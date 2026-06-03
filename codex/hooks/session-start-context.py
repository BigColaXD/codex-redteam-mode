#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
CODEX_DIR = HOOKS_DIR.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))
if str(CODEX_DIR) not in sys.path:
    sys.path.insert(0, str(CODEX_DIR))

from core import build_prompt_chain_notice, emit_hook_json, extract_session_id, reset_runtime_state
from core.prompt_parser import decode_stdin, load_payload


def _is_auto_patch_enabled() -> bool:
    return os.environ.get("CODEX_REDTEAM_AUTO_PATCH", "").strip() == "1"


def _detect_refusals_in_previous_session(current_session_id: str | None, sessions_dir: Path) -> list[str]:
    """Scan the most recent session for refusals and report them.

    Does NOT modify files. Only reports what would be patchable.
    Returns a list of informational messages (empty if nothing detected).
    """
    try:
        from session_patcher import RefusalDetector, list_session_files
    except Exception:
        return []

    sessions = list_session_files(str(sessions_dir))
    if not sessions:
        return []

    target = None
    for sp in sessions:
        if current_session_id and current_session_id in sp.name:
            continue
        target = sp
        break

    if target is None:
        return []

    if list(target.parent.glob(f"{target.name}.*.bak")):
        return []

    detector = RefusalDetector()
    try:
        with open(str(target), "r", encoding="utf-8") as f:
            lines = [__import__("json").loads(line) for line in f if line.strip()]
    except Exception:
        return []

    refusal_count = 0
    for line in lines:
        line_type = line.get("type", "")
        payload = line.get("payload", {})
        content = ""
        if line_type == "response_item":
            if payload.get("type") == "message" and payload.get("role") == "assistant":
                c = payload.get("content", [])
                if isinstance(c, list):
                    content = "".join(b.get("text", "") for b in c if isinstance(b, dict))
                elif isinstance(c, str):
                    content = c
        elif line_type == "event_msg":
            pt = payload.get("type", "")
            if pt == "agent_message":
                content = payload.get("message", "")
            elif pt == "task_complete":
                content = payload.get("last_agent_message", "")

        if content and detector.detect(content):
            refusal_count += 1

    if refusal_count:
        return [f"[detect] {target.name}: {refusal_count} refusal(s) detected. Set CODEX_REDTEAM_AUTO_PATCH=1 to auto-patch."]
    return []


def _auto_patch_previous_session(current_session_id: str | None, sessions_dir: Path) -> list[str]:
    """Scan and patch the most recent session for refusals.

    Only called when CODEX_REDTEAM_AUTO_PATCH=1.
    All file operations are wrapped — a failure here must not affect Codex startup.
    """
    try:
        from session_patcher import RefusalDetector, clean_session, list_session_files
    except Exception:
        return []

    try:
        sessions = list_session_files(str(sessions_dir))
    except Exception:
        return []

    if not sessions:
        return []

    target = None
    for sp in sessions:
        if current_session_id and current_session_id in sp.name:
            continue
        target = sp
        break

    if target is None:
        return []

    if list(target.parent.glob(f"{target.name}.*.bak")):
        return []

    detector = RefusalDetector()
    try:
        cleaned, modified, changes = clean_session(
            str(target),
            detector=detector,
            show_content=False,
            clean_reasoning=True,
            use_ai=False,
        )
    except Exception:
        return []

    if not modified:
        return []

    replace_count = sum(1 for c in changes if c.change_type == "replace")
    reason_count = sum(1 for c in changes if c.change_type in ("delete", "remove_thinking"))

    backup_path = None
    try:
        from session_patcher import backup_session
        backup_path = backup_session(str(target))
    except Exception:
        pass

    try:
        from session_patcher import save_session
        save_session(cleaned, str(target))
    except Exception:
        return [f"[auto-patch] {target.name}: save failed (backup at {backup_path})"]

    parts = []
    if replace_count:
        parts.append(f"{replace_count} refusal(s) replaced")
    if reason_count:
        parts.append(f"{reason_count} reasoning block(s) removed")

    return [f"[auto-patch] {target.name}: {', '.join(parts)}. Backup: {backup_path}"]


def main() -> None:
    raw = decode_stdin(sys.stdin.buffer.read())
    session_id = None
    if raw.strip():
        try:
            session_id = extract_session_id(load_payload(raw))
        except Exception:
            session_id = None

    reset_runtime_state(session_id=session_id)

    context = (
        "[mode] Default is normal. Red-team mode stays off until explicitly enabled. "
        "When enabled, guidance stays lightweight and routes by phase -> router -> pack -> leaf. "
        "Use method only when it adds value."
    )

    notice = build_prompt_chain_notice(CODEX_DIR)
    if notice:
        context = f"{context}\n{notice}"

    sessions_dir = CODEX_DIR / "sessions"

    if _is_auto_patch_enabled():
        patch_msgs = _auto_patch_previous_session(session_id, sessions_dir)
    else:
        patch_msgs = _detect_refusals_in_previous_session(session_id, sessions_dir)

    if patch_msgs:
        context = f"{context}\n" + "\n".join(patch_msgs)

    print(emit_hook_json("SessionStart", context))


if __name__ == "__main__":
    main()
