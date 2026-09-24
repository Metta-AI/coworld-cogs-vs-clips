"""Game-owned typed action question over one seat-visible semantic state."""

from __future__ import annotations

from mettagrid.sdk.agent import MettagridState
from pydantic import BaseModel, Field


class ActionChoice(BaseModel):
    choice: str
    probabilities: dict[str, float] = Field(default_factory=dict)


class SystemOneActionResponse(BaseModel):
    answers: dict[str, ActionChoice]


def action_request(
    state: MettagridState, action_names: list[str], model: str
) -> dict:
    if not action_names or len(set(action_names)) != len(action_names):
        raise ValueError("Action candidates must be nonempty and unique")
    return {
        "model": model,
        "state": state.model_dump(mode="json"),
        "questions": {
            "action": {
                "type": "choice",
                "instructions": "Choose one action for this agent's next step from its visible state.",
                "criteria": {name: f"Execute {name}" for name in action_names},
            }
        },
    }


def selected_action(response: dict, action_names: list[str]) -> ActionChoice:
    answer = SystemOneActionResponse.model_validate(response).answers["action"]
    if answer.choice not in action_names or any(
        name not in action_names for name in answer.probabilities
    ):
        raise ValueError("SystemOne chose an action outside the configured candidates")
    return answer
