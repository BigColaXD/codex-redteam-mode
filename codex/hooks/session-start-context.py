#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
CODEX_DIR = HOOKS_DIR.parent
for candidate in (HOOKS_DIR, CODEX_DIR):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from core import build_prompt_chain_notice, emit_hook_json, extract_session_id, extract_session_start_source, load_runtime_state, reset_runtime_state, resolve_model_prompt_profile, save_runtime_state
from core.prompt_parser import decode_stdin
from redteam_state import session_state_lock


def _process_session(payload: dict, session_id: str) -> None:
    source = extract_session_start_source(payload)

    state = load_runtime_state(session_id=session_id) if source in {"resume", "compact"} else reset_runtime_state(session_id=session_id)
    if state.mode == "normal":
        context = (
            "[mode] Default is normal. Structured red-team routing stays off until explicitly enabled. "
            "The base instruction.ctf.md security profile remains active in all modes. "
            "Use method only when it adds value. instruction.ctf.md remains highest priority."
        )
    else:
        context = (
            f"[mode] Session mode restored ({state.mode}). "
            "Resume the durable GoalContract operation and consume live MCP tools through the ToolBroker. "
            "Advance only on verified evidence and stop only when TerminalJudge proves the goal predicates."
        )
    notice = build_prompt_chain_notice(CODEX_DIR, mode=state.mode)
    if notice:
        context = f"{context}\n{notice}"

    profile = resolve_model_prompt_profile(CODEX_DIR, payload=payload)
    state.active_model = profile.model
    state.active_prompt_profile = profile.profile
    save_runtime_state(state, session_id=session_id)
    catalog = "single-profile" if os.environ.get("CODEX_REDTEAM_PROFILE_MODE", "").casefold() == "single" else "static"
    model_overlay = profile.render(scope="session-fallback", catalog=catalog)
    if model_overlay:
        context = f"{context}\n{model_overlay}"

    if state.mode in {"redteam-light", "redteam-full"}:
        if state.pending_action and not state.workflow_terminal:
            if state.pending_action.get("dispatch") in {"redteam_start", "redteam_run"}:
                if state.pending_action.get("batch_session_id"):
                    context = (
                        f"{context}\n[operation-dispatch-resume] Call redteam_run with "
                        f"batch_session_id={state.pending_action.get('batch_session_id')!r}. Follow every pending operation's "
                        "next_action_spec and return observations as one batch without user relay."
                    )
                elif state.pending_action.get("run_id"):
                    context = (
                        f"{context}\n[operation-dispatch-resume] Call redteam_run with "
                        f"run_id={state.pending_action.get('run_id')!r}. Continue without user relay."
                    )
                else:
                    context = (
                        f"{context}\n[operation-dispatch-resume] Call redteam_run idempotently with "
                        f"session_id={state.pending_action.get('session_id')}, objective={state.pending_action.get('objective')!r}, "
                        f"targets={state.pending_action.get('targets')}, workflow_hint={state.pending_action.get('workflow_hint')}. "
                        "Continue without user relay."
                    )
            else:
                capabilities = state.pending_action.get("capabilities") or []
                action_id = str(state.pending_action.get("action_id") or "unknown")
                run_id = str(state.pending_action.get("run_id") or "unknown")
                context = (
                    f"{context}\n[operation-resume:{run_id}:{action_id}] pending capabilities={capabilities}; "
                    "resume through redteam_run, follow its next_action_spec/output_contract, and return host-agent "
                    "evidence through redteam_run.observation. "
                    "Do not ask the user to relay tool output."
                )
    print(emit_hook_json("SessionStart", context))


def main() -> None:
    raw = decode_stdin(sys.stdin.buffer.read())
    if not raw.strip():
        return
    try:
        payload = json.loads(raw)
    except Exception:
        return
    if not isinstance(payload, dict):
        return

    session_id = extract_session_id(payload)
    if not session_id:
        return
    with session_state_lock(session_id):
        _process_session(payload, session_id)


if __name__ == "__main__":
    main()
