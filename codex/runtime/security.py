from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any


SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|cookie|session[_-]?token)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*", re.IGNORECASE),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|session[_-]?token)"
        r"(\s*[:=]\s*)[\"']?[^\s\"',;&]+"
    ),
)


def _redacted_digest(value: Any) -> str:
    if isinstance(value, str) and value.startswith("[REDACTED"):
        return value
    digest = hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"[REDACTED sha256:{digest}]"


def redact_sensitive(value: Any, key: str = "") -> Any:
    if key and SENSITIVE_KEY_RE.search(key):
        return _redacted_digest(value)
    if isinstance(value, Mapping):
        return {str(item_key): redact_sensitive(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.groups >= 2:
                redacted = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", redacted)
            else:
                redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value


def secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)


def secure_file(path: Path) -> None:
    if os.name != "nt" and path.exists():
        path.chmod(0o600)
