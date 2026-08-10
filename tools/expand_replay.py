#!/usr/bin/env python3
"""Resimulate Cogs vs Clips replays through the live mettagrid engine.

Unlike an offline parser that reconstructs game logic from recorded state
deltas, this rebuilds the episode (config + seed embedded in the replay) and
replays the recorded per-agent actions through a fresh
`mettagrid.simulator.Simulation`, tick by tick. Stats are then read straight
off the live, re-simulated engine, so whatever handler logic is currently
installed in mettagrid actually runs.

Pass --apply-heart-fix to patch a resimulated hub's heart handlers in
memory with the actor-capacity guard from src/cogsguard/game/teams/hub.py
before stepping, so the same historical scenario can be replayed against
the fixed rule without needing a new episode recorded under the fix.

Known limitation: agent spawn placement during map generation has been
observed to drift by a small constant offset from the original recording
(root-caused to the underlying mettagrid map-builder, not this tool's
action replay, which was verified tick-for-tick correct). This does not
affect --apply-heart-fix results, since the fix eliminates wasted-heart
events by construction regardless of position. It can make the un-patched
resim's totals differ somewhat from a replay's own recorded totals, so
reconciliation mismatches are reported rather than treated as fatal; treat
tools/analyze_cvc_replays.py's ground-truth parse as the authoritative
"before" count and this tool's before/after pair as a same-methodology
comparison.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

try:
    import orjson
except ImportError:  # The stdlib fallback is correct, but much slower on this corpus.
    orjson = None

from mettagrid.config.filter import actorHas, isNot
from mettagrid.config.handler_config import FirstMatch
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation.stats_mutation import StatsMutation, StatsTarget
from mettagrid.simulator import Simulation

HEART_HANDLER_NAMES = ("get_heart", "make_and_get_heart")
RECONCILE_TOLERANCE = 1e-6


class ReconciliationError(RuntimeError):
    """Raised when a resim's live stats diverge from the replay's recorded stats."""


class Trace:
    __slots__ = ("changes", "index")

    def __init__(self, changes: list[tuple[int, Any]]) -> None:
        if not changes or changes[0][0] != 0:
            raise ValueError("RLE trace must start at step 0")
        self.changes = changes
        self.index = 0

    def advance(self, step: int) -> Any:
        changes = self.changes
        index = self.index
        while index + 1 < len(changes) and changes[index + 1][0] <= step:
            index += 1
        self.index = index
        return changes[index][1]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _action_trace(raw: Any) -> Trace:
    if isinstance(raw, list) and raw and isinstance(raw[0], list) and len(raw[0]) == 2 and _is_int(raw[0][0]):
        return Trace([(pair[0], int(pair[1])) for pair in raw])
    return Trace([(0, int(raw))])


def _load_replay(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if orjson is not None:
        return orjson.loads(data)
    return json.loads(data)


def _heart_limit(cfg: MettaGridConfig) -> int:
    for agent in cfg.game.agents:
        limits = agent.inventory.limits.get("heart")
        if limits is not None:
            return limits.base
    raise ReconciliationError("no agent has a heart inventory limit configured")


def apply_heart_capacity_fix(cfg: MettaGridConfig) -> int:
    """Patch hub heart handlers in place to require the actor has room.

    Mirrors the isNot(actorHas({"heart": limit})) guard added to
    src/cogsguard/game/teams/hub.py, applied directly to a deserialized
    replay config instead of via mission construction, so it works against
    any historical replay regardless of which mission produced it.
    """
    limit = _heart_limit(cfg)
    guard = isNot(actorHas({"heart": limit}))
    patched = 0
    for obj in cfg.game.objects.values():
        handler = obj.on_use_handler
        if not isinstance(handler, FirstMatch):
            continue
        for sub_handler in handler.handlers:
            if getattr(sub_handler, "name", None) in HEART_HANDLER_NAMES:
                sub_handler.filters = [guard, *sub_handler.filters]
                patched += 1
    return patched


def _heart_fire_stat_keys(cfg: MettaGridConfig) -> list[str]:
    """Game-stat keys incremented once per get_heart/make_and_get_heart trigger."""
    keys = []
    for obj in cfg.game.objects.values():
        handler = obj.on_use_handler
        if not isinstance(handler, FirstMatch):
            continue
        for sub_handler in handler.handlers:
            if getattr(sub_handler, "name", None) not in HEART_HANDLER_NAMES:
                continue
            for mutation in sub_handler.mutations:
                if isinstance(mutation, StatsMutation) and mutation.target == StatsTarget.GAME:
                    keys.append(mutation.stat)
                    break
    return keys


def _average_agent_stats(per_agent_stats: list[dict[str, float]]) -> dict[str, float]:
    if not per_agent_stats:
        return {}
    totals: dict[str, float] = {}
    for stats in per_agent_stats:
        for key, value in stats.items():
            totals[key] = totals.get(key, 0.0) + value
    return {key: total / len(per_agent_stats) for key, total in totals.items()}


def _is_heart_related(key: str) -> bool:
    return "heart" in key or "withdrawn" in key


def _reconcile(replay: dict[str, Any], game_stats: dict[str, float], per_agent_stats: list[dict[str, float]]) -> list[str]:
    """Cross-check the resim's live stats against the replay's own recorded stats.

    Scoped to heart/hub-economy keys, not every game stat. Returns mismatch
    descriptions rather than raising: map-generation drift in the underlying
    mettagrid engine (see module docstring) can shift a replay's trajectory
    enough that hub-economy totals don't match exactly, without indicating a
    bug in this tool's action replay itself.
    """
    mismatches: list[str] = []
    expected_game = replay["infos"].get("game", {})
    for key, expected in expected_game.items():
        if not _is_heart_related(key):
            continue
        actual = game_stats.get(key, 0.0)
        if abs(actual - expected) > RECONCILE_TOLERANCE:
            mismatches.append(f"game stat {key!r} diverged: resim={actual} replay={expected}")

    expected_agent = replay["infos"].get("agent", {})
    actual_agent_avg = _average_agent_stats(per_agent_stats)
    for key, expected in expected_agent.items():
        if not _is_heart_related(key):
            continue
        actual = actual_agent_avg.get(key, 0.0)
        if abs(actual - expected) > max(RECONCILE_TOLERANCE, abs(expected) * 1e-4):
            mismatches.append(f"average agent stat {key!r} diverged: resim={actual} replay={expected}")
    return mismatches


def resim_replay(path: Path, *, apply_fix: bool, reconcile: bool, strict_reconcile: bool) -> dict[str, Any]:
    replay = _load_replay(path)
    cfg = MettaGridConfig.model_validate(replay["mg_config"])
    stat_keys = _heart_fire_stat_keys(cfg)
    if apply_fix:
        patched = apply_heart_capacity_fix(cfg)
        if patched == 0:
            raise ReconciliationError("no heart handlers found to patch")

    seed = replay["infos"]["attributes"]["seed"]
    sim = Simulation(cfg, seed=seed)

    action_names = replay["action_names"]
    agent_traces: dict[int, Trace] = {}
    for obj in replay["objects"]:
        agent_id = obj.get("agent_id")
        if agent_id is not None:
            agent_traces[agent_id] = _action_trace(obj["action_id"])

    if len(agent_traces) != replay["num_agents"]:
        raise ReconciliationError(f"found {len(agent_traces)} agent action traces, expected {replay['num_agents']}")

    steps = replay.get("infos", {}).get("attributes", {}).get("steps") or replay["max_steps"]

    for step in range(1, steps + 1):
        for agent_id, trace in agent_traces.items():
            action_id = trace.advance(step)
            sim.agent(agent_id).set_action(action_names[action_id])
        sim.step()

    stats = sim.episode_stats
    game_stats = dict(stats["game"])
    per_agent_stats = [dict(entry) for entry in stats["agent"]]
    sim.close()

    mismatches: list[str] = []
    if reconcile and not apply_fix:
        mismatches = _reconcile(replay, game_stats, per_agent_stats)
        if mismatches and strict_reconcile:
            raise ReconciliationError("; ".join(mismatches))

    craft_or_withdraw_fires = sum(game_stats.get(key, 0.0) for key in stat_keys)
    hearts_gained = sum(agent.get("heart.gained", 0.0) for agent in per_agent_stats)
    wasted_hearts = max(0, round(craft_or_withdraw_fires - hearts_gained))

    return {
        "replay_file": path.name,
        "apply_fix": apply_fix,
        "steps": steps,
        "heart_handler_fires": round(craft_or_withdraw_fires),
        "hearts_gained": round(hearts_gained),
        "wasted_hearts": wasted_hearts,
        "reconciliation_mismatches": mismatches,
    }


def _resim_worker(args: tuple[str, bool, bool, bool]) -> dict[str, Any]:
    path_string, apply_fix, reconcile, strict_reconcile = args
    path = Path(path_string)
    try:
        return resim_replay(path, apply_fix=apply_fix, reconcile=reconcile, strict_reconcile=strict_reconcile)
    except Exception as error:
        raise RuntimeError(f"{path.name}: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="a .replay file or a directory of .replay files")
    parser.add_argument("--output", type=Path, help="write per-replay JSONL rows here instead of stdout")
    parser.add_argument("--apply-heart-fix", action="store_true", help="patch in the actor-capacity guard before resimming")
    parser.add_argument(
        "--no-reconcile",
        action="store_true",
        help="skip cross-checking resim stats against the replay's own recorded stats",
    )
    parser.add_argument(
        "--strict-reconcile",
        action="store_true",
        help="fail a replay outright on any reconciliation mismatch instead of just reporting it",
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0, help="resim only the first N sorted files")
    args = parser.parse_args()

    paths = sorted(args.input.glob("*.replay")) if args.input.is_dir() else [args.input]
    if args.limit > 0:
        paths = paths[: args.limit]
    if not paths:
        parser.error(f"no .replay files found at {args.input}")

    reconcile = not args.no_reconcile
    tasks = [(str(path), args.apply_heart_fix, reconcile, args.strict_reconcile) for path in paths]

    rows: list[dict[str, Any]] = []
    if args.workers == 1:
        for task in tasks:
            rows.append(_resim_worker(task))
            if len(rows) % 25 == 0 or len(rows) == len(tasks):
                print(f"resimmed {len(rows)}/{len(tasks)} replays", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(_resim_worker, task): task for task in tasks}
            for future in as_completed(futures):
                rows.append(future.result())
                if len(rows) % 25 == 0 or len(rows) == len(tasks):
                    print(f"resimmed {len(rows)}/{len(tasks)} replays", flush=True)
    rows.sort(key=lambda row: row["replay_file"])

    total_wasted = sum(row["wasted_hearts"] for row in rows)
    mismatched = sum(1 for row in rows if row["reconciliation_mismatches"])
    print(f"total wasted_hearts across {len(rows)} replays (apply_fix={args.apply_heart_fix}): {total_wasted}")
    if reconcile and not args.apply_heart_fix:
        print(f"{mismatched}/{len(rows)} replays had reconciliation mismatches (see module docstring)")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
