from __future__ import annotations

try:
    from redteam_state import RedTeamState, load_state, reset_state, save_state
except ModuleNotFoundError:  # package import path used by tests/automation
    from hooks.redteam_state import RedTeamState, load_state, reset_state, save_state


def load_runtime_state(session_id: str | None = None) -> RedTeamState:
    return load_state(session_id)


def save_runtime_state(state: RedTeamState, session_id: str | None = None) -> None:
    save_state(state, session_id)


def reset_runtime_state(session_id: str | None = None) -> RedTeamState:
    return reset_state(session_id)
