# Codex Red Team Opt-In Mode

[中文说明](./README_ZH.md)

**Current release:** v1.0.0

> Normal by default. Red-team mode is opt-in; once enabled, automation starts automatically by default.

A lightweight, evidence-driven red team runtime/configuration layer for Codex. Ordinary coding, documentation, and research tasks stay in normal mode unless the user explicitly enables red-team mode. When enabled, Loop Runtime SKILL.md domain cards declare scope, boundaries, and exit evidence — not instructions.

## Why This Project

Two common pitfalls in AI-assisted security work:

1. **Pollution of normal operations** — persistent red-team hints or system prompts bleed into everyday coding, causing refusals or unwanted behavior.
2. **Context bloat** — heavy injection of offensive doctrine increases token cost without improving routing quality.

This project solves both: **normal mode stays normal**, and red-team mode must be explicitly enabled. When enabled, SKILL.md Loop Runtime domain cards declare scope, boundaries, and exit evidence, while the 5-Phase engine drives evidence-based progression — not a monolithic prompt dump.

## Core Features

- **Three explicit modes**: `normal` (default), `redteam-light` (targeted analysis/planning), `redteam-full` (constrained red team workflow)
- **Structured JSON runtime state** with session-isolated state files
- **Rule-first phase detection** with semantic fallback for ambiguous tasks
- **Pack-first routing mainline**: `phase → router → pack → leaf` — method is a soft hint, not the primary routing axis
- **SKILL.md Loop Runtime domain cards** — pure Markdown `scope-not-instruct` format: each card has `## Domain` (scope declaration), `## Boundaries` (forbidden actions), `## Pivot Hints` (direction changes), `## Exit Evidence` (required artifacts and minimum attempts) — no YAML, no JSON
- **Graded feedback gates** — four-level gate decisions: `pass` (advance), `soft_fail` (retry/adjust), `pivot` (change path), `blocked` (halt for human)
- **Dedicated routing layer** — regex-based router engine (Chinese + English patterns), fine-grained sub-routers per domain (5 web, 4 AD, 6 crypto, 5 network, 3 mobile), external skill adapters (ACS/hackskills/qiushi)
- **Lightweight hooks** — activation engine, context prepoison, intent engine, loop engine, phase detector, semantic fallback, state manager, refusal backstop
- **Session patcher** — two-tier refusal detector (strong phrases + weak openers in Chinese + English), JSONL session cleaner with auto-backup and optional AI-powered rewrite
- **Bounded Loop Runtime** — each decision exposes a trigger, feedback gate, and exit condition so the agent can adjust pace before advancing
- **Artifact/gate-based progression** — prove one path before expanding, distinguish facts from assumptions
- **Automation Loop Runtime** — reads local MCP/tool inventory, derives required capabilities, runs scoped registered adapters, saves artifacts, and feeds gate decisions
- **Tool preference model**: prefer 5 practical tool classes (WebFetch, Browser MCP, IDA MCP, JADX MCP, Current AI Agent), fall back to equivalent local tools when needed
- **Managed incremental installer** — Python-based, preserves existing AGENTS.md and hooks.json, injects only managed blocks, supports `--uninstall` and idempotent upgrades

## Coverage Scenarios

### Core Phases

| Phase | Coverage |
|-------|----------|
| **Web** | Web exploitation, injection, SSRF, XSS, CSRF, deserialization |
| **AD** | Active Directory enumeration, Kerberoasting, delegation, trusts |
| **Post-Exploitation** | Persistence, lateral movement, privilege escalation, data exfiltration |
| **Reverse Engineering** | Binary analysis, protocol reversing, firmware extraction |
| **Code Audit** | Static analysis, vulnerability discovery, patch diffing |
| **Payload** | Generation, encoding, obfuscation, staging |
| **Evasion** | EDR/AV bypass, log tampering, indicator removal |

### Extended Router/Pack Families

| Domain | Detail Pack |
|--------|-------------|
| **Recon** | OSINT, network discovery, service enumeration |
| **API** | REST/GraphQL fuzzing, auth bypass, rate-limit evasion |
| **Auth** | OAuth, JWT, SAML, Kerberos, NTLM attack surfaces |
| **Injection** | SQL, LDAP, XPath, template, command injection variants |
| **File** | Upload attacks, path traversal, LFI/RFI, file parsing bugs |
| **Business Logic** | Workflow abuse, race conditions, privilege boundary violations |
| **Cloud** | AWS/Azure/GCP IAM, serverless, storage, metadata services |
| **Container / Kubernetes** | Escape, pod lateral movement, supply chain, misconfigured RBAC |
| **Network / Protocol** | MITM, ARP/DNS poisoning, BGP hijack, protocol fuzzing |
| **Crypto** | Weak cipher suites, padding oracles, nonce reuse, side channels |
| **Mobile** | APK/IPA analysis, certificate pinning bypass, deep link abuse |

## Installation

### Python (cross-platform)

```bash
python scripts/install.py
```

### Options

| Option | Description |
|--------|-------------|
| `--codex-home PATH` | Custom Codex home directory (default: `~/.codex`) |
| `--agents-home PATH` | Custom agents directory (default: `~/.agents`) |
| `--dry-run` | Preview all operations without writing any files |
| `--uninstall` | Remove all managed files, hooks, and AGENTS.md blocks |

```bash
# Preview before install
python scripts/install.py --dry-run

# Custom install location
python scripts/install.py --codex-home /opt/codex/home

# Full uninstall
python scripts/install.py --uninstall
```

### What the Installer Does

1. **Upgrade cleanup** — reads the manifest from the previous install (`~/.codex/redteam-install-manifest.json`), removes all old tracked paths, plus known legacy remnants (`legacy-redteam-hook.py`, `red-team-command-doctrine-old`)
2. **Core files** — copies `instruction.ctf.md` and `config.toml` to `~/.codex/`
3. **Hooks** — deploys `session-start-context.py`, `hook-security-context-hook.py`, `redteam_state.py`, and `core/` to `~/.codex/hooks/`
4. **Subsystems** — deploys `router/`, `orchestrator/`, `automation/`, and `session_patcher/` to `~/.codex/`
5. **Skill packs** — deploys all 34 SKILL.md domain cards from `agents/skills/` to `~/.agents/skills/` (only `SKILL.md` is copied per skill directory)
6. **Seed prompts** — copies prompt files to `~/.codex/prompts/` (skips existing)
7. **Merge hooks.json** — strips old managed hooks, then injects the current `SessionStart` and `UserPromptSubmit` hooks (preserves user-defined hooks)
8. **Merge AGENTS.md** — injects or updates a managed block (`<!-- codex-redteam-optin-mode:start -->`) into `~/.codex/AGENTS.md` (preserves user content outside the block)
9. **Write manifest** — records all managed paths to `~/.codex/redteam-install-manifest.json` for future upgrade/cleanup tracking
10. **Validate** — runs `scripts/validate.py` to verify every subsystem file is in place

### Upgrade & Idempotency

The installer is **idempotent** — running it repeatedly is safe and will not duplicate hooks or AGENTS.md blocks.

On each run, it reads the previous manifest, removes only project-managed files from the old install, then re-deploys from the current version. This means:
- Version upgrades are clean without touching user-owned files
- `copy_tree` replaces managed directories (`router/`, `orchestrator/`, etc.) wholesale; skill directories copy only `SKILL.md`
- `AGENTS.md` and `hooks.json` are never deleted — they use managed-block merge logic so user customizations survive
- Python cache files (`__pycache__`, `.pyc`, `.pyo`) are not copied into the installed runtime
- If the manifest is missing, the installer falls back to cleaning the current target set plus known legacy paths

```bash
# Safe to run repeatedly — same result each time
python scripts/install.py
python scripts/install.py   # second run: cleanup → fresh deploy → same state
```

## Quick Start

### Enable Red Team Mode

```text
进入红队模式
开启红队模式
/redteam on
/redteam light
/redteam full
enable red team mode
```

### Disable Red Team Mode

```text
退出红队模式
关闭红队模式
/redteam off
disable red team mode
```

### Mode Reference

| Mode | Default | Use Case |
|------|---------|----------|
| `normal` | Yes | Coding, documentation, general research |
| `redteam-light` | No | Targeted security analysis, planning, review |
| `redteam-full` | No | Constrained red team workflow, operations |

## Working Flow

When red-team mode is enabled, the runtime follows this mainline:

```
phase → router → pack → leaf
```

1. **Phase detection** — rule-first matching against task intent; semantic fallback when ambiguous
2. **Router** — maps phase to the appropriate detail pack family
3. **Pack** — loads the compact, testable skill pack for the matched domain
4. **Leaf** — executes the concrete skill or technique

`method` is a **soft hint** — it may add value for technique selection but is not the primary routing axis.

Evidence-first reasoning is enforced throughout: prove one path before expanding, distinguish facts from assumptions, end with one concrete next step.

## Loop Runtime

The Loop Runtime follows `Observe -> Decide -> Act -> Verify -> Record -> Next`. Every loop decision carries:

- `trigger`: why this loop started or changed direction
- `feedback_gate`: the gate used to judge whether the current step is valid
- `exit_condition`: the condition for advancing, pivoting, blocking, reporting, or refreshing context

The runtime now includes decision-tree path selection, rhythm classification, artifact/tool/scope gates, retry handling, quick-card refreshes, JSONL decision recording, and an executor adapter layer. In red-team mode, automation requires explicit `mode = "active"` / `"auto"` / `"assisted"` in config.toml to enable active execution; without configuration it defaults to `plan-only`. Direct tool execution is intentionally bounded behind Tool Registry, Scope Gate, Execution Gate, and registered Executor adapters.

## Automation Tool Policy

Before planning tool use, the automation layer reads the user's local MCP/tool inventory, derives required capabilities, then selects tools in this order:

1. **Prefer these 5 practical tool classes:**
   - `WebFetch` — content fetch and page analysis
   - `Browser MCP` — browser automation and engine-backed interaction
   - `IDA MCP` — binary reverse engineering and protocol analysis
   - `JADX MCP` — APK decompilation and API extraction
   - `Current AI Agent` — code generation and AI-assisted analysis using the AI agent the user is currently running
2. If a preferred tool is unavailable, select an equivalent registered local MCP/tool.
3. Record `preferred_tool`, `selected_tool`, `capability_match`, `risk`, and `fallback_reason`.
4. Execute only through Tool Registry → Scope Gate → Executor.
5. In red-team mode, run active automation by default; execute only when a scoped adapter is registered and all gates pass.
6. If a required tool, scope, or adapter is missing, block or pivot explicitly instead of pretending execution happened.
7. Save successful adapter output as artifacts and re-check gates before advancing.

## Validation

```bash
# Full test suite
python -m unittest discover -s tests -p "test_*.py"

# Quick validation
python scripts/validate.py
```

Validation covers:
- Installer integrity checks
- Routing correctness across all phase/pack combinations
- Mode switching (normal ↔ light ↔ full ↔ off)
- Loop runtime checks (decision tree, scope gate, adapter execution, retry, artifact saving, report gate)
- Orchestration gate checks (scope, report, artifact)
- Prompt-chain verification

## Known Limitations

- This is a **runtime/configuration layer**, not a complete attack platform — it provides routing, context management, adapter-based automation, and evidence gates, not hardcoded exploit code
- Tool availability depends on the user's local MCP/tool inventory
- Real execution requires explicitly registered scoped adapters; missing tools, scope, or adapters are blocked or pivoted instead of being treated as successful execution
- Red-team mode must be explicitly enabled per session
- Semantic phase detection is a fallback — rule-first matching is more reliable for well-defined task types

## Disclaimer

This project is intended **solely for authorized penetration testing, red team research, and defensive security experiments**. Users must obtain proper authorization before testing any system they do not own. The authors disclaim all liability for unauthorized or illegal use.

## Contributions & Acknowledgements

### Individual Contributors

- **Mingxi / 洺熙** — suggested adding semantic judgment as fallback for phase detection; proposed removing methodology while subdividing skills for smarter AI behavior
- **Nirvana** — proposed workflow optimization with overlay installation enablement
- **PINGS** — offered prompt-chain robustness review

### Reference Projects

Method layer, routing layer, and skill pack structure draw inspiration from:

- [qiushi-skill](https://github.com/qiushi-L/qiushi-skill)
- [yaklang/hack-skills](https://github.com/yaklang/hack-skills)
- [mukul975/Anthropic-Cybersecurity-Skills](https://github.com/mukul975/Anthropic-Cybersecurity-Skills)

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.

## License

[MIT](./LICENSE)
