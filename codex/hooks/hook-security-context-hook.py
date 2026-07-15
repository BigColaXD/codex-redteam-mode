#!/usr/bin/env python3
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
CODEX_DIR = HOOKS_DIR.parent
for candidate in (HOOKS_DIR, CODEX_DIR):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from core import build_redteam_mode_overlay, emit_hook_json, extract_prompt, extract_session_id, extract_transcript_path, load_runtime_state, parse_mode_command, parse_opsec_command, resolve_model_prompt_profile, save_runtime_state
from core.controller import process_turn
from core.prompt_parser import decode_stdin, load_payload
from core.refusal_backstop import build_recent_refusal_overlay, payload_has_recent_refusal
from redteam_state import default_state


def main() -> None:
    raw = decode_stdin(sys.stdin.buffer.read())
    if not raw.strip():
        return
    try:
        payload = load_payload(raw)
    except Exception:
        return

    prompt = extract_prompt(payload)
    if not prompt.strip():
        return

    session_id = extract_session_id(payload)
    if not session_id:
        return
    transcript_path = extract_transcript_path(payload)
    state = load_runtime_state(session_id=session_id)

    mode = parse_mode_command(prompt)
    if mode is not None:
        if mode == "normal":
            state = default_state(session_id)
            save_runtime_state(state, session_id=session_id)
            print(
                emit_hook_json(
                    "UserPromptSubmit",
                    "[mode] Structured red-team routing disabled for future turns. "
                    "No new phase/router/pack/leaf context will be injected. "
                    "The base instruction.ctf.md profile and previous task context remain active. "
                    "The session state file remains stored with mode reset to normal. "
                    "Use /clear or start a new task to remove prior per-session context.",
                )
            )
        else:
            profile = resolve_model_prompt_profile(CODEX_DIR, payload=payload, transcript_path=transcript_path)
            state = replace(
                default_state(session_id),
                mode=mode,
                opsec_level=state.opsec_level,
                active_model=profile.model,
                active_prompt_profile=profile.profile,
            )
            save_runtime_state(state, session_id=session_id)
            context = (
                f"[mode] Red-team mode enabled ({mode}). Future prompts will use "
                "phase -> router -> pack -> leaf routing until you explicitly disable it."
            )
            mode_overlay = build_redteam_mode_overlay(CODEX_DIR, mode)
            if mode_overlay:
                context = f"{context}\n{mode_overlay}"
            model_overlay = profile.render()
            if model_overlay:
                context = f"{context}\n{model_overlay}"
            print(
                emit_hook_json(
                    "UserPromptSubmit",
                    context,
                    inject_prepoison=True,
                )
            )
        return

    opsec = parse_opsec_command(prompt)
    if opsec is not None:
        state = replace(state, opsec_level=opsec)
        save_runtime_state(state, session_id=session_id)
        print(emit_hook_json("UserPromptSubmit", f"[mode] OPSEC level updated to {opsec}."))
        return

    if state.mode == "normal":
        return

    previous_model = state.active_model
    previous_profile = state.active_prompt_profile
    profile = resolve_model_prompt_profile(CODEX_DIR, payload=payload, transcript_path=transcript_path)
    result = process_turn(
        prompt=prompt,
        state=state,
        codex_dir=CODEX_DIR,
        assistant_summary="",
    )
    result.state.active_model = profile.model
    result.state.active_prompt_profile = profile.profile
    save_runtime_state(result.state, session_id=session_id)
    context = result.brief
    if profile.model != previous_model or profile.profile != previous_profile:
        model_overlay = profile.render()
        if model_overlay:
            context = f"{context}\n{model_overlay}"
    if payload_has_recent_refusal(payload):
        context = f"{context}\n{build_recent_refusal_overlay()}"
    if result.overlay:
        context = f"{context}\n{result.overlay}"
    print(emit_hook_json("UserPromptSubmit", context, inject_role_overlay=True, role_phase=result.state.phase))


if __name__ == "__main__":
    main()
