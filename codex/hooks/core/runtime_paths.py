from __future__ import annotations

import json
import os
from pathlib import Path


MANIFEST_NAME = "redteam-install-manifest.json"


def project_root_from_codex_dir(codex_dir: Path) -> Path:
    return codex_dir.parent


def manifest_candidates(codex_dir: Path) -> list[Path]:
    project_root = project_root_from_codex_dir(codex_dir)
    candidates = [
        codex_dir / MANIFEST_NAME,
        project_root / ".codex" / MANIFEST_NAME,
    ]
    env_codex = os.environ.get("CODEX_HOME")
    if env_codex:
        candidates.append(Path(env_codex).expanduser() / MANIFEST_NAME)
    else:
        candidates.append(Path.home() / ".codex" / MANIFEST_NAME)
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def load_runtime_manifest(codex_dir: Path) -> dict | None:
    for manifest in manifest_candidates(codex_dir):
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            return data
    return None


def default_log_root() -> Path:
    env_codex = os.environ.get("CODEX_HOME", "").strip()
    if env_codex:
        return Path(env_codex).expanduser() / "logs" / "codex-redteam"
    return Path.home() / ".codex" / "logs" / "codex-redteam"


def resolve_log_root(codex_dir: Path) -> Path:
    manifest = load_runtime_manifest(codex_dir)
    if manifest:
        raw = manifest.get("log_root")
        if isinstance(raw, str) and raw.strip():
            return Path(raw).expanduser()
    return default_log_root()
