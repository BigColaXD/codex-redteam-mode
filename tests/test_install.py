from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from tomlkit.exceptions import ParseError as TomlParseError


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_PATH = REPO_ROOT / "scripts" / "install.py"
VALIDATE_PATH = REPO_ROOT / "scripts" / "validate.py"
CODEX_PATH = REPO_ROOT / "codex"
HOOKS_PATH = REPO_ROOT / "codex" / "hooks"

spec = importlib.util.spec_from_file_location("install_script", INSTALL_PATH)
install = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = install
assert spec.loader is not None
spec.loader.exec_module(install)

validate_spec = importlib.util.spec_from_file_location("validate_script", VALIDATE_PATH)
validate = importlib.util.module_from_spec(validate_spec)
sys.modules[validate_spec.name] = validate
assert validate_spec.loader is not None
validate_spec.loader.exec_module(validate)

if str(HOOKS_PATH) not in sys.path:
    sys.path.insert(0, str(HOOKS_PATH))
if str(CODEX_PATH) not in sys.path:
    sys.path.insert(0, str(CODEX_PATH))
from core import controller, prompt_parser, refusal_backstop, runtime_paths, skill_card
from session_patcher import patcher


def _write_skill(skills_root: Path, name: str = "redteam-demo") -> Path:
    skill_dir = skills_root / name
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: demo\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    return skill_dir


def _write_session(path: Path, mtime: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"type":"event_msg","payload":{}}\n', encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_merge_config_preserves_user_sections(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text(
        """
# user-owned config
model = "gpt-5"

[automation]
mode = "active"

[mcp_servers.ida-pro-mcp]
command = "ida-mcp"

[projects."/work/demo"]
trust_level = "trusted"
""".lstrip(),
        encoding="utf-8",
    )

    install.merge_config_file(REPO_ROOT / "config.toml", target, dry_run=False)

    merged = tomllib.loads(target.read_text(encoding="utf-8"))
    assert merged["model"] == "gpt-5"
    assert merged["model_instructions_file"] == "./instruction.ctf.md"
    assert merged["features"]["hooks"] is True
    assert merged["features"]["automation"] is True
    assert merged["automation"]["mode"] == "active"
    assert merged["automation"]["allow_restricted_actions"] is False
    assert merged["mcp_servers"]["ida-pro-mcp"]["command"] == "ida-mcp"
    assert merged["projects"]["/work/demo"]["trust_level"] == "trusted"
    assert "# user-owned config" in target.read_text(encoding="utf-8")


def test_merge_config_does_not_put_automation_keys_in_skills_array(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text(
        """
[automation]
mode = "active"

[[skills.config]]
path = "/tmp/demo/SKILL.md"
enabled = false
""".lstrip(),
        encoding="utf-8",
    )

    install.merge_config_file(REPO_ROOT / "config.toml", target, dry_run=False)

    merged = tomllib.loads(target.read_text(encoding="utf-8"))
    assert merged["automation"]["allow_restricted_actions"] is False
    assert merged["automation"]["require_scope_for_network"] is True
    assert "allow_restricted_actions" not in merged["skills"]["config"][0]
    assert "require_scope_for_network" not in merged["skills"]["config"][0]


def test_merge_config_supports_quoted_automation_table(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text(
        """
["automation"]
mode = "active"
""".lstrip(),
        encoding="utf-8",
    )

    install.merge_config_file(REPO_ROOT / "config.toml", target, dry_run=False)

    merged = tomllib.loads(target.read_text(encoding="utf-8"))
    assert merged["automation"]["mode"] == "active"
    assert merged["automation"]["allow_restricted_actions"] is False


def test_merge_config_accepts_utf8_bom(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_bytes(b"\xef\xbb\xbf[automation]\nmode = \"active\"\n")

    install.merge_config_file(REPO_ROOT / "config.toml", target, dry_run=False)

    merged = tomllib.loads(target.read_text(encoding="utf-8"))
    assert merged["automation"]["mode"] == "active"
    assert merged["model_instructions_file"] == "./instruction.ctf.md"


def test_runtime_accepts_unchanged_utf8_bom_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / ".codex"
    target = codex_home / "config.toml"
    target.parent.mkdir(parents=True)
    original = b"\xef\xbb\xbf" + (REPO_ROOT / "config.toml").read_bytes()
    target.write_bytes(original)

    install.merge_config_file(REPO_ROOT / "config.toml", target, dry_run=False)

    assert target.read_bytes() == original
    monkeypatch.setattr(controller.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.delenv("CODEX_REDTEAM_AUTOMATION_MODE", raising=False)
    monkeypatch.delenv("CODEX_REDTEAM_CONFIG", raising=False)
    assert controller._automation_mode_from_config(codex_home, "redteam-light") == "active"


def test_validate_config_accepts_utf8_bom(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_bytes(b"\xef\xbb\xbf" + (REPO_ROOT / "config.toml").read_bytes())

    _, messages = validate.validate_install(tmp_path)

    assert "config.toml: valid" in messages


def test_validate_config_rejects_invalid_toml(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("[automation\n", encoding="utf-8")

    all_ok, messages = validate.validate_install(tmp_path)

    assert all_ok is False
    assert any(message.startswith("config.toml: INVALID TOML") for message in messages)


def test_merge_config_backs_up_existing_file_before_change(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    original = '[automation]\nmode = "active"\n'
    target.write_text(original, encoding="utf-8")

    install.merge_config_file(REPO_ROOT / "config.toml", target, dry_run=False)

    backups = list(tmp_path.glob("config.toml.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    assert tomllib.loads(target.read_text(encoding="utf-8"))["features"]["hooks"] is True


def test_merge_config_dry_run_does_not_write_or_backup(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    original = '[automation]\nmode = "active"\n'
    target.write_text(original, encoding="utf-8")

    install.merge_config_file(REPO_ROOT / "config.toml", target, dry_run=True)

    assert target.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("config.toml.*.bak")) == []


def test_merge_config_does_not_backup_when_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text((REPO_ROOT / "config.toml").read_text(encoding="utf-8"), encoding="utf-8")

    install.merge_config_file(REPO_ROOT / "config.toml", target, dry_run=False)

    assert list(tmp_path.glob("config.toml.*.bak")) == []


def test_merge_config_invalid_existing_toml_does_not_backup_or_write(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    original = "[automation\nmode = \"active\"\n"
    target.write_text(original, encoding="utf-8")

    with pytest.raises(TomlParseError):
        install.merge_config_file(REPO_ROOT / "config.toml", target, dry_run=False)

    assert target.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("config.toml.*.bak")) == []


def test_install_invalid_existing_toml_fails_before_writes_or_cleanup(tmp_path: Path) -> None:
    codex_home = tmp_path / "custom-codex"
    agents_home = tmp_path / "custom-agents"
    codex_home.mkdir()
    original = "[automation\nmode = \"active\"\n"
    (codex_home / "config.toml").write_text(original, encoding="utf-8")
    stale = codex_home / "stale-managed.txt"
    stale.write_text("old managed file\n", encoding="utf-8")
    manifest = codex_home / "redteam-install-manifest.json"
    manifest.write_text(json.dumps({"managed_paths": [str(stale)]}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--codex-home",
            str(codex_home),
            "--agents-home",
            str(agents_home),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    assert result.returncode != 0
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == original
    assert list(codex_home.glob("config.toml.*.bak")) == []
    assert not (codex_home / "instruction.ctf.md").exists()
    assert not (codex_home / "hooks").exists()
    assert not (codex_home / "AGENTS.md").exists()
    assert not agents_home.exists()
    assert stale.exists()
    assert manifest.exists()


def test_merge_hooks_json_accepts_utf8_bom_and_preserves_user_hooks(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    hooks_path = codex_home / "hooks.json"
    user_payload = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "user-command",
                            "statusMessage": "User hook",
                        }
                    ],
                }
            ]
        }
    }
    hooks_path.write_bytes(b"\xef\xbb\xbf" + json.dumps(user_payload).encode("utf-8"))

    install.merge_hooks_json(REPO_ROOT, codex_home, dry_run=False)

    merged = json.loads(hooks_path.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entries in merged["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
    ]
    assert "user-command" in commands
    assert any("session-start-context.py" in command for command in commands)


@pytest.mark.parametrize(
    "hooks_bytes",
    [
        b"{invalid json",
        json.dumps({"hooks": []}).encode("utf-8"),
    ],
)
@pytest.mark.parametrize("extra_args", [(), ("--dry-run",)])
def test_install_invalid_hooks_fails_before_writes_or_cleanup(
    tmp_path: Path,
    hooks_bytes: bytes,
    extra_args: tuple[str, ...],
) -> None:
    codex_home = tmp_path / "custom-codex"
    agents_home = tmp_path / "custom-agents"
    codex_home.mkdir()
    hooks_path = codex_home / "hooks.json"
    hooks_path.write_bytes(hooks_bytes)
    stale = codex_home / "stale-managed.txt"
    stale.write_text("old managed file\n", encoding="utf-8")
    manifest = codex_home / "redteam-install-manifest.json"
    manifest.write_text(json.dumps({"managed_paths": [str(stale)]}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--codex-home",
            str(codex_home),
            "--agents-home",
            str(agents_home),
            *extra_args,
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    assert result.returncode != 0
    assert hooks_path.read_bytes() == hooks_bytes
    assert stale.exists()
    assert manifest.exists()
    assert not (codex_home / "config.toml").exists()
    assert not (codex_home / "instruction.ctf.md").exists()
    assert not (codex_home / "AGENTS.md").exists()
    assert not (codex_home / "hooks").exists()
    assert not agents_home.exists()


def test_uninstall_invalid_hooks_fails_before_deleting_managed_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    codex_home = project / ".codex"
    codex_home.mkdir(parents=True)
    hooks_path = codex_home / "hooks.json"
    hooks_path.write_text("{invalid json", encoding="utf-8")
    managed = codex_home / "instruction.ctf.md"
    managed.write_text("managed\n", encoding="utf-8")
    manifest = codex_home / "redteam-install-manifest.json"
    manifest.write_text(json.dumps({"managed_paths": [str(managed)]}), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(INSTALL_PATH), "--project-home", str(project), "--uninstall"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    assert result.returncode != 0
    assert hooks_path.exists()
    assert managed.exists()
    assert manifest.exists()


def test_upgrade_cleanup_preserves_config_from_previous_manifest(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    agents_home = tmp_path / ".agents"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    instruction = codex_home / "instruction.ctf.md"
    config.write_text("[automation]\nmode = \"active\"\n", encoding="utf-8")
    instruction.write_text("managed instruction\n", encoding="utf-8")
    install.manifest_path(codex_home).write_text(
        json.dumps(
            {
                "managed_paths": [
                    str(config),
                    str(instruction),
                ]
            }
        ),
        encoding="utf-8",
    )

    install._SAFE_ROOTS.clear()
    install._SAFE_ROOTS.extend([codex_home, agents_home, REPO_ROOT])

    install.upgrade_cleanup(codex_home, agents_home, codex_home / "AGENTS.md", [], dry_run=False)

    assert config.exists()
    assert not instruction.exists()
    assert not install.manifest_path(codex_home).exists()


def test_manifest_tracks_config_as_merged_file(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    managed = [codex_home / "instruction.ctf.md"]
    agents_file = tmp_path / "AGENTS.md"

    agents_home = tmp_path / ".agents"
    install.write_manifest(
        codex_home,
        agents_file,
        agents_home,
        managed,
        codex_home / "logs" / "codex-redteam",
        False,
        dry_run=False,
    )

    payload = json.loads(install.manifest_path(codex_home).read_text(encoding="utf-8"))
    assert str(codex_home / "config.toml") not in payload["managed_paths"]
    assert str(codex_home / "config.toml") in payload["merged_files"]
    assert str(agents_file) in payload["merged_files"]
    assert payload["skills_paths"]["skills_root"] == str(agents_home / "skills")
    assert payload["custom_skill_dirs_enabled"] is False
    assert payload["log_root"] == str(codex_home / "logs" / "codex-redteam")


def test_project_home_resolves_dot_codex_and_dot_agents(tmp_path: Path) -> None:
    project = tmp_path / "project"

    codex_home, agents_home, agents_file = install.resolve_install_paths(str(project), None, None)

    assert codex_home == project / ".codex"
    assert agents_home == project / ".agents"
    assert agents_file == project / "AGENTS.md"


def test_project_home_allows_custom_agents_home(tmp_path: Path) -> None:
    project = tmp_path / "project"
    custom_agents = tmp_path / "custom-agents"

    codex_home, agents_home, agents_file = install.resolve_install_paths(
        str(project),
        None,
        str(custom_agents),
    )

    assert codex_home == project / ".codex"
    assert agents_home == custom_agents
    assert agents_file == project / "AGENTS.md"


def test_relative_install_paths_are_resolved_before_manifest_and_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    agents_home = tmp_path / "shared-agents"
    log_root = tmp_path / "logs"

    subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            "project",
            "--agents-home",
            "shared-agents",
            "--log-root",
            "logs",
            "--enable-custom-skill-dirs",
        ],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    codex_home = project / ".codex"
    payload = json.loads((codex_home / "redteam-install-manifest.json").read_text(encoding="utf-8"))
    recorded_paths = [
        *payload["managed_paths"],
        *payload["merged_files"],
        payload["skills_paths"]["skills_root"],
        *payload["skills_paths"]["skill_dirs"],
        payload["log_root"],
    ]
    assert all(Path(path).is_absolute() for path in recorded_paths)
    assert payload["skills_paths"]["skills_root"] == str(agents_home / "skills")
    assert payload["log_root"] == str(log_root)

    hooks_payload = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entries in hooks_payload["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
    ]
    assert all(str(codex_home / "hooks") in command for command in commands)

    monkeypatch.chdir(project)
    assert runtime_paths.resolve_log_root(codex_home) == log_root
    assert skill_card.resolve_skills_dir(codex_home) == agents_home / "skills"


def test_relative_codex_home_environment_is_resolved_for_install(tmp_path: Path) -> None:
    env = {**os.environ, "CODEX_HOME": "profile"}

    subprocess.run(
        [sys.executable, str(INSTALL_PATH), "--agents-home", "agents"],
        cwd=tmp_path,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    codex_home = tmp_path / "profile"
    payload = json.loads((codex_home / "redteam-install-manifest.json").read_text(encoding="utf-8"))
    assert payload["log_root"] == str(codex_home / "logs" / "codex-redteam")
    assert payload["skills_paths"]["skills_root"] == str(tmp_path / "agents" / "skills")
    assert all(Path(path).is_absolute() for path in payload["managed_paths"])


def test_relative_manifest_targets_are_rejected_as_a_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / ".codex"
    agents_home = tmp_path / ".agents"
    codex_home.mkdir()
    relative_user_file = tmp_path / "user-owned.txt"
    relative_user_file.write_text("user data\n", encoding="utf-8")
    current_target = codex_home / "instruction.ctf.md"
    current_target.write_text("managed\n", encoding="utf-8")
    install.manifest_path(codex_home).write_text(
        json.dumps({"managed_paths": ["user-owned.txt", str(current_target)]}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(install, "_SAFE_ROOTS", [codex_home, agents_home, tmp_path])

    install.upgrade_cleanup(
        codex_home,
        agents_home,
        codex_home / "AGENTS.md",
        [current_target],
        dry_run=False,
    )

    assert relative_user_file.exists()
    assert not current_target.exists()
    assert not install.manifest_path(codex_home).exists()


def test_project_home_install_writes_under_dot_dirs(tmp_path: Path) -> None:
    project = tmp_path / "project"

    subprocess.run(
        [sys.executable, str(INSTALL_PATH), "--project-home", str(project)],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    assert (project / ".codex" / "config.toml").exists()
    assert (project / ".codex" / "instruction.ctf.md").exists()
    assert (project / "AGENTS.md").exists()
    assert not (project / ".codex" / "AGENTS.md").exists()
    assert (project / ".agents" / "skills" / "redteam-cve-validation" / "SKILL.md").exists()
    assert not (project / "config.toml").exists()
    payload = json.loads((project / ".codex" / "redteam-install-manifest.json").read_text(encoding="utf-8"))
    assert payload["skills_paths"]["skills_root"] == str(project / ".agents" / "skills")
    assert str(project / ".agents" / "skills" / "redteam-cve-validation") in payload["skills_paths"]["skill_dirs"]
    assert payload["custom_skill_dirs_enabled"] is False
    assert payload["log_root"] == str(project / ".codex" / "logs" / "codex-redteam")


def test_project_home_migrates_old_dot_codex_agents_block(tmp_path: Path) -> None:
    project = tmp_path / "project"
    old_agents = project / ".codex" / "AGENTS.md"
    old_agents.parent.mkdir(parents=True)
    old_agents.write_text(install.managed_agents_block(REPO_ROOT), encoding="utf-8")

    subprocess.run(
        [sys.executable, str(INSTALL_PATH), "--project-home", str(project)],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    assert (project / "AGENTS.md").exists()
    assert not old_agents.exists()


def test_project_home_uninstall_preserves_user_agents_content(tmp_path: Path) -> None:
    project = tmp_path / "project"
    agents_file = project / "AGENTS.md"

    subprocess.run(
        [sys.executable, str(INSTALL_PATH), "--project-home", str(project)],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    agents_file.write_text(
        "user guidance\n\n" + agents_file.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, str(INSTALL_PATH), "--project-home", str(project), "--uninstall"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    assert agents_file.read_text(encoding="utf-8") == "user guidance\n"


def test_project_home_install_accepts_custom_agents_home(tmp_path: Path) -> None:
    project = tmp_path / "project"
    custom_agents = tmp_path / "custom-agents"

    subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--agents-home",
            str(custom_agents),
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    assert (project / ".codex" / "config.toml").exists()
    assert (custom_agents / "skills" / "redteam-cve-validation" / "SKILL.md").exists()
    assert not (project / ".agents").exists()
    payload = json.loads((project / ".codex" / "redteam-install-manifest.json").read_text(encoding="utf-8"))
    assert payload["skills_paths"]["skills_root"] == str(custom_agents / "skills")
    assert str(custom_agents / "skills" / "redteam-cve-validation") in payload["skills_paths"]["skill_dirs"]


def test_custom_agents_home_without_runtime_opt_in_warns(tmp_path: Path) -> None:
    project = tmp_path / "project"
    custom_agents = tmp_path / "custom-agents"

    result = subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--agents-home",
            str(custom_agents),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "[WARN] custom --agents-home" in result.stdout
    assert "--enable-custom-skill-dirs" in result.stdout


def test_custom_agents_home_with_runtime_opt_in_does_not_warn(tmp_path: Path) -> None:
    project = tmp_path / "project"
    custom_agents = tmp_path / "custom-agents"

    result = subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--agents-home",
            str(custom_agents),
            "--enable-custom-skill-dirs",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "[WARN] custom --agents-home" not in result.stdout


def test_validate_reports_custom_skill_runtime_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    custom_agents = tmp_path / "custom-agents"
    fake_home = tmp_path / "home"
    runtime_skills = fake_home / ".agents" / "skills"
    _write_skill(runtime_skills)

    subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--agents-home",
            str(custom_agents),
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    monkeypatch.setattr(skill_card.Path, "home", classmethod(lambda cls: fake_home))

    all_ok, messages = validate.validate_install(project / ".codex")

    assert all_ok is True
    assert f"Installed skill cards: {custom_agents / 'skills'}" in messages
    assert f"Runtime skill cards: {runtime_skills}" in messages
    assert any("runtime is not using the installed skill root" in message for message in messages)


def test_uninstall_external_agents_home_requires_original_scope(tmp_path: Path) -> None:
    project = tmp_path / "project"
    custom_agents = tmp_path / "custom-agents"
    codex_home = project / ".codex"

    subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--agents-home",
            str(custom_agents),
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    manifest = codex_home / "redteam-install-manifest.json"
    manifest_before = manifest.read_bytes()
    managed = codex_home / "instruction.ctf.md"
    skill = custom_agents / "skills" / "redteam-cve-validation" / "SKILL.md"

    result = subprocess.run(
        [sys.executable, str(INSTALL_PATH), "--project-home", str(project), "--uninstall"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "outside the current cleanup scope" in result.stderr
    assert "--agents-home" in result.stderr
    assert manifest.read_bytes() == manifest_before
    assert managed.exists()
    assert skill.exists()

    subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--agents-home",
            str(custom_agents),
            "--uninstall",
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    assert not manifest.exists()
    assert not managed.exists()
    assert not skill.exists()


def test_upgrade_external_agents_home_requires_original_scope(tmp_path: Path) -> None:
    project = tmp_path / "project"
    original_agents = tmp_path / "original-agents"
    replacement_agents = tmp_path / "replacement-agents"
    codex_home = project / ".codex"

    subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--agents-home",
            str(original_agents),
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    manifest = codex_home / "redteam-install-manifest.json"
    manifest_before = manifest.read_bytes()
    managed = codex_home / "instruction.ctf.md"
    old_skill = original_agents / "skills" / "redteam-cve-validation" / "SKILL.md"

    result = subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--agents-home",
            str(replacement_agents),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "upgrade cleanup blocked" in result.stderr
    assert manifest.read_bytes() == manifest_before
    assert managed.exists()
    assert old_skill.exists()
    assert not replacement_agents.exists()


def test_install_manifest_records_custom_skill_dirs_and_log_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    custom_log = tmp_path / "custom-logs"

    subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--enable-custom-skill-dirs",
            "--log-root",
            str(custom_log),
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    payload = json.loads((project / ".codex" / "redteam-install-manifest.json").read_text(encoding="utf-8"))
    assert payload["custom_skill_dirs_enabled"] is True
    assert payload["log_root"] == str(custom_log)


def test_codex_home_install_manifest_log_root_follows_codex_home(tmp_path: Path) -> None:
    codex_home = tmp_path / "custom-codex"
    agents_home = tmp_path / "custom-agents"
    env = {**os.environ, "CODEX_HOME": str(codex_home)}

    subprocess.run(
        [sys.executable, str(INSTALL_PATH), "--agents-home", str(agents_home)],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
        env=env,
    )

    payload = json.loads((codex_home / "redteam-install-manifest.json").read_text(encoding="utf-8"))
    assert payload["log_root"] == str(codex_home / "logs" / "codex-redteam")


def test_skill_resolver_ignores_agents_home_and_uses_project_dot_agents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    fake_home = tmp_path / "home"
    env_agents = tmp_path / "env-agents"
    _write_skill(project / ".agents" / "skills")
    _write_skill(env_agents / "skills")
    monkeypatch.setattr(skill_card.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("AGENTS_HOME", str(env_agents))

    resolved = skill_card.resolve_skills_dir(project / ".codex")

    assert resolved == project / ".agents" / "skills"


def test_skill_resolver_uses_custom_manifest_skills_root_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    custom_root = tmp_path / "custom-agents" / "skills"
    fake_home = tmp_path / "home"
    _write_skill(project / ".agents" / "skills")
    _write_skill(custom_root)
    manifest = project / ".codex" / "redteam-install-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "custom_skill_dirs_enabled": True,
                "skills_paths": {
                    "skills_root": str(custom_root),
                    "skill_dirs": [str(custom_root / "redteam-demo")],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_card.Path, "home", classmethod(lambda cls: fake_home))

    resolved = skill_card.resolve_skills_dir(project / ".codex")

    assert resolved == custom_root


def test_skill_resolver_falls_back_to_manifest_root_when_defaults_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    custom_root = tmp_path / "custom-agents" / "skills"
    fake_home = tmp_path / "home"
    _write_skill(custom_root)
    manifest = project / ".codex" / "redteam-install-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "custom_skill_dirs_enabled": False,
                "skills_paths": {
                    "skills_root": str(custom_root),
                    "skill_dirs": [str(custom_root / "redteam-demo")],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_card.Path, "home", classmethod(lambda cls: fake_home))

    resolved = skill_card.resolve_skills_dir(project / ".codex")

    assert resolved == custom_root


def test_runtime_log_root_comes_from_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    log_root = tmp_path / "custom-logs"
    fake_home = tmp_path / "home"
    manifest = project / ".codex" / "redteam-install-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"log_root": str(log_root)}), encoding="utf-8")
    monkeypatch.setattr(runtime_paths.Path, "home", classmethod(lambda cls: fake_home))

    resolved = runtime_paths.resolve_log_root(project / ".codex")

    assert resolved == log_root


def test_runtime_manifest_resolves_from_current_codex_dir_without_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex_home = tmp_path / "custom-codex"
    custom_root = tmp_path / "custom-agents" / "skills"
    log_root = tmp_path / "custom-logs"
    fake_home = tmp_path / "home"
    _write_skill(custom_root)
    manifest = codex_home / "redteam-install-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "log_root": str(log_root),
                "custom_skill_dirs_enabled": True,
                "skills_paths": {
                    "skills_root": str(custom_root),
                    "skill_dirs": [str(custom_root / "redteam-demo")],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(skill_card.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("CODEX_HOME", raising=False)

    assert runtime_paths.resolve_log_root(codex_home) == log_root
    assert skill_card.resolve_skills_dir(codex_home) == custom_root


def test_runtime_log_root_falls_back_to_user_codex_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    fake_home = tmp_path / "home"
    monkeypatch.setattr(runtime_paths.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("CODEX_HOME", raising=False)

    resolved = runtime_paths.resolve_log_root(project / ".codex")

    assert resolved == fake_home / ".codex" / "logs" / "codex-redteam"


def test_extract_transcript_path_from_hook_payload() -> None:
    payload = {"session": {"transcript_path": "C:/tmp/session.jsonl"}}

    assert prompt_parser.extract_transcript_path(payload) == "C:/tmp/session.jsonl"


def test_refusal_backstop_session_dir_uses_transcript_session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = tmp_path / "sessions" / "2026" / "07" / "10" / "current.jsonl"
    fake_home = tmp_path / "home"
    monkeypatch.setattr(refusal_backstop.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("CODEX_REDTEAM_SESSION_DIR", str(tmp_path / "ignored"))

    resolved = refusal_backstop._session_dir(str(transcript))

    assert resolved == tmp_path / "sessions"


def test_refusal_backstop_session_dir_falls_back_to_transcript_parent(tmp_path: Path) -> None:
    transcript = tmp_path / "transcripts" / "current.jsonl"

    assert refusal_backstop._session_dir(str(transcript)) == transcript.parent


def test_refusal_backstop_selects_previous_session_across_date_directories(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    previous = _write_session(sessions / "2026" / "07" / "09" / "previous.jsonl", 10)
    current = _write_session(sessions / "2026" / "07" / "10" / "current.jsonl", 20)

    selected = refusal_backstop._select_previous_session(None, str(current))

    assert selected == previous


def test_refusal_backstop_selects_previous_session_on_same_day(tmp_path: Path) -> None:
    day = tmp_path / "sessions" / "2026" / "07" / "10"
    previous = _write_session(day / "previous.jsonl", 10)
    current = _write_session(day / "current.jsonl", 20)

    assert refusal_backstop._select_previous_session(None, str(current)) == previous


def test_refusal_backstop_selects_latest_other_file_when_current_is_missing(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    older = _write_session(sessions / "2026" / "07" / "09" / "older.jsonl", 10)
    latest = _write_session(sessions / "2026" / "07" / "10" / "latest.jsonl", 20)
    missing_current = sessions / "2026" / "07" / "11" / "current.jsonl"

    assert refusal_backstop._select_previous_session(None, str(missing_current)) == latest
    assert latest != older


def test_refusal_backstop_does_not_fall_back_to_another_profile(tmp_path: Path) -> None:
    custom_sessions = tmp_path / "custom" / "sessions"
    current = _write_session(custom_sessions / "2026" / "07" / "10" / "current.jsonl", 20)
    _write_session(tmp_path / "home" / ".codex" / "sessions" / "2026" / "07" / "09" / "global.jsonl", 10)

    assert refusal_backstop._select_previous_session(None, str(current)) is None


def test_refusal_backstop_session_dir_uses_codex_home_without_transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex_home = tmp_path / "codex-home"
    fake_home = tmp_path / "home"
    monkeypatch.setattr(patcher.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_REDTEAM_SESSION_DIR", str(tmp_path / "ignored"))

    resolved = refusal_backstop._session_dir()

    assert resolved == codex_home / "sessions"


def test_session_patcher_default_session_dir_uses_codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert patcher.default_session_dir() == codex_home / "sessions"


def test_project_home_rejects_codex_home_mix(tmp_path: Path) -> None:
    project = tmp_path / "project"

    result = subprocess.run(
        [
            sys.executable,
            str(INSTALL_PATH),
            "--project-home",
            str(project),
            "--codex-home",
            str(project / "custom-codex"),
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    assert result.returncode == 2
