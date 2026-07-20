# Codex Red-Team Opt-In Mode

[中文](./README_ZH.md)

**Current version: v2.0.0**

> Normal mode remains the default. The durable red-team operation runtime starts only after explicit activation, while the system-layer base instructions and active model profile remain loaded in every mode.

An opt-in, durable red-team runtime for Codex App and Codex CLI. It compiles each objective into a criteria-bearing `GoalContract`, executes typed `WorkflowSpec` graphs through live MCP tools, preserves verified evidence, and reaches successful terminal state only after `TerminalJudge` proves every criterion.

## Usage Instructions

Before using this project, you should read the [README](./README_ZH.md) file completely to prevent any issues during use.

### About Model Security Review

1. For `GPT-5.4`, this model does not have `trusted network access`, so you can directly use this project for penetration testing.
2. For `GPT-5.5` and `GPT-5.6`, there are `other models` on the cloud that monitor the model's output, and if the output violates rules, it will `ban this session`. Therefore, to ensure smooth usage, please make sure: `your ChatGPT account has passed trusted network access`, `use GPT-5.4`, `use Claude-Opus-4-6`, or `use other models without security review`.

### Asking Questions Wisely

1. If you have questions about the content in the **README**, you should submit an **ISSUE**, including the corresponding content from the **README** to seek help, or ask in the **WeChat group** in the same way.

   Do:
   ```text
   [Paste the text from the README], I have a question here, how/why/what should I do
   ```
   Don't:
   ```text
   Why is it different when I open it compared to the video?
   ```

2. If you have suggestions or ideas for maintaining the project, you can `submit an ISSUE`, `submit a Pull Request`, or `suggest in the WeChat group`.

   Do:
   ```text
   I have a suggestion regarding xxx [image], here we can modify/add/delete xxx
   ```
   Don't:
   ```text
   Can we add a plugin/feature for cracking keys?
   ```

### Disclaimer

This project is **only for authorized penetration testing, red team research, and defensive security experiments**. Users must obtain proper authorization before testing any systems they don't own. The author assumes no responsibility for unauthorized or illegal use.

## Why This Project
## Motivation

Codex can use many security tools, but long-running workflows are vulnerable to session interruption, tool variance, manual result relay, and false completion based on a tool success flag. This project unifies objectives, actions, evidence, recovery, and terminal judgment in one durable execution path:

```text
GoalContract
  -> WorkflowSpec
  -> Durable Scheduler
  -> ToolBroker
  -> SemanticVerifier
  -> EvidenceGraph
  -> TerminalJudge
```

Version 2.0.0 removes the former `phase -> router -> pack -> leaf` runtime, regex domain routers, Markdown exit gates, and the second Automation state machine. Domain names now act only as asset and technique metadata rather than control-plane branches.

## Core Features

- **Explicit activation**: `normal` is always the default, and red-team operations start only after a mode command.
- **Typed execution**: eight versioned TOML workflows cover web/API, external assessment, source review, binary/mobile, identity/cloud, adversary emulation, model security, and generic adaptive operations.
- **Live tool collaboration**: tools are discovered through stdio or Streamable HTTP MCP; Host-only capabilities execute against an output contract and submit observations without user relay.
- **Durability and batch autonomy**: SQLite WAL, events, leases, idempotency keys, and independent run IDs support recovery, concurrency control, multi-target batches, and cancellation cleanup.
- **Evidence-driven completion**: only semantically verified results with target binding, parent lineage, reproduction, impact, coverage, and rollback proof can satisfy `TerminalJudge`.

## Installation

### Install Commands

From the repository root, install dependencies and deploy to the current user Codex Home:

```bash
python -m pip install -r requirements.txt
python scripts/install.py
```

The installer detects the model from the environment, target config, or existing manifest; `--model` is normally unnecessary.

Project-local installation:

```bash
python scripts/install.py --project-home PATH
```

Custom Skill and durable operation roots:

```bash
python scripts/install.py --project-home PATH --agents-home AGENTS_PATH --enable-custom-skill-dirs --log-root OPERATION_PATH
```

### Options

| Option | Description |
|---|---|
| `--codex-home PATH` | Install into a specific Codex Home/profile; its `AGENTS.md` provides global guidance |
| `--project-home PATH` | Install under `PATH/.codex` and `PATH/.agents`, and manage the project-root `AGENTS.md`; mutually exclusive with `--codex-home` |
| `--agents-home PATH` | Select the Skill destination; custom roots should also use `--enable-custom-skill-dirs` |
| `--enable-custom-skill-dirs` | Prefer the manifest-recorded custom Skill directory at runtime |
| `--log-root PATH` | Select the durable root for SQLite state, events, and evidence artifacts |
| `--model MODEL` | Optional: override automatic detection and explicitly select the installation-time system profile |
| `--dry-run` | Preview installation, upgrade, or uninstall actions without writing files |
| `--uninstall` | Remove manifest-managed files, Hooks, config values, and `AGENTS.md` blocks |

```bash
# Preview a project-local installation
python scripts/install.py --project-home PATH --dry-run

# Uninstall a user-level deployment
python scripts/install.py --uninstall

# Uninstall a project-local deployment
python scripts/install.py --project-home PATH --uninstall
```

### Runtime State Locations

The default operation root is:

```text
$CODEX_HOME/redteam-mode/operations/
├── runtime.sqlite3
└── artifacts/<run-id>/*.json
```

Hook session state is stored under `$CODEX_HOME/redteam-mode/state/sessions`. Use `--log-root OPERATION_PATH` to relocate operation data. Status responses inline no more than 64 KiB of evidence; larger verified payloads are fetched with `redteam_evidence`, and each evidence payload is capped at 4 MiB.

Upgrade and uninstall preserve runtime session, memory, and operation data for recovery, auditing, or manual cleanup.

### What the Installer Does

- Preserves existing user configuration and manages only installer-owned fields and files.
- Merges `config.toml`, Hooks, the system-layer model profile catalog, Runtime MCP server, workflows, and the single boundary Skill.
- Deploys a candidate through a pending transaction and commits the manifest only after operational validation passes.
- Preflights invalid manifests, TOML, Hook config, and out-of-scope managed paths before upgrade cleanup.
- Removes only unchanged managed content during uninstall while preserving user-modified config, prompts, Hooks, and `AGENTS.md` content.

## Quick Start

1. Complete installation and restart Codex App or Codex CLI.
2. Start a new task and submit `/redteam on`, `/redteam light`, or `/redteam full` as a standalone prompt.
3. Submit the complete objective. The Hook compiles it into a `GoalContract`, with independent operations for single or multiple targets.
4. `redteam_run` starts or resumes execution and uses `ToolBroker` to invoke available MCP tools.
5. Host-only tools receive a `next_action_spec`, gate, exit condition, and output contract, then automatically submit their observation to the Runtime.
6. `TerminalJudge` emits the final result after proving every target criterion, evidence lineage, and cleanup state.
7. Submit `/redteam off` or `disable red team mode` to return to normal mode.

The optional CLI wrapper pins one model-family profile for the current process:

```bash
codex-redteam --model gpt-5.6-sol
```

Changing model families requires a new App task or wrapper process so that `model_instructions_file` is reloaded.

### Modes

| Mode | Default | Typical Use |
|---|---:|---|
| `normal` | Yes | Ordinary coding, documentation, and research; no red-team operation or operation doctrine is started |
| `redteam-light` | No | Explicit durable Goal/Workflow execution through `/redteam on` or `/redteam light` |
| `redteam-full` | No | Explicit full-mode marker; in v2.0.0 it shares the same Runtime, evidence rules, and TerminalJudge gates as light mode |

## Validation

```bash
# Install test dependencies
python -m pip install -r requirements-dev.txt

# Run the complete test suite
python -m pytest -q

# Validate an installation rooted at the current directory
python scripts/validate.py --codex-home .
```

Installer and test coverage includes:

- Starting the Runtime MCP server and loading all eight workflows.
- Config merge, transactional upgrade, App/CLI Hooks, model profiles, and uninstall preservation.
- Concurrent start/recovery, leases, idempotent results, batch cancellation, and cleanup status.
- Rejection of false terminal states, false evidence, incorrect target binding, and derived evidence without trusted parents.
- Live stdio/Streamable HTTP MCP, Host Agent handoff, secret redaction, and workflow drift protection.

GitHub Actions runs the full suite on Windows, Ubuntu, and macOS with Python 3.11.

## Contributions & Acknowledgements
## Known Limitations

- Execution capability depends on the MCP or Host Agent tools currently available; missing capabilities remain as a pending handoff or deferred action.
- MCP tools whose names, descriptions, and input schemas do not expose their capabilities require explicit `automation.tool_capabilities` entries.
- `redteam-light` and `redteam-full` share the same engine and terminal rules in v2.0.0; the mode label does not select a separate workflow policy.
- Each evidence payload is capped at 4 MiB, while normal status output inlines only 64 KiB; larger evidence must be fetched through `redteam_evidence`.
- New tasks reset to normal mode, and changing model families requires a new task or wrapper process.

## Contributions and Acknowledgements

### Individual Contributors

- **Mingxi / 洺熙** — suggested semantic judgment as a phase-detection fallback and proposed removing the methodology layer while subdividing Skills to improve Agent behavior.
- **Nirvana** — proposed workflow optimization and overlay installation support.
- **PINGS** — contributed jailbreak text enhancements and prompt-chain robustness improvements.

### Reference Projects

The earlier routing/Skill design and current runtime research drew from:

- [qiushi-skill](https://github.com/qiushi-L/qiushi-skill)
- [yaklang/hack-skills](https://github.com/yaklang/hack-skills)
- [Anthropic-Cybersecurity-Skills](https://github.com/mukul975/Anthropic-Cybersecurity-Skills)
- [gpt-5.6-instruct](https://github.com/MDX-Tom/gpt-5.6-instruct)

## Star History

<a href="https://www.star-history.com/?repos=chAng-L19%2Fcodex-redteam-mode&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=chAng-L19/codex-redteam-mode&type=date&theme=dark&legend=top-left&sealed_token=CKO8uuC9r4XaKg8t4S3lVosw8UEFEOEmUKhK1gspPwDXctFtdeVgYQ-aWPH8rWLhIDCaZUmPasrE5qceMhl1M-dDRmHrpHDJ1lg4ZYhqGWAqYv8mcUdVEQ" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=chAng-L19/codex-redteam-mode&type=date&legend=top-left&sealed_token=CKO8uuC9r4XaKg8t4S3lVosw8UEFEOEmUKhK1gspPwDXctFtdeVgYQ-aWPH8rWLhIDCaZUmPasrE5qceMhl1M-dDRmHrpHDJ1lg4ZYhqGWAqYv8mcUdVEQ" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=chAng-L19/codex-redteam-mode&type=date&legend=top-left&sealed_token=CKO8uuC9r4XaKg8t4S3lVosw8UEFEOEmUKhK1gspPwDXctFtdeVgYQ-aWPH8rWLhIDCaZUmPasrE5qceMhl1M-dDRmHrpHDJ1lg4ZYhqGWAqYv8mcUdVEQ" />
 </picture>
</a>

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the contribution workflow, coding conventions, and submission requirements.

## License

[MIT](./LICENSE)
