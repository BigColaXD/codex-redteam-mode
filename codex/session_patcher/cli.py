#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session Patcher — clean refusal responses from Codex CLI session files.

Usage:
    python -m codex.session_patcher --latest             # Clean latest session
    python -m codex.session_patcher --all                # Clean all sessions
    python -m codex.session_patcher --dry-run --latest   # Preview without modifying
    python -m codex.session_patcher --list               # List all sessions

    # Or directly:
    python codex/session_patcher/cli.py --latest
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

from .detector import RefusalDetector
from .patcher import (
    backup_session,
    clean_session,
    list_session_files,
    save_session,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Session Patcher — clean refusal responses from Codex CLI sessions"
    )
    parser.add_argument(
        "--session-dir",
        default=None,
        help="Session directory (default: ~/.codex/sessions/)",
    )
    parser.add_argument("--latest", action="store_true", help="Process only the latest session")
    parser.add_argument("--all", action="store_true", help="Process all sessions")
    parser.add_argument("--list", action="store_true", help="List sessions without modifying")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not modify files")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup creation")
    parser.add_argument("--show-content", action="store_true", help="Show detailed change content")
    parser.add_argument(
        "--keep-reasoning",
        action="store_true",
        help="Keep reasoning/thinking blocks, only replace refusals",
    )
    parser.add_argument(
        "--custom-response",
        type=str,
        default=None,
        help="Custom replacement text for refusal responses",
    )

    args = parser.parse_args()

    session_dir = args.session_dir or os.path.expanduser("~/.codex/sessions/")

    print(f"Session directory: {session_dir}")
    print()

    sessions = list_session_files(session_dir)

    if not sessions:
        print("No session files found.")
        return

    if args.list:
        print(f"Found {len(sessions)} session(s):\n")
        for i, path in enumerate(sessions):
            mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            label = f"  [{i}] {path.name}  ({mtime})"
            print(label)
        return

    if args.latest:
        sessions = sessions[:1]
    elif not args.all:
        sessions = sessions[:1]

    detector = RefusalDetector()

    total_modified = 0
    for session_path in sessions:
        label = session_path.name
        print(f"Processing: {label}")

        try:
            cleaned_lines, modified, changes = clean_session(
                str(session_path),
                detector=detector,
                show_content=args.show_content,
                mock_response=args.custom_response,
                clean_reasoning=not args.keep_reasoning,
            )
        except Exception as e:
            print(f"  Error reading session: {e}")
            continue

        if not modified:
            print("  No refusal responses found.")
            continue

        # Summarize changes
        replace_count = sum(1 for c in changes if c.change_type == "replace")
        delete_count = sum(1 for c in changes if c.change_type == "delete")

        print(f"  Found {len(changes)} modification(s):")
        if replace_count:
            print(f"    - Replace refusal responses: {replace_count}")
        if delete_count:
            print(f"    - Remove reasoning blocks: {delete_count}")

        if args.show_content:
            for change in changes:
                if change.original_content:
                    print(f"    Line {change.line_num} [{change.change_type}]: "
                          f"{change.original_content[:120]}")

        if args.dry_run:
            print("  (dry-run, file not modified)")
            continue

        # Backup
        if not args.no_backup:
            backup_path = backup_session(str(session_path))
            if backup_path:
                print(f"  Backup: {backup_path}")

        # Save
        save_session(cleaned_lines, str(session_path))
        print("  Saved.")
        total_modified += 1

    print(f"\nDone: processed {len(sessions)} session(s), modified {total_modified}.")


if __name__ == "__main__":
    main()
