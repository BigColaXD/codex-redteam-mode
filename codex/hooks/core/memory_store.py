from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

try:
    from redteam_state import _safe_session_key, memory_dir
except ModuleNotFoundError:  # package import path used by tests/automation
    from hooks.redteam_state import _safe_session_key, memory_dir


DEFAULT_SESSION_MEMORY: dict[str, Any] = {
    "taskbook": {"objective": "", "todo_items": [], "acceptance_checks": []},
    "facts_confirmed": [],
    "assumptions_active": [],
    "recent_artifacts": [],
    "ruled_out_paths": [],
    "coverage_tags_seen": [],
    "coverage_tags_pending": [],
    "acceptance_checks": [],
    "reflection_log": [],
    "boundary_events": [],
    "boundary": {
        "in_scope": [],
        "out_of_scope": [],
        "allow_cross_system": False,
        "notes": "",
    },
}


def _memory_root() -> Path:
    root = memory_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_path(session_id: str) -> Path:
    return _memory_root() / f"{_safe_session_key(session_id)}.json"


def _long_memory_path(session_id: str) -> Path:
    return _memory_root() / f"{_safe_session_key(session_id)}.long.json"


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = {key: deepcopy(value) for key, value in base.items()}
        for key, value in patch.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    return deepcopy(patch)


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return deepcopy(fallback)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, type(fallback)) else deepcopy(fallback)
    except Exception:
        return deepcopy(fallback)


def load_session_memory(session_id: str) -> dict[str, Any]:
    if not session_id.strip():
        return deepcopy(DEFAULT_SESSION_MEMORY)
    return _deep_merge(DEFAULT_SESSION_MEMORY, _load_json(_session_path(session_id), {}))


def save_session_memory(session_id: str, data: dict[str, Any]) -> dict[str, Any]:
    if not session_id.strip():
        return _deep_merge(DEFAULT_SESSION_MEMORY, data)
    path = _session_path(session_id)
    current = load_session_memory(session_id)
    merged = _deep_merge(current, data)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def append_long_memory(session_id: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    if not session_id.strip():
        return [deepcopy(entry)]
    path = _long_memory_path(session_id)
    history = _load_json(path, [])
    if not isinstance(history, list):
        history = []
    history.append(deepcopy(entry))
    history = history[-24:]
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return history


def load_long_memory(session_id: str) -> list[dict[str, Any]]:
    if not session_id.strip():
        return []
    history = _load_json(_long_memory_path(session_id), [])
    return history if isinstance(history, list) else []


def latest_long_memory(session_id: str) -> Optional[dict[str, Any]]:
    history = load_long_memory(session_id)
    if history:
        return history[-1]
    return None
