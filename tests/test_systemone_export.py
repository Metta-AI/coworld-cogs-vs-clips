from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

EXPORT_PATH = Path(__file__).resolve().parents[1] / "tools" / "export_semantic_trajectory.py"
spec = importlib.util.spec_from_file_location("cvc_semantic_export", EXPORT_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
export = module.export


def test_replay_join_keeps_proposal_and_executed_action_separate(tmp_path: Path) -> None:
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps({
        "action_names": ["noop", "move_north"],
        "objects": [{"type_name": "agent", "agent_id": 0,
                     "action_id": [[0, 0], [1, 1]]}],
    }))
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"mission": "cogsguard", "steps": 2, "scores": [1.0],
                                   "replay_sha256": hashlib.sha256(replay.read_bytes()).hexdigest()}))
    journal = tmp_path / "journal.jsonl"
    events = [
        {"type": "model_request", "step": 0,
         "request": {"model": "jev-latest", "state": {"game": "cogsguard"},
                     "questions": {"action": {"type": "choice"}}}},
        {"type": "submitted_action", "step": 0, "action": "noop",
         "choice_request_step": None, "observation": {"game": "cogsguard"}},
        {"type": "model_answer", "request_step": 0, "selected_action": "move_north",
         "response": {"answers": {"action": {"choice": "move_north"}}}},
        {"type": "submitted_action", "step": 1, "action": "move_north",
         "choice_request_step": 0, "observation": {"game": "cogsguard"}},
    ]
    journal.write_text("".join(json.dumps(event) + "\n" for event in events))
    args = (journal, replay, results, tmp_path / "complete.jsonl", "episode-1", "a" * 40, "jev-latest", 0)
    complete = export(*args)
    assert [row["action_status"] for row in complete["decisions"]] == ["fallback", "accepted"]
    assert complete["decisions"][1]["attempts"][0]["response"] == events[2]["response"]
    assert (tmp_path / "complete.jsonl").stat().st_mode & 0o777 == 0o600

    replay.write_text(json.dumps({
        "action_names": ["noop", "move_north"],
        "objects": [{"type_name": "agent", "agent_id": 0, "action_id": [[0, 0]]}],
    }))
    with pytest.raises(ValueError, match="another replay"):
        export(journal, replay, results, tmp_path / "wrong-replay.jsonl", *args[-4:])
    results.write_text(json.dumps({"mission": "cogsguard", "steps": 2, "scores": [1.0],
                                   "replay_sha256": hashlib.sha256(replay.read_bytes()).hexdigest()}))
    blocked = export(journal, replay, results, tmp_path / "blocked.jsonl", *args[-4:])
    attempt = blocked["decisions"][1]["attempts"][0]
    assert blocked["decisions"][1]["action_status"] == "fallback"
    assert blocked["decisions"][1]["executed_action"]["action_name"] == "noop"
    assert attempt["parsed_action"]["action_name"] == "move_north"
    assert attempt["accepted"] is False

    events[2]["selected_action"] = "fly"
    journal.write_text("".join(json.dumps(event) + "\n" for event in events))
    with pytest.raises(ValueError, match="differs"):
        export(journal, replay, results, tmp_path / "invalid.jsonl", *args[-4:])
