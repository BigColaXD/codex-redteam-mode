# Changelog

All notable changes to the Codex Red Team Opt-In Mode project.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.1] - 2026-07-09

### Added

- Added `--project-home PATH` for project-level installs. It writes Codex runtime/config files to `<project>/.codex` and, by default, skill cards to `<project>/.agents/skills`.
- `--project-home` can be combined with `--agents-home PATH` to place skill cards in a custom agents directory while keeping project Codex config under `<project>/.codex`.

### Fixed

- Merged `config.toml` structurally instead of overwriting user-owned config, preserving existing MCP servers, model providers, project trust entries, automation mode, and other user settings.
- Protected `config.toml` during upgrade cleanup by tracking it as a merged file instead of a managed disposable path.
- Created timestamped `config.toml.YYYYMMDDHHMMSS.bak` backups before changing an existing config file. Dry-run, no-op merges, and invalid TOML do not create backups or modify files.
- Accepted UTF-8 BOM-prefixed existing config files during merge.

## [1.0.0] - 2026-06-28

### Changed - Loop Runtime Redesign (P0-P7)

- **Architecture**: Replaced multi-knowledge-card system (YAML/JSON runtime cards + references/) with lightweight Loop Runtime. Each skill is now a single `SKILL.md` domain card following Observe -> Decide -> Act -> Verify -> Record -> Next flow.
- **SKILL.md format**: Unified domain card with sections: `## Domain`, `## Boundaries`, `## Pivot Hints`, `## Exit Evidence`. Replaces `skill_card.yaml`, `skill_card.json`, and `references/` directories.
- **Graded feedback gates**: Introduced four-level gate system (`pass` / `soft_fail` / `pivot` / `blocked`) replacing binary pass/fail.
- **skill_card.py**: Rewritten to parse only SKILL.md (Markdown-native, no YAML/JSON dependency).
- **install.py**: New `copy_skill_md()` function copies only SKILL.md per skill directory instead of entire directory trees. Version bumped to 1.0.0.
- **install.py**: Directory copy now excludes Python cache files (`__pycache__`, `.pyc`, `.pyo`) so overlay installs stay clean even if the source tree contains local caches.
- **34 skill directories**: All converted to Loop Runtime SKILL.md format. Legacy YAML/JSON runtime cards and references directories are removed from `agents/skills/`.
- **brain.py**: Rewritten to 5-phase framework (recon -> test -> hypothesis -> verify -> report) with `phase_drive` orchestrator and per-domain halt mechanism.
- **Tool modules**: 5-module upgrade: `recon_ports`, `recon_subdomains`, `recon_directories` (upgraded), `vuln_scanner`, `sqli_detector` (new).
- **README.md / README_ZH.md**: Updated to describe Loop Runtime SKILL.md architecture, graded gates, automatic red-team automation startup, and new installer behavior.
- **Documentation encoding**: Restored README, README_ZH, and CHANGELOG text to valid UTF-8 without changing prompt/refusal-direction scripts.
- **Automation startup**: Red-team sessions default to `plan-only` when no explicit `[automation].mode` is configured. Set `mode = "active"` / `"assisted"` / `"auto"` in config.toml to enable active automation. This ensures no unintended tool execution without explicit opt-in.
- **CVE tool preference**: `cve_search`, `cve_lookup`, and `patch_status_check` now prefer WebFetch-compatible tools before browser automation fallbacks.

### Removed

- `skill_card.yaml`, `skill_card.yml`, and `skill_card.json` files under `agents/skills/`.
- `references/` directories under `agents/skills/`.

## [0.6.0] - 2026-06-22

### Added
- Loop Runtime automation skeleton with `Observe -> Decide -> Act -> Verify -> Record -> Next` flow.
- `LoopDecision` metadata fields: `trigger`, `feedback_gate`, `exit_condition`, `required_artifact`, `required_capability`, and `selected_tool`.
- Automation runtime modules: decision tree, loop state, gate engine, rhythm classifier, quick cards, executor adapter layer, loop recorder, and report builder.
- Registered executor adapters for bounded tool execution. Red-team `active` / `auto` / `assisted` automation starts an active executor; explicitly registered adapters can execute scoped steps and return standard `ExecutionResult` objects.
- Scope-gated runtime execution: tool steps are checked through Tool Registry and Scope Gate before adapter execution.
- Artifact-driven progression: successful adapter output is saved through `ArtifactStore` and fed back into artifact gates before advancing.
- Retry handling for retryable adapter failures.
- Strict `ReportGate` mode covering seven report-readiness gates: core evidence, reproduction, impact proof, multi-ID/parameter check, scope proof, false-positive exclusion, parameter portability, and CIA impact.
- Controller brief output for `[loop-trigger:]`, `[feedback-gate:]`, and `[exit-condition:]`.
- Loop runtime tests covering adapter execution, scope blocking, retry, artifact saving, decision logging, and strict report gates.

### Changed
- Updated README, README_ZH, and instruction profile to describe the current Loop Runtime and adapter-based automation behavior.
- Updated install validation to require the new automation runtime files.
- Updated installer version to `0.6.0`.
- Aligned `config.toml` tool priority with README and template by adding `Current AI Agent`.

### Fixed
- Restored normal UTF-8 Chinese red-team activation and disable trigger text in `instruction.ctf.md`.
- Fixed Windows `hooks.json` template path escaping during install.
- Fixed direct import crash in `hooks/core/method_engine.py` by using the shared router mappings module.
- Fixed controller phase fallback so summarize/revise/new-objective prompts no longer inherit stale domain phases; only genuine continue prompts preserve the previous phase.
- Fixed prompt extraction fallback so explicit non-user `system`/`assistant` messages are not treated as user prompts, while role-less legacy messages remain supported.
- Fixed Scope Gate behavior for scoped tools with a target but no declared `in_scope`; these now return `missing_scope` instead of default allow.
- Fixed Loop Runtime verification so empty execution results cannot satisfy verification via Python's `all([])` behavior.
- Added regression coverage for method import, prompt role filtering, phase fallback, missing scope, and empty execution-result verification.

### Notes
- This release adds a real automation loop runtime and adapter execution path, but it does not hardcode direct shell, scanner, exploit, or network execution. Real tools must be wired through explicit scoped adapters.

## [0.5.0] - 2026-06-14

### Added
- Dedicated routing layer (`codex/router/`) with regex-based router engine supporting Chinese + English pattern detection, pack selector, leaf selector, and method engine.
- External skill adapters for ACS, hackskills, and qiushi reference repositories (`codex/router/adapters/`).
- Fine-grained sub-routers per domain: 5 web sub-routers, 4 AD sub-routers, 6 crypto sub-routers, 5 network protocol sub-routers, and 3 mobile sub-routers.
- Session patcher system (`codex/session_patcher/`) with two-tier refusal detector, JSONL session file cleaner with auto-backup, refusal-content replacement, and optional AI-powered rewrite.
- Cross-platform installer launchers: `install.ps1` for Windows PowerShell and `install.sh` for macOS/Linux bash.
- Templates directory with `hooks.json.template` and `config.toml.example`.
- Expanded test suite covering router, orchestrator, automation tools, controller, install, modes, and session patcher.
- Enhanced `scripts/validate.py` with per-subsystem file verification.

### Changed
- Updated `config.toml` to include `Current AI Agent` as the fifth preferred tool class.
- Refined installer with managed manifest tracking, idempotent upgrades, stale legacy path cleanup, and `--uninstall` support.
- Tightened phase-to-method escalation mappings with per-domain defaults.
- Router now uses dedicated `mappings.py` for all phase-to-router, router-to-pack, and phase-to-method lookups.

## [0.4.0] - 2026-05-18

### Changed
- Normalized the GitHub version around the effective `phase -> router -> pack -> leaf` runtime model.
- Reduced method emphasis to a soft hint instead of the primary routing axis.
- Tightened evidence inference to avoid overconfident `confirmed` labels.
- Aligned session-start, runtime, docs, and tests with actual pack-first behavior.

### Added
- Expanded domain routing for cloud, container, network, crypto, and mobile scenarios.
- Added dedicated detail packs for recon, API, auth, injection, file, business logic, cloud, container, network, crypto, and mobile.
- Expanded validation coverage for the new routing domains.
- Installer cleanup for known stale legacy runtime paths.

## [0.3.0] - 2026-05-14

### Changed
- Removed methodology layer; subdivided skills for smarter AI behavior during work phases.
- Added semantic judgment as fallback for phase detection.
- Optimized workflow routing based on community feedback.

### Added
- Overlay installation enablement. Thanks Nirvana.

## [0.2.0] - 2026-05-11

### Added
- Extended router/pack families beyond core phases.
- Initial validation and orchestration gate checks.
- Prompt-chain verification tests.

### Changed
- Improved prompt-chain text robustness. Thanks PINGS.
- Refined hook injection to stay lightweight.

## [0.1.0] - 2026-05-07

### Added
- Initial release offering `normal`, `redteam-light`, and `redteam-full` modes.
- Structured JSON runtime state with session isolation.
- Rule-first phase detection with semantic fallback.
- Pack-first routing mainline: `phase -> router -> pack -> leaf`.
- Core phase coverage spanning web, AD, post-exploitation, reverse engineering, code-audit, payload, and evasion.
- Managed incremental installer for Python and PowerShell.
- Reference method layer and technology routing layer from three external skill repositories.

[1.1.1]: https://github.com/chAng-L19/codex-redteam-mode/releases/tag/v1.1.1
[1.0.0]: https://github.com/chAng-L19/codex-redteam-mode/releases/tag/v1.0.0
[0.6.0]: https://github.com/chAng-L19/codex-redteam-mode/releases/tag/v0.6.0
[0.5.0]: https://github.com/chAng-L19/codex-redteam-mode/releases/tag/v0.5.0
[0.4.0]: https://github.com/chAng-L19/codex-redteam-mode/releases/tag/v0.4.0
[0.3.0]: https://github.com/chAng-L19/codex-redteam-mode/releases/tag/v0.3.0
[0.2.0]: https://github.com/chAng-L19/codex-redteam-mode/releases/tag/v0.2.0
[0.1.0]: https://github.com/chAng-L19/codex-redteam-mode/releases/tag/v0.1.0
