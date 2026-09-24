"""Join one private typed-player journal to executed replay actions.

The game replay supplies the applied action at each step. Submitted actions
and model replies are only proposals until this join succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def export(
    journal_path: Path, replay_path: Path, results_path: Path, output: Path,
    episode_id: str, source_revision: str, policy_revision: str, seat: int,
) -> dict:
    if not episode_id or not policy_revision or len(source_revision) != 40 or any(
        char not in "0123456789abcdef" for char in source_revision
    ):
        raise ValueError("Episode, policy, and pinned source revision are required")
    events = [json.loads(line) for line in journal_path.read_text().splitlines()]
    replay_bytes = replay_path.read_bytes()
    replay = json.loads(replay_bytes)
    results = json.loads(results_path.read_text())
    replay_digest = hashlib.sha256(replay_bytes).hexdigest()
    if results["replay_sha256"] != replay_digest:
        raise ValueError("Results refer to another replay")
    steps = results["steps"]
    if steps < 1 or results["mission"] not in {"cogsguard", "machina_1", "four_score"}:
        raise ValueError("Results do not describe a completed Cogs vs Clips mission")
    agents = [item for item in replay["objects"] if item["type_name"] == "agent"
              and item["agent_id"] == seat]
    if len(agents) != 1 or not 0 <= seat < len(results["scores"]):
        raise ValueError("Replay or results omit the player seat")
    transitions = agents[0]["action_id"]
    if not transitions or transitions[0][0] != 0 or transitions != sorted(transitions):
        raise ValueError("Replay action timeline is incomplete or unordered")
    requests = {event["step"]: event for event in events if event["type"] == "model_request"}
    answers = {event["request_step"]: event for event in events if event["type"] == "model_answer"}
    submitted = {event["step"]: event for event in events if event["type"] == "submitted_action"}
    if len(submitted) != sum(event["type"] == "submitted_action" for event in events):
        raise ValueError("Duplicate submitted action for step")
    if set(submitted) != set(range(steps)):
        raise ValueError("Private journal does not cover every completed step")
    if len(requests) != sum(event["type"] == "model_request" for event in events):
        raise ValueError("Duplicate model request step")
    if len(answers) != sum(event["type"] == "model_answer" for event in events):
        raise ValueError("Duplicate model answer step")
    errors_by_step = {}
    pending_errors = []
    for event in events:
        if event["type"] == "model_error":
            pending_errors.append(event)
        elif event["type"] == "submitted_action" and pending_errors:
            errors_by_step[event["step"]] = pending_errors
            pending_errors = []
    if pending_errors:
        raise ValueError("Model error has no following submitted action")
    used_answers = set()
    decisions = []
    action_index = 0
    for step in range(steps):
        while action_index + 1 < len(transitions) and transitions[action_index + 1][0] <= step:
            action_index += 1
        executed_index = transitions[action_index][1]
        executed_name = replay["action_names"][executed_index]
        row = submitted[step]
        if row["observation"]["game"] != results["mission"]:
            raise ValueError(f"Step {step} differs from results mission")
        matched = row["action"] == executed_name
        request_step = row["choice_request_step"]
        new_answer = request_step is not None and request_step not in used_answers
        decision_id = f"seat:{seat}:step:{step}"
        attempt_id = f"{decision_id}:proposal"
        attempts = []
        for failure in errors_by_step.get(step, []):
            failed_request_step = failure["request_step"]
            attempts.append({
                "attempt_id": f"{decision_id}:model-failed:{failed_request_step}",
                "policy": requests[failed_request_step]["request"]["model"],
                "origin": "model", "response": None, "parsed_action": None,
                "accepted": False, "rejection_reason": failure["error"],
            })
        if new_answer:
            if request_step not in requests or request_step not in answers:
                raise ValueError("Selected model action lacks its request or answer")
            answer = answers[request_step]
            if answer["selected_action"] != row["action"]:
                raise ValueError("Model answer differs from submitted action")
            used_answers.add(request_step)
            attempts.append({
                "attempt_id": attempt_id,
                "policy": requests[request_step]["request"]["model"],
                "origin": "model",
                "response": answer["response"],
                "parsed_action": {"action_name": row["action"]},
                "accepted": matched,
                "rejection_reason": None if matched else "Simulator applied another action",
            })
        else:
            attempts.append({
                "attempt_id": attempt_id,
                "policy": policy_revision,
                "origin": "fallback",
                "response": None,
                "parsed_action": {"action_name": row["action"]},
                "accepted": matched,
                "rejection_reason": None if matched else "Simulator applied another action",
            })
        decisions.append({
            "schema_version": "1", "event_type": "decision",
            "event_id": str(uuid5(NAMESPACE_URL, episode_id + ":" + decision_id)),
            "episode_id": episode_id, "decision_id": decision_id, "decision_index": step,
            "game": "coworld-cogs-vs-clips", "game_version": results["mission"],
            "source_revision": source_revision, "seat": str(seat), "visibility": "private",
            "observation": row["observation"],
            "prompt": (requests[request_step]["request"] if new_answer else
                       requests[errors_by_step[step][0]["request_step"]]["request"]
                       if step in errors_by_step else None),
            "attempts": attempts, "selected_attempt_id": attempt_id if matched else None,
            "executed_action": {"action_name": executed_name, "action_index": executed_index,
                                "step": step},
            "action_status": "accepted" if new_answer and matched else "fallback",
            "fallback_origin": None if new_answer and matched else (
                "simulator-substituted" if not matched else
                "model-error" if step in errors_by_step else
                "model-pending" if request_step is None else "hold-last-model-choice"
            ),
            "reward": None, "terminal": step == steps - 1,
        })
    for request_step in set(requests) - set(answers) - {
        event["request_step"] for events_at_step in errors_by_step.values() for event in events_at_step
    }:
        final = decisions[-1]
        final["attempts"].append({
            "attempt_id": f"{final['decision_id']}:model-pending:{request_step}",
            "policy": requests[request_step]["request"]["model"],
            "origin": "model", "response": None, "parsed_action": None,
            "accepted": False, "rejection_reason": "Episode ended before model answer",
        })
    complete = {
        "schema_version": "1",
        "episode": {
            "schema_version": "1", "event_type": "episode",
            "event_id": str(uuid5(NAMESPACE_URL, episode_id + ":episode")),
            "episode_id": episode_id, "game": "coworld-cogs-vs-clips",
            "game_version": results["mission"], "source_revision": source_revision,
            "status": "completed",
            "outcome": {"results": results, "replay_sha256": replay_digest},
            "participant_outcomes": {"scores": results["scores"]},
        },
        "decisions": decisions,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(complete, separators=(",", ":"), ensure_ascii=False) + "\n")
    return complete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--policy-revision", required=True)
    parser.add_argument("--seat", type=int, required=True)
    args = parser.parse_args()
    episode = export(args.journal, args.replay, args.results, args.output,
                     args.episode_id, args.source_revision, args.policy_revision, args.seat)
    print(json.dumps({"decisions": len(episode["decisions"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
