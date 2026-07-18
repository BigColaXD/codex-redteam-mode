from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping
from uuid import uuid4

from .security import redact_sensitive, secure_directory, secure_file


def _safe_session_key(session_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", session_id.strip())[:120]


def _state_path(session_id: str) -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser().resolve(strict=False)
    return codex_home / "redteam-mode" / "state" / "sessions" / f"{_safe_session_key(session_id)}.json"


@contextmanager
def _state_lock(path: Path, *, timeout_seconds: float = 10.0) -> Iterator[None]:
    secure_directory(path.parent)
    lock_path = path.with_name(f"{path.name}.lock")
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > 30.0
            except FileNotFoundError:
                continue
            if stale:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"session_state_lock_timeout:{path.stem}")
            time.sleep(0.01)
            continue
        try:
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        finally:
            os.close(descriptor)
        secure_file(lock_path)
        break
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _sync_session_summary(session_id: str, summary: Mapping[str, Any]) -> None:
    if not session_id.strip():
        return
    path = _state_path(session_id)
    operations = [item for item in summary.get("operations", ()) if isinstance(item, Mapping)]
    is_batch = bool(summary.get("batch_session_id"))
    terminal = summary.get("terminal") if isinstance(summary.get("terminal"), Mapping) else {}
    if is_batch:
        run_ids = [str(item) for item in summary.get("run_ids", ()) if str(item)]
        pending_operations = [item for item in summary.get("pending_operations", ()) if isinstance(item, Mapping)]
        workflow_ids = [str(item.get("workflow_id") or "") for item in operations if item.get("workflow_id")]
        pending_action = (
            {
                "dispatch": "redteam_run",
                "batch_session_id": str(summary.get("batch_session_id") or session_id),
                "operations": pending_operations,
            }
            if not terminal.get("terminal")
            else {}
        )
        operation_run_id = ""
        workflow_id = ",".join(dict.fromkeys(workflow_ids))
        next_action_id = "batch" if pending_operations else ""
        evidence = [node for item in operations for node in item.get("evidence", ()) if isinstance(node, Mapping)]
    else:
        run_id = str(summary.get("run_id") or "")
        run_ids = [run_id] if run_id else []
        next_action_spec = summary.get("next_action_spec") if isinstance(summary.get("next_action_spec"), Mapping) else {}
        pending_action = (
            {
                "dispatch": "redteam_run",
                "run_id": run_id,
                "action_id": str(summary.get("next_action") or summary.get("current_action") or ""),
                "capabilities": list(summary.get("missing_capabilities") or ()),
                "next_action_spec": dict(next_action_spec),
            }
            if run_id and not terminal.get("terminal")
            else {}
        )
        operation_run_id = run_id
        workflow_id = str(summary.get("workflow_id") or "")
        next_action_id = str(summary.get("next_action") or "")
        evidence = [node for node in summary.get("evidence", ()) if isinstance(node, Mapping)]

    with _state_lock(path):
        try:
            current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        current.update(
            {
                "session_id": session_id,
                "pending_action": redact_sensitive(pending_action),
                "verified_artifacts": sorted(
                    {str(node.get("artifact_type") or "") for node in evidence if node.get("artifact_type")}
                ),
                "workflow_terminal": bool(terminal.get("terminal")),
                "operation_run_id": operation_run_id,
                "operation_run_ids": run_ids,
                "batch_session_id": str(summary.get("batch_session_id") or ""),
                "workflow_id": workflow_id,
                "operation_status": str(summary.get("status") or ""),
                "next_action_id": next_action_id,
                "goal_terminal": bool(terminal.get("terminal")),
                "goal_success": bool(terminal.get("success")),
            }
        )
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        secure_file(temporary)
        temporary.replace(path)
        secure_file(path)


def sync_session_summary(session_id: str, summary: Mapping[str, Any]) -> bool:
    try:
        _sync_session_summary(session_id, summary)
    except OSError:
        return False
    return True
