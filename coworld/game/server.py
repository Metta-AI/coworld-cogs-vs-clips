from __future__ import annotations

import asyncio
import gzip
import json
import os
import tempfile
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import unquote, urlencode, urlparse

import numpy as np
import uvicorn
from cogsguard.missions.machina_1 import make_cogsguard_mission, make_machina1_mission
from coworld.runner.io import read_data, write_data
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.map_builder.map_builder import HasSeed
from mettagrid.renderer.common import METTASCOPE_REPLAY_URL_PREFIX
from mettagrid.runner.live_episode import LiveMettaGridEpisode, TickMode
from mettagrid.simulator.replay_log_writer import EpisodeReplay
from mettagrid.util.grid_object_formatter import format_grid_object

CLIENT_DIR = Path(__file__).parent / "client"
METTASCOPE_DIST_DIR = Path(
    os.environ.get("METTASCOPE_DIST_DIR", Path(__file__).parent / "mettascope")
)
GLOBAL_PROTOCOL = "mettagrid.mettascope.live.v1"
START_GRACE_SECONDS = 0.5
POLICY_ACTION_TIMEOUT_SECONDS = 0.1
GAME_HOST = os.environ.get("COGAME_HOST", "0.0.0.0")
GAME_PORT = int(os.environ.get("COGAME_PORT", "8080"))


def build_initial_replay(sim) -> tuple[dict[str, Any], list[str], dict[int, int]]:
    game_config = sim.config.game
    game_config_dict = game_config.model_dump(mode="json", exclude_none=True)
    # The simulator-only event table can balloon to >1 MiB (cogsguard generates
    # one EventConfig per (lane, direction, search radius) tuple), pushing the
    # assign frame past the websockets-library default max_size of 1 MiB on the
    # Observatory proxy. No mettascope client field consumes it.
    game_config_dict.pop("events", None)
    agent_inv_limits = (
        game_config.agents[0].inventory.limits if game_config.agents else {}
    )
    capacity_names = sorted(agent_inv_limits.keys())
    resource_to_capacity_id = {}
    for capacity_id, capacity_name in enumerate(capacity_names):
        for resource_name in agent_inv_limits[capacity_name].resources:
            resource_to_capacity_id[sim.resource_names.index(resource_name)] = (
                capacity_id
            )
    id_map = game_config.id_map()
    tags = {name: idx for idx, name in enumerate(id_map.tag_names())}
    return (
        {
            "version": 2,
            "action_names": list(sim.action_ids.keys()),
            "item_names": sim.resource_names,
            "type_names": sim.object_type_names,
            "capacity_names": capacity_names,
            "tags": tags,
            "map_size": [sim.map_width, sim.map_height],
            "num_agents": sim.num_agents,
            "max_steps": 0,
            "mg_config": {"label": "Cogs vs Clips Live", "game": game_config_dict},
            "objects": [],
        },
        capacity_names,
        resource_to_capacity_id,
    )


def build_step_replay(
    sim,
    action_indices: list[int],
    capacity_names: list[str],
    resource_to_capacity_id: dict[int, int],
    policy_infos_by_agent: dict[int, dict[str, Any]] | None = None,
    ignored_object_types: list[str] | None = None,
) -> dict[str, Any]:
    actions = np.asarray(action_indices, dtype=np.int32)
    rewards = np.zeros(sim.num_agents)
    objects = []
    for grid_object in sim.grid_objects(
        ignore_types=ignored_object_types or []
    ).values():
        agent_id = grid_object.get("agent_id")
        policy_infos = (
            policy_infos_by_agent.get(agent_id)
            if agent_id is not None and policy_infos_by_agent
            else None
        )
        formatted = format_grid_object(
            grid_object,
            actions,
            sim.action_success,
            rewards,
            sim.episode_rewards,
            policy_infos=policy_infos,
        )
        raw_capacities = formatted.pop("inventory_capacities_raw", {})
        group_capacities = {}
        for resource_id, effective_limit in raw_capacities.items():
            capacity_id = resource_to_capacity_id.get(resource_id)
            if capacity_id is not None and capacity_id not in group_capacities:
                group_capacities[capacity_id] = effective_limit
        formatted["inventory_capacities"] = sorted(group_capacities.items())
        objects.append(formatted)
    return {
        "step": sim.current_step,
        "objects": objects,
        "episode_stats": sim._c_sim.get_episode_stats(),
        "capacity_names": capacity_names,
    }


class CogsVsClipsGame:
    def __init__(
        self,
        config: dict[str, Any],
        results_path: Path,
        replay_path: Path | None,
        request_shutdown: Callable[[], None],
        results_uri: str | None = None,
        replay_uri: str | None = None,
    ):
        self.mission_name = config["mission"]
        self.tokens = config["tokens"]
        self.policy_names = [player["name"] for player in config["players"]]
        if len(self.policy_names) != len(self.tokens):
            raise ValueError(f"config.players must contain {len(self.tokens)} players")
        max_steps = config["max_steps"]
        seed = config["seed"]

        env = make_env(
            self.mission_name,
            num_agents=len(self.tokens),
            max_steps=max_steps,
            seed=seed,
        )
        self.episode = LiveMettaGridEpisode.from_env(
            env,
            seed=seed,
            tokens=self.tokens,
            max_steps=max_steps,
            step_seconds=config["step_seconds"],
            message_context={"mission": self.mission_name},
            start_grace_seconds=START_GRACE_SECONDS,
            wait_for_all_players=True,
            policy_action_timeout_seconds=POLICY_ACTION_TIMEOUT_SECONDS,
            disconnect_exception_types=(RuntimeError, WebSocketDisconnect),
            request_shutdown=request_shutdown,
        )
        self.episode.configure_artifacts(
            results_path=results_path,
            replay_path=None,
            results_builder=self.results,
        )
        self.sim = self.episode.sim
        self.replay_path = replay_path
        self.results_uri = results_uri
        self.replay_uri = replay_uri
        self.replay = EpisodeReplay(self.sim) if replay_path is not None else None
        self.replay_written = False
        (
            self.initial_replay,
            self.capacity_names,
            self.resource_to_capacity_id,
        ) = build_initial_replay(self.sim)
        self.episode.configure_replay_events(
            baseline_builder=lambda: {"type": "baseline"},
            step_builder=self.record_replay_step,
        )

    def handle_global_message(self, message: dict[str, Any]) -> None:
        message_type = message["type"]
        if message_type == "action":
            agent_id = int(message["agent_id"])
            if 0 <= agent_id < len(self.tokens):
                self.episode.set_policy_action(
                    agent_id, message, connection_id="global"
                )
            return
        if message_type != "control":
            return
        command = str(message["command"]).lower()
        if command in {"play", "resume", "start"}:
            self.episode.paused = False
        elif command in {"pause", "stop"}:
            self.episode.paused = True
        elif command == "speed":
            speed = float(message["speed"])
            if speed > 0:
                self.episode.step_seconds = 1.0 / speed
        elif command == "step":
            self.episode.paused = False

    def global_assign_message(self) -> dict[str, Any]:
        return {
            "type": "assign",
            "protocol": GLOBAL_PROTOCOL,
            "agent_id": -1,
            "initial_replay": self.initial_replay,
            "status": self.global_status(),
        }

    def global_hello_message(self) -> dict[str, Any]:
        return {
            "type": "hello",
            "protocol": GLOBAL_PROTOCOL,
            "status": self.global_status(),
        }

    def global_baseline_message(self) -> dict[str, Any]:
        return self._global_step_message()

    def global_delta_message(self) -> dict[str, Any]:
        return self._global_step_message(ignored_object_types=["wall"])

    def record_replay_step(self) -> dict[str, Any]:
        if self.replay is not None:
            self.sim._context["policy_infos"] = self.policy_infos_by_agent()
            self.replay.log_step(
                self.sim.current_step,
                self.sim._c_sim.actions(),
                self.sim._c_sim.rewards(),
            )
        return {"type": "step", "step": self.sim.current_step}

    def write_replay(self) -> None:
        if self.replay_path is None or self.replay is None or self.replay_written:
            return
        self.replay_path.parent.mkdir(parents=True, exist_ok=True)
        self.replay_path.write_text(
            json.dumps(self.replay.get_replay_data()), encoding="utf-8"
        )
        self.replay_written = True

    def _global_step_message(
        self, *, ignored_object_types: list[str] | None = None
    ) -> dict[str, Any]:
        return {
            "type": "step",
            "protocol": GLOBAL_PROTOCOL,
            **build_step_replay(
                self.sim,
                self.episode.latest_action_indices,
                self.capacity_names,
                self.resource_to_capacity_id,
                policy_infos_by_agent=self.policy_infos_by_agent(),
                ignored_object_types=ignored_object_types,
            ),
            "state": self.snapshot(),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.episode.snapshot(),
            "global_protocol": GLOBAL_PROTOCOL,
            "policy_names": self.policy_names,
        }

    def admin_snapshot(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        snapshot["slots"] = [
            {
                **slot_state,
                "takeover_url": self.takeover_url(int(slot_state["slot"])),
            }
            for slot_state in snapshot["slots"]
        ]
        return snapshot

    def takeover_url(self, slot: int) -> str:
        return f"/client/player?{urlencode({'slot': slot, 'token': self.tokens[slot], 'takeover': 1})}"

    def global_status(self) -> dict[str, Any]:
        return {
            "mission": self.mission_name,
            "done": self.episode.done,
            "scores": self.scores(),
            "policy_names": self.policy_names,
            "num_agents": len(self.tokens),
            "connected_players": len(self.episode.connections),
            "action_names": self.episode.action_names,
            "protocol": GLOBAL_PROTOCOL,
        }

    def scores(self) -> list[float]:
        return [float(score) for score in self.sim.episode_rewards.tolist()]

    def results(self) -> dict[str, Any]:
        self.write_replay()
        results = {
            "scores": self.scores(),
            "steps": self.sim.current_step,
            "mission": self.mission_name,
        }
        if self.results_uri is not None:
            write_data(
                self.results_uri,
                json.dumps(results),
                content_type="application/json",
                http_method=artifact_method("COGAME_RESULTS_METHOD"),
            )
        if self.replay_uri is not None and self.replay_path is not None:
            write_data(
                self.replay_uri,
                self.replay_path.read_bytes(),
                content_type="application/json",
                http_method=artifact_method("COGAME_SAVE_REPLAY_METHOD"),
            )
        return results

    def policy_infos_by_agent(self) -> dict[int, dict[str, Any]]:
        infos_by_agent: dict[int, dict[str, Any]] = {}
        for slot, action in enumerate(self.episode.latest_policy_actions):
            policy_infos = dict(action.policy_infos)
            if slot < len(self.policy_names):
                policy_infos["policy_name"] = self.policy_names[slot]
            if policy_infos:
                infos_by_agent[slot] = policy_infos
        return infos_by_agent


def make_env(
    mission_name: str, *, num_agents: int, max_steps: int, seed: int
) -> MettaGridConfig:
    if mission_name == "machina_1":
        mission = make_machina1_mission(num_agents=num_agents, max_steps=max_steps)
    elif mission_name == "cogsguard":
        mission = make_cogsguard_mission(num_agents=num_agents, max_steps=max_steps)
    else:
        raise ValueError(f"Unknown mission: {mission_name}")
    env = mission.make_env()
    map_builder = env.game.map_builder
    if not isinstance(map_builder, HasSeed):
        raise TypeError(f"{mission_name} map builder must support seeding")
    map_builder.seed = seed
    return env


def noop_shutdown() -> None:
    pass


def artifact_method(env_var: str) -> Literal["POST", "PUT"]:
    method = os.environ.get(env_var, "PUT").upper()
    if method not in {"POST", "PUT"}:
        raise ValueError(f"{env_var} must be PUT or POST")
    return cast(Literal["POST", "PUT"], method)


def _artifact_path(uri: str, filename: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if parsed.scheme in {"http", "https"}:
        return Path(tempfile.mkdtemp(prefix="cogs-vs-clips-")) / filename
    if parsed.scheme == "":
        return Path(uri)
    raise ValueError(f"Unsupported cogs_vs_clips artifact URI: {uri}")


def _mount_mettascope(app: FastAPI) -> bool:
    if not METTASCOPE_DIST_DIR.is_dir():
        return False
    app.mount(
        "/mettascope", StaticFiles(directory=METTASCOPE_DIST_DIR), name="mettascope"
    )
    return True


def create_app(
    config: dict[str, Any],
    results_path: Path,
    replay_path: Path | None,
    request_shutdown: Callable[[], None] = noop_shutdown,
    results_uri: str | None = None,
    replay_uri: str | None = None,
) -> FastAPI:
    game = CogsVsClipsGame(
        config,
        results_path=results_path,
        replay_path=replay_path,
        request_shutdown=request_shutdown,
        results_uri=results_uri,
        replay_uri=replay_uri,
    )
    app = FastAPI()
    _mount_mettascope(app)

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/client/global")
    def global_client() -> HTMLResponse:
        return HTMLResponse((CLIENT_DIR / "global.html").read_text())

    @app.get("/client/admin")
    def admin_client() -> HTMLResponse:
        return HTMLResponse((CLIENT_DIR / "admin.html").read_text())

    @app.get("/client/replay")
    def replay_client() -> HTMLResponse:
        return HTMLResponse((CLIENT_DIR / "replay.html").read_text())

    @app.get("/client/player")
    def player_client() -> HTMLResponse:
        return HTMLResponse((CLIENT_DIR / "player.html").read_text())

    @app.websocket("/global")
    async def global_viewer(websocket: WebSocket) -> None:
        await websocket.accept()
        sender = asyncio.create_task(_send_global_snapshots(websocket))
        receiver = asyncio.create_task(_drain_global_messages(websocket))
        done, pending = await asyncio.wait(
            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    async def _send_global_snapshots(websocket: WebSocket) -> None:
        await websocket.send_json(game.global_hello_message())
        await websocket.send_json(game.global_assign_message())
        await websocket.send_json(game.global_baseline_message())
        while not game.episode.done:
            await asyncio.sleep(game.episode.step_seconds)
            await websocket.send_json(game.global_delta_message())
        await websocket.send_json(
            {
                "type": "done",
                "protocol": GLOBAL_PROTOCOL,
                "steps": game.sim.current_step,
                "status": game.global_status(),
            }
        )

    async def _drain_global_messages(websocket: WebSocket) -> None:
        async for message in websocket.iter_json():
            game.handle_global_message(message)

    @app.websocket("/admin")
    async def admin(websocket: WebSocket) -> None:
        await websocket.accept()
        send_lock = asyncio.Lock()
        sender = asyncio.create_task(_send_admin_snapshots(websocket, send_lock))
        receiver = asyncio.create_task(_drain_admin_commands(websocket, send_lock))
        done, pending = await asyncio.wait(
            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    async def _send_admin_snapshots(
        websocket: WebSocket, send_lock: asyncio.Lock
    ) -> None:
        while not game.episode.done:
            await _send_admin_snapshot(websocket, send_lock)
            await asyncio.sleep(0.25)
        await _send_admin_snapshot(websocket, send_lock)

    async def _drain_admin_commands(
        websocket: WebSocket, send_lock: asyncio.Lock
    ) -> None:
        async for command in websocket.iter_json():
            if command["command"] == "pause":
                game.episode.paused = True
            elif command["command"] == "resume":
                game.episode.paused = False
            elif command["command"] == "step_seconds":
                game.episode.step_seconds = float(command["step_seconds"])
            elif command["command"] == "tick_mode":
                tick_mode = command["tick_mode"]
                if tick_mode not in {"fixed", "tick_when_act"}:
                    raise ValueError(f"Unknown tick_mode: {tick_mode}")
                game.episode.tick_mode = cast(TickMode, tick_mode)
            elif command["command"] == "human_action_timeout_seconds":
                game.episode.human_action_timeout_seconds = float(
                    command["human_action_timeout_seconds"]
                )
            elif command["command"] == "boot_connection":
                await game.episode.boot_connection(str(command["connection_id"]))
            await _send_admin_snapshot(websocket, send_lock)

    async def _send_admin_snapshot(
        websocket: WebSocket, send_lock: asyncio.Lock
    ) -> None:
        async with send_lock:
            await websocket.send_json(game.admin_snapshot())

    @app.websocket("/player")
    async def player(websocket: WebSocket) -> None:
        if (
            "slot" not in websocket.query_params
            or "token" not in websocket.query_params
        ):
            await websocket.close(code=1008)
            return

        slot = int(websocket.query_params["slot"])
        token = websocket.query_params["token"]
        if slot < 0 or slot >= len(game.tokens) or game.tokens[slot] != token:
            await websocket.close(code=1008)
            return

        await websocket.accept()
        connection_id = await game.episode.connect_player(slot, websocket)
        async for message in websocket.iter_json():
            if game.episode.done:
                break
            await game.episode.handle_player_message(connection_id, message)
        game.episode.disconnect_player(connection_id)

    return app


def load_replay_data(replay_uri: str) -> dict[str, Any]:
    replay_data = read_data(replay_uri)
    if replay_uri.endswith(".json.gz"):
        replay_data = gzip.decompress(replay_data)
    elif replay_uri.endswith(".json.z"):
        replay_data = zlib.decompress(replay_data)
    return json.loads(replay_data)


def create_replay_app(replay_uri: str) -> FastAPI:
    app = FastAPI()
    has_mettascope = _mount_mettascope(app)
    mettascope_url = (
        "../mettascope/mettascope.html"
        if has_mettascope
        else METTASCOPE_REPLAY_URL_PREFIX.removesuffix("?replay=")
    )

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/client/replay")
    def replay_client() -> HTMLResponse:
        return HTMLResponse(
            f"""<!doctype html>
<meta charset="utf-8">
<title>Cogs vs Clips Replay</title>
<body>Loading replay...</body>
<script>
const mettascopeUrl = new URL({json.dumps(mettascope_url)}, window.location.href);
mettascopeUrl.searchParams.set("replay", new URL("../replay-data", window.location.href).href);
mettascopeUrl.searchParams.set("autostart", "true");
window.location.replace(mettascopeUrl.href);
</script>
"""
        )

    @app.get("/replay-data", name="replay_data")
    def replay_data() -> Response:
        return Response(
            read_data(replay_uri),
            media_type="application/octet-stream",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.websocket("/replay")
    async def replay_viewer(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"type": "replay", **load_replay_data(replay_uri)})
        async for command in websocket.iter_json():
            await websocket.send_json({"type": "control", "command": command})

    return app


def load_app_from_env(request_shutdown: Callable[[], None] = noop_shutdown) -> FastAPI:
    if "COGAME_LOAD_REPLAY_URI" in os.environ:
        return create_replay_app(os.environ["COGAME_LOAD_REPLAY_URI"])
    config = json.loads(read_data(os.environ["COGAME_CONFIG_URI"]))
    results_uri = os.environ["COGAME_RESULTS_URI"]
    results_path = _artifact_path(results_uri, "results.json")
    raw_replay_uri = os.environ.get("COGAME_SAVE_REPLAY_URI")
    replay_path = (
        _artifact_path(raw_replay_uri, "replay.json") if raw_replay_uri else None
    )
    return create_app(
        config,
        results_path=results_path,
        replay_path=replay_path,
        request_shutdown=request_shutdown,
        results_uri=results_uri,
        replay_uri=raw_replay_uri,
    )


def main() -> None:
    server: uvicorn.Server

    def request_shutdown() -> None:
        server.should_exit = True

    server = uvicorn.Server(
        uvicorn.Config(
            load_app_from_env(request_shutdown), host=GAME_HOST, port=GAME_PORT
        )
    )
    server.run()


if __name__ == "__main__":
    main()
