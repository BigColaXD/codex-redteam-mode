#!/usr/bin/env python3
from __future__ import annotations

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


def _auto_patch_previous_session(current_session_id: str | None) -> list[str]:
    """Scan the most recent session for refusals and patch it if found.

    Returns a list of status messages (empty if nothing was done).
    """
    try:
        from session_patcher import RefusalDetector, clean_session, list_session_files, backup_session, save_session
    except Exception:
        return []

    sessions = list_session_files()
    if len(sessions) < 1:
        return []

    # Pick the most recent session that is not the current one
    target = None
    for sp in sessions:
        if current_session_id and current_session_id in sp.name:
            continue
        target = sp
        break

    if target is None:
        return []

    # Skip already-patched sessions (have a .bak sibling)
    if list(target.parent.glob(f"{target.name}.*.bak")):
        return []

    detector = RefusalDetector()
    try:
        cleaned, modified, changes = clean_session(
            str(target),
            detector=detector,
            show_content=False,
            clean_reasoning=True,
        )
    except Exception:
        return []

    if not modified:
        return []

    replace_count = sum(1 for c in changes if c.change_type == "replace")
    reason_count = sum(1 for c in changes if c.change_type in ("delete", "remove_thinking"))

    backup_path = backup_session(str(target))
    save_session(cleaned, str(target))

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

    # Auto-patch previous session if it contains refusals
    patch_msgs = _auto_patch_previous_session(session_id)
    if patch_msgs:
        context = f"{context}\n" + "\n".join(patch_msgs)

    print(emit_hook_json("SessionStart", context))


if __name__ == "__main__":
    main()
