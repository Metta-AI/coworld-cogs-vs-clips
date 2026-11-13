# Global Protocol

The selected variant owns its viewer and wire format. Open `/client/global`
with the platform-provided `address` query parameter; do not choose a renderer
from player runtime (file versus container). Both engines support live spectating.

## Polyworld variants

`polyworld-machina-daily` and `polyworld-four-score` serve their matching browser
renderer and assets from the game image. The read-only `/global` WebSocket sends
a binary Polyworld action-tape replay snapshot on connect and on the text request
`snapshot`. Before initialization it sends `{"type":"waiting"}`. The browser
requests the current snapshot once per second. The simulation retains one tape
and publishes initial/final state plus at most one update per second.

Every snapshot is an append to the same episode. The viewer checks replay setup,
previous actions, and per-tick hashes. A reconnect or late join receives the
current tape; paused viewers retain their position and Play catches up. Player
credentials, policy logs, and private observations are absent from this stream.
The final snapshot is identical to the saved replay, and existing recordings
remain readable through the shared static replay bundle.

## MettaGrid variants

`machina-1-daily` and `four-score-daily` retain the MettaScope protocol below.

Connect to `/global` with a websocket. The endpoint accepts viewers before or during an episode and speaks the
`mettagrid.mettascope.live.v1` live-replay protocol used by the websocket-capable MettaScope build.

The first message is a small readiness frame:

```json
{
  "type": "hello",
  "protocol": "mettagrid.mettascope.live.v1",
  "status": {
    "mission": "cogsguard",
    "connected_players": 1,
    "num_agents": 2,
    "done": false
  }
}
```

The next message assigns the global viewer to the live replay:

```json
{
  "type": "assign",
  "protocol": "mettagrid.mettascope.live.v1",
  "agent_id": -1,
  "initial_replay": {
    "version": 2,
    "action_names": ["noop", "move_north"],
    "item_names": ["energy"],
    "type_names": ["agent", "wall"],
    "map_size": [24, 24],
    "num_agents": 2,
    "mg_config": {}
  },
  "status": {
    "mission": "cogsguard",
    "connected_players": 1,
    "num_agents": 2,
    "done": false
  }
}
```

The `hello` and `assign` frames intentionally keep status metadata under `status` without a nested `step` key. This
keeps older Emscripten MettaScope builds from mistaking those pre-replay envelopes for replay step frames.

Each viewer receives a baseline MettaGrid replay step containing static walls and the current agent/object state:

```json
{
  "type": "step",
  "protocol": "mettagrid.mettascope.live.v1",
  "step": 0,
  "objects": [
    { "id": 1, "type_name": "wall", "location": [0, 0], "alive": true },
    {
      "id": 10,
      "type_name": "agent",
      "location": [6, 6],
      "agent_id": 0,
      "is_agent": true
    }
  ],
  "episode_stats": {},
  "state": {
    "type": "state",
    "scores": [0.0, 0.0],
    "paused": false,
    "done": false
  }
}
```

Subsequent delta steps use the same replay frame shape, but may omit static walls:

```json
{
  "type": "step",
  "protocol": "mettagrid.mettascope.live.v1",
  "step": 1,
  "objects": [
    {
      "id": 10,
      "type_name": "agent",
      "location": [6, 6],
      "agent_id": 0,
      "is_agent": true
    }
  ],
  "episode_stats": {},
  "state": {
    "type": "state",
    "scores": [0.0, 0.0],
    "paused": false,
    "done": false
  }
}
```

The HTTP `/client/global` client loads the bundled websocket-capable MettaScope from
`/mettascope/mettascope.html?ws=...` when the Docker image includes it, and keeps a lightweight canvas fallback
connected to the `/global` websocket. A mid-episode viewer receives a fresh `assign` frame and a step frame containing
static walls plus the latest dynamic objects, so it can render from its join point.

When the episode completes, the server sends a terminal frame:

```json
{
  "type": "done",
  "protocol": "mettagrid.mettascope.live.v1",
  "steps": 120,
  "status": {
    "mission": "cogsguard",
    "done": true,
    "scores": [1.0, 0.0],
    "num_agents": 2,
    "connected_players": 1,
    "action_names": ["noop", "move_north"],
    "protocol": "mettagrid.mettascope.live.v1"
  }
}
```

The global websocket may also receive MettaScope action/control messages:

```json
{ "type": "action", "agent_id": 0, "action_name": "move_north" }
{ "type": "control", "command": "pause" }
{ "type": "control", "command": "speed", "speed": 5.0 }
```

Replay mode starts the same image with `COGAME_LOAD_REPLAY_URI=<uri>`. The server serves `GET /client/replay`, redirects
bundled MettaScope to an extension-bearing `GET /replay-data.json*` URL, and sends the saved live-replay artifact over
`WEBSOCKET /replay`.
