#!/usr/bin/env python3
from __future__ import annotations

import json
from fnmatch import fnmatchcase
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Mapping


DEFAULT_PROFILE_FILES = {
    "gpt-5.6*": "Jailbreak.gpt-5.6.md",
    "gpt-5.5*": "Jailbreak.gpt-5.5.md",
    "gpt-5.4*": "Jailbreak.gpt-5.4.md",
    "default": "Jailbreak.default.md",
}
SYSTEM_PROFILE_END = "<!-- codex-redteam-system-profile:end -->"
ROUTER_HEADING = "# Automatic model system profile router"


def _assignment_value(raw: str, key: str) -> str:
    name, separator, value = raw.partition("=")
    if not separator or name.strip() != key:
        return ""
    try:
        parsed = tomllib.loads(f"{key} = {value}").get(key)
    except tomllib.TOMLDecodeError:
        parsed = value.strip().strip('"\'')
    return parsed.strip() if isinstance(parsed, str) else ""


def _model_from_args(args: list[str]) -> str:
    for index, argument in enumerate(args):
        if argument in {"--model", "-m"} and index + 1 < len(args):
            return args[index + 1].strip()
        if argument.startswith("--model="):
            return argument.split("=", 1)[1].strip()
        if argument in {"-c", "--config"} and index + 1 < len(args):
            value = _assignment_value(args[index + 1], "model")
            if value:
                return value
    return ""


def _read_config(config_path: Path) -> dict:
    try:
        value = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def resolve_model(args: list[str], environ: Mapping[str, str], config_path: Path) -> str:
    argument_model = _model_from_args(args)
    if argument_model:
        return argument_model
    environment_model = environ.get("CODEX_MODEL", "").strip()
    if environment_model:
        return environment_model
    configured = _read_config(config_path).get("model")
    return configured.strip() if isinstance(configured, str) and configured.strip() else "unknown"


def profile_mapping(config_path: Path) -> dict[str, str]:
    mapping = dict(DEFAULT_PROFILE_FILES)
    redteam = _read_config(config_path).get("redteam")
    configured = redteam.get("model_prompt_profiles") if isinstance(redteam, dict) else None
    if isinstance(configured, dict):
        mapping.update(
            (str(pattern).strip(), filename.strip())
            for pattern, filename in configured.items()
            if str(pattern).strip() and isinstance(filename, str) and filename.strip()
        )
    return mapping


def select_profile(model: str, mapping: dict[str, str]) -> tuple[str, str]:
    normalized = model.casefold()
    patterns = sorted((key for key in mapping if key.casefold() != "default"), key=len, reverse=True)
    for pattern in patterns:
        lowered = pattern.casefold()
        if fnmatchcase(normalized, lowered) or (
            not any(character in lowered for character in "*?[") and normalized.startswith(lowered)
        ):
            return pattern, mapping[pattern]
    return "default", mapping.get("default", DEFAULT_PROFILE_FILES["default"])


def build_session_instructions(shared: str, profile: str, pattern: str, filename: str) -> str:
    body = shared.split(SYSTEM_PROFILE_END, 1)[1].lstrip() if SYSTEM_PROFILE_END in shared else shared
    body = body.split(f"\n{ROUTER_HEADING}", 1)[0].rstrip()
    return (
        f"{body}\n\n# Selected model system profile: {pattern}\n\n"
        f"Profile file: `{filename}`\n\n{profile.strip()}\n"
    )


def build_codex_command(args: list[str], session_path: Path, executable: str) -> list[str]:
    override = f"model_instructions_file={json.dumps(str(session_path))}"
    return [executable, *args, "-c", override]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    codex_home = Path(__file__).resolve().parents[1]
    config_path = codex_home / "config.toml"
    model = resolve_model(args, os.environ, config_path)
    mapping = profile_mapping(config_path)
    pattern, filename = select_profile(model, mapping)
    profile_path = codex_home / "prompts" / Path(filename).name
    if not profile_path.is_file():
        pattern = "default"
        filename = mapping.get("default", DEFAULT_PROFILE_FILES["default"])
        profile_path = codex_home / "prompts" / Path(filename).name
    shared_path = codex_home / "redteam-mode" / "system-instructions.md"
    if not shared_path.is_file() or not profile_path.is_file():
        print("ERROR: installed system instructions or model profile is missing", file=sys.stderr)
        return 2

    content = build_session_instructions(
        shared_path.read_text(encoding="utf-8-sig"),
        profile_path.read_text(encoding="utf-8-sig"),
        pattern,
        profile_path.name,
    )
    runtime_dir = codex_home / "redteam-mode"
    descriptor, temporary = tempfile.mkstemp(
        prefix=f"system-instructions.{profile_path.name}.",
        suffix=".SESSION.md",
        dir=runtime_dir,
        text=True,
    )
    os.close(descriptor)
    session_path = Path(temporary)
    session_path.write_text(content, encoding="utf-8")

    executable = os.environ.get("CODEX_REDTEAM_CODEX_BIN", "").strip() or shutil.which("codex")
    if not executable:
        session_path.unlink(missing_ok=True)
        print("ERROR: codex executable was not found", file=sys.stderr)
        return 127
    environment = dict(os.environ)
    environment["CODEX_MODEL"] = model
    try:
        return subprocess.run(build_codex_command(args, session_path, executable), env=environment).returncode
    finally:
        session_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
