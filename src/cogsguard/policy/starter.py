"""Game-owned CogsGuard teacher with fixed mining and alignment roles."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from heapq import heappop, heappush

from mettagrid.policy.policy import (
    MultiAgentPolicy,
    StatefulAgentPolicy,
    StatefulPolicyImpl,
)
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

STARTER_ROLE_CYCLE = ("miner", "aligner")
ALL_ROLES = ("miner", "aligner", "scrambler", "scout")
ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
WANDER_DIRECTIONS = ("east", "south", "west", "north")
TEAM_TAG_PREFIX = "team:"
MAX_REMEMBERED_JUNCTION_DISTANCE = 24
MAX_ALIGNER_JUNCTION_FRONTIER_DISTANCE = 25
MAX_ALIGNER_RETURN_TO_FRONTIER_DISTANCE = 20
MOVE_DELTAS = {
    "north": (-1, 0),
    "south": (1, 0),
    "west": (0, -1),
    "east": (0, 1),
}
Coordinate = tuple[int, int]


@dataclass
class StarterCogState:
    """Small amount of map memory so starter cogs can avoid tiny local loops."""

    explore_direction_index: int
    position: Coordinate = (0, 0)
    visited: set[Coordinate] = field(default_factory=lambda: {(0, 0)})
    blocked: set[Coordinate] = field(default_factory=set)
    seen_tags_by_position: dict[Coordinate, set[int]] = field(default_factory=dict)
    last_move_direction: str | None = None


class StarterCogPolicyImpl(StatefulPolicyImpl[StarterCogState]):
    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        role: str | None = None,
    ):
        self._policy_env_info = policy_env_info
        self._role = role or STARTER_ROLE_CYCLE[agent_id % len(STARTER_ROLE_CYCLE)]
        self._explore_direction_start = (
            ALL_ROLES.index(self._role) + agent_id // len(STARTER_ROLE_CYCLE)
        ) % len(WANDER_DIRECTIONS)

        self._center = (policy_env_info.obs_height // 2, policy_env_info.obs_width // 2)
        self._tag_name_to_id = {
            name: idx for idx, name in enumerate(policy_env_info.tags)
        }

        # Starter policies only target the current canonical CvC action and tag contract. If that contract changes, we
        # want the policy to fail loudly instead of carrying compat shims forever.
        required_action_names = {"noop"} | {
            f"move_{direction}" for direction in MOVE_DELTAS
        }
        missing_action_names = required_action_names - set(policy_env_info.action_names)
        assert not missing_action_names, (
            f"Starter policy requires actions {sorted(missing_action_names)}"
        )

        required_tag_names = {
            "type:agent",
            "type:wall",
            "type:hub",
            "type:junction",
            *(f"type:{role_name}" for role_name in ALL_ROLES),
            *(f"type:{element}_extractor" for element in ELEMENTS),
        }
        missing_tag_names = required_tag_names - self._tag_name_to_id.keys()
        assert not missing_tag_names, (
            f"Starter policy requires tags {sorted(missing_tag_names)}"
        )

        self._noop_action_name = "noop"
        self._move_action_names = {
            direction: f"move_{direction}" for direction in MOVE_DELTAS
        }
        self._team_tag_ids = {
            idx
            for idx, name in enumerate(policy_env_info.tags)
            if name.startswith(TEAM_TAG_PREFIX)
        }
        self._agent_tags = {self._tag_name_to_id["type:agent"]}
        self._wall_tags = {self._tag_name_to_id["type:wall"]}
        self._role_station_tags = {
            role_name: {self._tag_name_to_id[f"type:{role_name}"]}
            for role_name in ALL_ROLES
        }
        self._extractor_tags = {
            self._tag_name_to_id[f"type:{element}_extractor"] for element in ELEMENTS
        }
        hub_tag_id = self._tag_name_to_id["type:hub"]
        self._hub_tags = {hub_tag_id}
        self._junction_tags = {self._tag_name_to_id["type:junction"]}
        self._heart_source_tags = {hub_tag_id}
        if "type:chest" in self._tag_name_to_id:
            self._heart_source_tags.add(self._tag_name_to_id["type:chest"])
        self._deposit_tags = self._junction_tags | {hub_tag_id}

    def _closest_matching_location(
        self,
        tags_by_location: dict[Coordinate, set[int]],
        origin: Coordinate,
        include_tag_ids: set[int],
        *,
        require_tag_ids: set[int] | None = None,
        exclude_tag_ids: set[int] | None = None,
        allow_origin: bool = True,
    ) -> Coordinate | None:
        # Deterministically pick the nearest matching cell so ties stay stable across runs.
        best_location: Coordinate | None = None
        best_key: tuple[int, int, int] | None = None
        for location, location_tag_ids in tags_by_location.items():
            if not allow_origin and location == origin:
                continue
            if not (location_tag_ids & include_tag_ids):
                continue
            if require_tag_ids and not (location_tag_ids & require_tag_ids):
                continue
            if exclude_tag_ids and location_tag_ids & exclude_tag_ids:
                continue

            distance_key = (
                abs(location[0] - origin[0]) + abs(location[1] - origin[1]),
                location[0],
                location[1],
            )
            if best_key is None or distance_key < best_key:
                best_location = location
                best_key = distance_key

        return best_location

    def _move(
        self, direction: str, state: StarterCogState
    ) -> tuple[Action, StarterCogState]:
        state.last_move_direction = direction
        return Action(name=self._move_action_names[direction]), state

    def _toward_directions(self, delta_row: int, delta_col: int) -> list[str]:
        # Prefer the dominant axis first so direct lines win when both row and column progress are possible.
        direction_candidates: list[str] = []
        if abs(delta_row) >= abs(delta_col):
            if delta_row != 0:
                direction_candidates.append("south" if delta_row > 0 else "north")
            if delta_col != 0:
                direction_candidates.append("east" if delta_col > 0 else "west")
        else:
            if delta_col != 0:
                direction_candidates.append("east" if delta_col > 0 else "west")
            if delta_row != 0:
                direction_candidates.append("south" if delta_row > 0 else "north")
        return direction_candidates

    def _route_to_remembered_target(
        self,
        target: Coordinate,
        tags_by_location: dict[Coordinate, set[int]],
        state: StarterCogState,
    ) -> str | None:
        """Find a path around observed obstacles instead of stepping back and forth."""
        start = state.position
        occupied = {
            (
                start[0] + location[0] - self._center[0],
                start[1] + location[1] - self._center[1],
            )
            for location in tags_by_location
            if location != self._center
        }
        blocked = state.blocked | occupied
        blocked.discard(target)
        known = (*state.seen_tags_by_position, start, target)
        row_min = min(position[0] for position in known) - 2
        row_max = max(position[0] for position in known) + 2
        col_min = min(position[1] for position in known) - 2
        col_max = max(position[1] for position in known) + 2
        frontier = [(abs(target[0] - start[0]) + abs(target[1] - start[1]), 0, start)]
        best_cost = {start: 0}
        first_direction: dict[Coordinate, str] = {}
        while frontier:
            _, cost, position = heappop(frontier)
            if cost != best_cost[position]:
                continue
            if position == target:
                return first_direction[position]
            directions = self._toward_directions(
                target[0] - position[0], target[1] - position[1]
            )
            directions.extend(
                direction
                for direction in WANDER_DIRECTIONS
                if direction not in directions
            )
            for direction in directions:
                delta = MOVE_DELTAS[direction]
                next_position = (position[0] + delta[0], position[1] + delta[1])
                next_cost = cost + 1
                if (
                    not (
                        row_min <= next_position[0] <= row_max
                        and col_min <= next_position[1] <= col_max
                    )
                    or next_position in blocked
                    or (
                        next_position in best_cost
                        and next_cost >= best_cost[next_position]
                    )
                ):
                    continue
                best_cost[next_position] = next_cost
                first_direction[next_position] = (
                    direction if position == start else first_direction[position]
                )
                heuristic = abs(target[0] - next_position[0]) + abs(
                    target[1] - next_position[1]
                )
                heappush(frontier, (next_cost + heuristic, next_cost, next_position))
        return None

    def _explore(
        self,
        tags_by_location: dict[tuple[int, int], set[int]],
        state: StarterCogState,
    ) -> tuple[Action, StarterCogState]:
        blocked_locations = set(tags_by_location)
        blocked_locations.discard(self._center)
        for prefer_visited in (False, True):
            # First keep pushing into new cells. Only fall back to revisits when the local frontier is boxed in.
            for direction_offset in range(len(WANDER_DIRECTIONS)):
                direction_index = (
                    state.explore_direction_index + direction_offset
                ) % len(WANDER_DIRECTIONS)
                direction = WANDER_DIRECTIONS[direction_index]
                move_delta = MOVE_DELTAS[direction]
                next_location = (
                    self._center[0] + move_delta[0],
                    self._center[1] + move_delta[1],
                )
                next_position = (
                    state.position[0] + move_delta[0],
                    state.position[1] + move_delta[1],
                )
                if (
                    next_location in blocked_locations
                    or next_position in state.blocked
                    or not (0 <= next_location[0] < self._policy_env_info.obs_height)
                    or not (0 <= next_location[1] < self._policy_env_info.obs_width)
                ):
                    continue
                if prefer_visited and next_position not in state.visited:
                    continue
                if not prefer_visited and next_position in state.visited:
                    continue
                state.explore_direction_index = direction_index
                return self._move(direction, state)
        return Action(name=self._noop_action_name), state

    def step_with_state(
        self, obs: AgentObservation, state: StarterCogState
    ) -> tuple[Action, StarterCogState]:
        """Compute the action for this Cog."""
        # Bucket visible tags and center inventory while reading each token once.
        tags_by_location: dict[tuple[int, int], set[int]] = {}
        items: dict[str, int] = {}
        last_action_moved = False
        for token in obs.tokens:
            feature_name = token.feature.name
            if feature_name == "last_action_move" and bool(token.value):
                last_action_moved = True
            if feature_name == "tag":
                location = token.location
                if location is not None:
                    tags_by_location.setdefault(location, set()).add(token.value)
            elif feature_name.startswith("inv:") and token.location == self._center:
                suffix = feature_name[4:]
                if not suffix or token.value <= 0:
                    continue
                item_name, sep, power_str = suffix.rpartition(":p")
                if sep and item_name and power_str.isdigit():
                    scale = max(int(token.feature.normalization), 1) ** int(power_str)
                else:
                    item_name = suffix
                    scale = 1
                items[item_name] = items.get(item_name, 0) + int(token.value) * scale

        # Fold the previous move attempt into map memory, then remember the tags on every visible cell.
        if state.last_move_direction is not None:
            move_delta = MOVE_DELTAS[state.last_move_direction]
            attempted_location = (
                self._center[0] + move_delta[0],
                self._center[1] + move_delta[1],
            )
            attempted_position = (
                state.position[0] + move_delta[0],
                state.position[1] + move_delta[1],
            )
            if last_action_moved:
                state.position = attempted_position
                state.visited.add(attempted_position)
            elif tags_by_location.get(attempted_location, set()) & self._wall_tags:
                # Only walls become permanent blockers. Another cog in the way is just traffic.
                state.blocked.add(attempted_position)
            state.last_move_direction = None

        for location, tag_ids in tags_by_location.items():
            absolute_location = (
                state.position[0] + location[0] - self._center[0],
                state.position[1] + location[1] - self._center[1],
            )
            state.seen_tags_by_position[absolute_location] = set(tag_ids)
            if location != self._center and tag_ids & self._wall_tags:
                state.blocked.add(absolute_location)

        own_team_tag_ids = (
            tags_by_location.get(self._center, set()) & self._team_tag_ids
        )
        enemy_team_tag_ids = (
            self._team_tag_ids - own_team_tag_ids
        ) or self._team_tag_ids
        has_role_gear = items.get(self._role, 0) > 0
        has_heart = items.get("heart", 0) > 0
        retreat_for_health = self._role == "aligner" and items.get("hp", 100) < 70
        cargo_amount = sum(items.get(element, 0) for element in ELEMENTS)
        role_station_tags = self._role_station_tags[self._role]
        own_anchor_positions = [
            position
            for position, tag_ids in state.seen_tags_by_position.items()
            if tag_ids & self._deposit_tags and tag_ids & own_team_tag_ids
        ]
        aligner_frontier_play = (
            self._role == "aligner"
            and has_heart
            and bool(own_anchor_positions)
            and not retreat_for_health
        )

        # Choose one target for the fixed role.
        # Miners: deposit, gear up, then mine. Aligner/scrambler: gear up, grab a heart, then go to junctions.
        target_tag_ids: set[int] | None = None
        require_tag_ids: set[int] | None = None
        exclude_tag_ids: set[int] | None = None
        if retreat_for_health:
            target_tag_ids = self._hub_tags
            require_tag_ids = own_team_tag_ids
        elif self._role == "miner":
            if cargo_amount > 0:
                target_tag_ids = self._deposit_tags
                require_tag_ids = own_team_tag_ids
            elif not has_role_gear:
                target_tag_ids = role_station_tags
                require_tag_ids = own_team_tag_ids
            else:
                target_tag_ids = self._extractor_tags
        elif not has_role_gear:
            target_tag_ids = role_station_tags
            require_tag_ids = own_team_tag_ids
        elif self._role in {"aligner", "scrambler"}:
            target_tag_ids = self._heart_source_tags
            require_tag_ids = own_team_tag_ids
            if has_heart:
                target_tag_ids = self._junction_tags
                if self._role == "aligner":
                    exclude_tag_ids = self._team_tag_ids
                else:
                    require_tag_ids = enemy_team_tag_ids

        target_location = None
        if target_tag_ids is not None:
            if aligner_frontier_play:
                # Heart carriers should spend hearts near our existing territory instead of wandering into deep neutral
                # space.
                best_target_key: tuple[int, int, int, int] | None = None
                for location, location_tag_ids in tags_by_location.items():
                    if (
                        not (location_tag_ids & target_tag_ids)
                        or location_tag_ids & self._team_tag_ids
                    ):
                        continue
                    absolute_location = (
                        state.position[0] + location[0] - self._center[0],
                        state.position[1] + location[1] - self._center[1],
                    )
                    frontier_distance = min(
                        abs(absolute_location[0] - anchor[0])
                        + abs(absolute_location[1] - anchor[1])
                        for anchor in own_anchor_positions
                    )
                    if frontier_distance > MAX_ALIGNER_JUNCTION_FRONTIER_DISTANCE:
                        continue
                    distance_to_agent = abs(location[0] - self._center[0]) + abs(
                        location[1] - self._center[1]
                    )
                    target_key = (
                        frontier_distance,
                        distance_to_agent,
                        location[0],
                        location[1],
                    )
                    if best_target_key is None or target_key < best_target_key:
                        best_target_key = target_key
                        target_location = location
            else:
                target_location = self._closest_matching_location(
                    tags_by_location,
                    self._center,
                    target_tag_ids,
                    require_tag_ids=require_tag_ids,
                    exclude_tag_ids=exclude_tag_ids,
                )

        # If nothing useful is visible, fall back to deterministic exploration.
        if target_location is None:
            if target_tag_ids is not None:
                remembered_target = None
                if aligner_frontier_play:
                    # Keep heart carriers near the friendly frontier so they turn hearts into junction captures quickly.
                    best_target_key: tuple[int, int, int, int] | None = None
                    for position, tag_ids in state.seen_tags_by_position.items():
                        if (
                            not (tag_ids & target_tag_ids)
                            or tag_ids & self._team_tag_ids
                            or position == state.position
                        ):
                            continue
                        frontier_distance = min(
                            abs(position[0] - anchor[0]) + abs(position[1] - anchor[1])
                            for anchor in own_anchor_positions
                        )
                        if frontier_distance > MAX_ALIGNER_JUNCTION_FRONTIER_DISTANCE:
                            continue
                        distance_to_agent = abs(position[0] - state.position[0]) + abs(
                            position[1] - state.position[1]
                        )
                        if distance_to_agent > MAX_REMEMBERED_JUNCTION_DISTANCE:
                            continue
                        target_key = (
                            frontier_distance,
                            distance_to_agent,
                            position[0],
                            position[1],
                        )
                        if best_target_key is None or target_key < best_target_key:
                            best_target_key = target_key
                            remembered_target = position

                    if remembered_target is None:
                        nearest_anchor = min(
                            own_anchor_positions,
                            key=lambda anchor: abs(anchor[0] - state.position[0])
                            + abs(anchor[1] - state.position[1]),
                        )
                        if (
                            abs(nearest_anchor[0] - state.position[0])
                            + abs(nearest_anchor[1] - state.position[1])
                            > MAX_ALIGNER_RETURN_TO_FRONTIER_DISTANCE
                        ):
                            remembered_target = nearest_anchor
                else:
                    # Remember stable objectives freely, but only chase nearby junction memories so mutable targets stay
                    # local.
                    remembered_target = self._closest_matching_location(
                        state.seen_tags_by_position,
                        state.position,
                        target_tag_ids,
                        require_tag_ids=require_tag_ids,
                        exclude_tag_ids=exclude_tag_ids,
                        allow_origin=False,
                    )
                if remembered_target is not None:
                    # Prefer moves that both close distance to the remembered target and keep expanding fresh cells.
                    delta_row = remembered_target[0] - state.position[0]
                    delta_col = remembered_target[1] - state.position[1]
                    current_distance = abs(delta_row) + abs(delta_col)
                    if (
                        target_tag_ids == self._junction_tags
                        and current_distance > MAX_REMEMBERED_JUNCTION_DISTANCE
                    ):
                        return self._explore(tags_by_location, state)
                    direction = self._route_to_remembered_target(
                        remembered_target, tags_by_location, state
                    )
                    if direction is not None:
                        return self._move(direction, state)
            return self._explore(tags_by_location, state)

        # Step directly onto adjacent targets, otherwise route to an open neighbor cell.
        delta_row = target_location[0] - self._center[0]
        delta_col = target_location[1] - self._center[1]
        if delta_row == 0 and delta_col == 0:
            return Action(name=self._noop_action_name), state

        if abs(delta_row) + abs(delta_col) == 1:
            return self._move(self._toward_directions(delta_row, delta_col)[0], state)

        blocked_locations = set(tags_by_location)
        blocked_locations.discard(self._center)
        if not (tags_by_location.get(target_location, set()) & self._agent_tags):
            blocked_locations.discard(target_location)
        # Route toward a free neighbor of the target cell; the target itself is often occupied or interactive.
        goal_locations = {
            (target_location[0] + move_delta[0], target_location[1] + move_delta[1])
            for move_delta in MOVE_DELTAS.values()
            if 0
            <= target_location[0] + move_delta[0]
            < self._policy_env_info.obs_height
            and 0
            <= target_location[1] + move_delta[1]
            < self._policy_env_info.obs_width
            and (target_location[0] + move_delta[0], target_location[1] + move_delta[1])
            not in blocked_locations
        }
        if not goal_locations:
            return self._explore(tags_by_location, state)

        queue = deque([self._center])
        visited = {self._center}
        first_directions: dict[tuple[int, int], str] = {}
        while queue:
            current = queue.popleft()
            delta_row = target_location[0] - current[0]
            delta_col = target_location[1] - current[1]
            # Expand BFS in target-facing order so the first route we find is usually the cleanest one.
            for direction in self._toward_directions(delta_row, delta_col):
                move_delta = MOVE_DELTAS[direction]
                next_location = (current[0] + move_delta[0], current[1] + move_delta[1])
                if (
                    next_location in visited
                    or next_location in blocked_locations
                    or not (0 <= next_location[0] < self._policy_env_info.obs_height)
                    or not (0 <= next_location[1] < self._policy_env_info.obs_width)
                ):
                    continue
                visited.add(next_location)
                first_directions[next_location] = first_directions.get(
                    current, direction
                )
                if next_location in goal_locations:
                    return self._move(first_directions[next_location], state)
                queue.append(next_location)

        return self._explore(tags_by_location, state)

    def initial_agent_state(self) -> StarterCogState:
        """Get the initial state for a new agent."""
        return StarterCogState(explore_direction_index=self._explore_direction_start)


class BaseStarterPolicy(MultiAgentPolicy):
    short_names: list[str]
    _role: str | None = None

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu"):
        super().__init__(policy_env_info, device=device)
        self._agent_policies: dict[int, StatefulAgentPolicy[StarterCogState]] = {}

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[StarterCogState]:
        if agent_id not in self._agent_policies:
            self._agent_policies[agent_id] = StatefulAgentPolicy(
                StarterCogPolicyImpl(self._policy_env_info, agent_id, role=self._role),
                self._policy_env_info,
                agent_id=agent_id,
            )
        return self._agent_policies[agent_id]


class StarterPolicy(BaseStarterPolicy):
    short_names = ["cogsguard_starter"]


class MinerRolePolicy(BaseStarterPolicy):
    short_names = ["cogsguard_miner"]
    _role = "miner"


class ScoutRolePolicy(BaseStarterPolicy):
    short_names = ["cogsguard_scout"]
    _role = "scout"


class AlignerRolePolicy(BaseStarterPolicy):
    short_names = ["cogsguard_aligner"]
    _role = "aligner"


class ScramblerRolePolicy(BaseStarterPolicy):
    short_names = ["cogsguard_scrambler"]
    _role = "scrambler"
