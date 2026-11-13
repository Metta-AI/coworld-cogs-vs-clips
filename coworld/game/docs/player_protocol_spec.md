# Player Protocol

Connect to `/player?slot=<slot>&token=<token>` with a websocket. `slot` is zero-indexed and `token` must match the token
supplied by the Coworld runner for that slot.

The first accepted message is a rendering/configuration subset for the slot:

```json
{
  "type": "player_config",
  "protocol": "coworld.player.v1",
  "mission": "cogsguard",
  "slot": 0,
  "connection_id": "player-0",
  "num_agents": 2,
  "action_names": ["noop", "move_north", "move_south"],
  "observation_shape": [500, 3],
  "policy_env": {
    "action_names": ["noop", "move_north", "move_south"],
    "num_agents": 2,
    "observation_shape": [500, 3],
    "egocentric_shape": [13, 13]
  },
  "observation": {
    "width": 13,
    "height": 13,
    "features": [{ "id": 6, "name": "tag", "normalization": 10.0 }],
    "tags": ["agent", "wall"],
    "global_location": 254,
    "empty_location": 255
  },
  "control_state": {
    "control_mode": "policy",
    "human_controller_connection_id": null,
    "tick_mode": "fixed",
    "human_action_timeout_seconds": 5.0
  }
}
```

At each simulator step the engine sends the raw MettaGrid token observation:

```json
{
  "type": "observation",
  "protocol": "coworld.player.v1",
  "mission": "cogsguard",
  "slot": 0,
  "step": 1,
  "observation": [
    [254, 1, 0],
    [102, 6, 1]
  ],
  "visible_talk": [
    { "agent_id": 1, "text": "hello", "row": 6, "col": 6, "remaining_steps": 2 }
  ],
  "scores": [0.0, 0.0],
  "is_human_controlled": false,
  "control_state": {
    "control_mode": "policy",
    "human_controller_connection_id": null,
    "tick_mode": "fixed",
    "human_action_timeout_seconds": 5.0
  }
}
```

Observation tokens are `[packed_location, feature_id, value]`. `packed_location == 254` is a global feature and
`packed_location == 255` is padding. Spatial locations use `row = packed_location // 16` and
`col = packed_location % 16` within the configured egocentric observation window.
`visible_talk` contains only speech visible to this slot. `cogsguard.semantic.wire` validates these messages and
reconstructs the game-owned semantic state for `cogsguard`, `machina_1`, and `four_score` missions.

The player responds with an action index:

```json
{ "type": "action", "action_index": 0 }
```

or an action name:

```json
{
  "type": "action",
  "action_name": "noop",
  "policy_infos": { "reason": "blocked" },
  "request_id": "step-1"
}
```

Default control is policy. Any non-controller connection can keep submitting policy actions for its slot. A player
connection can explicitly take human control:

```json
{ "type": "takeover" }
```

Only that connection's actions control the slot while takeover is active. Policy connections still receive observations
and may keep submitting actions and policy infos, but those actions are ignored until human control is released:

```json
{ "type": "release_takeover" }
```

If a human-controlled slot is idle for a tick, the applied action is `noop`. Invalid or missing actions are treated as
`noop`. A player can reconnect to the same slot with the same token while the episode is running.


## Polyworld variants

`polyworld-machina-daily` and `polyworld-four-score` use the same
`coworld.player.v1` container exchange, implemented by the upstream game.
They also accept BASIC source or tensor ZIP file seats alongside containers.
MettaGrid variants continue to require containers.

Polyworld declares its observation reconstruction in `player_config.observation_contract`:
`polyworld-machina-74/v1` for both cooperative CvC and FourScore. The 134-feature
dense tensor interface belongs to file policies, not Docker players. These are not MettaGrid checkpoint
parity guarantees. Qualify an imported policy against its selected variant.
Only noop and the four movement actions are supported; vibe actions and speech
are not implemented. See the pinned upstream `docs/policies.md` and
`docs/cooperative-migration.md` for file-policy APIs and qualification.

Polyworld permits one authenticated connection per seat. It waits up to 300 seconds
for startup and 30 seconds for each action. Invalid actions and disconnects terminate
the episode with an attributed player failure; they do not become noops.
A nonempty `request_id` must match `step-N`; stale replies do not extend the deadline.
Human takeover and reconnection described above apply only to the MettaGrid runtime.

### CPU player defaults

The reference Dockerfile bounds OpenMP, MKL, OpenBLAS, and NumExpr to one thread.
The bundled player reserves and caps one CPU. Use the same explicit allocation
when uploading a CPU policy:

```sh
coworld upload-policy my-cvc-player:latest --cpu 1 --cpu-limit 1 --memory 1Gi
```

For PyTorch models, set both pools before loading the model or running inference:

```python
import torch

torch.set_num_threads(1)
torch.set_num_interop_threads(1)
```

Size memory for the model. If additional CPUs are necessary, measure concurrent
matches and increase the reservation, limit, and thread counts together. A fast
single-container benchmark does not establish performance on a shared worker.

Polyworld game logs emit `player_timing` JSON every 1,000 actions per remote seat.
`reply_wait_ms` is cumulative observation-to-reply wall time; `maximum_reply_wait_ms`
is the slowest reply. These include transport and scheduling, not just inference.
Reception timestamps exclude time a reply spends waiting in the game's event queue.
Use the episode's slot-to-policy roster to identify slow players. Timing diagnostics
contain no observations, actions, credentials, or model output, and do not change scores.
