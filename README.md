# Codex Red-Team Mode

An opt-in, durable red-team operation runtime for Codex App and Codex CLI.

The project compiles a user objective into a typed `GoalContract` with objective-specific criteria, executes single-domain, cross-domain, or multi-target batch `WorkflowSpec` graphs through live MCP tools, stores an evidence graph, resumes after interruption, and reaches terminal state only when `TerminalJudge` proves every criterion.

## What Changed

The runtime no longer uses `phase -> router -> pack -> leaf`, regex domain routers, Markdown exit gates, or a second automation state machine. Thirty-six domain cards were replaced with one boundary-only skill:

```text
GoalContract
  -> WorkflowSpec
  -> Durable Scheduler
  -> ToolBroker
  -> SemanticVerifier
  -> EvidenceGraph
  -> TerminalJudge
```

## Core Properties

- **Opt-in mode**: normal mode remains the default.
- **System-layer profiles**: `model_instructions_file` loads the composed base and model-specific instructions.
- **Typed workflows**: eight versioned TOML workflows cover web/API, external, source, binary/mobile, identity/cloud, adversary emulation, model security, and generic adaptive operations.
- **Live MCP discovery**: stdio and Streamable HTTP servers are discovered through `initialize` and `tools/list`.
- **Complementary tool use**: discovery actions can collect a bounded ensemble of independent MCP results while validation stays focused on one proven path.
- **Durable execution**: SQLite WAL state, events, leases, idempotency results, and verified evidence survive process/session interruption.
- **No user relay**: host-only tool output is submitted through `redteam_run.observation/observations`; users do not copy results between prompts.
- **Semantic evidence**: user prose, filenames, report text, and tool success flags do not prove findings.
- **Strict terminal state**: required actions, target coverage, evidence lineage, reproduction, impact, coverage, cleanup, and report predicates must pass.
- **Batch autonomy**: multi-target goals retain independent workflows/run IDs with aggregate resume, Host handoff, terminal status, and cancellation.

## Installation

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Install into the user Codex home:

```bash
python scripts/install.py --model gpt-5.6-sol
```

Install into a project-local Codex profile:

```bash
python scripts/install.py --project-home PATH --model gpt-5.6-sol
```

Optional custom skill root:

```bash
python scripts/install.py --project-home PATH --agents-home AGENTS_PATH --enable-custom-skill-dirs --model gpt-5.6-sol
```

Optional durable operation root:

```bash
python scripts/install.py --project-home PATH --log-root OPERATION_PATH --model gpt-5.6-sol
```

The installer performs a transactional deployment and operational validation before committing the manifest.

## Installed Configuration

The installer preserves existing user config and manages these values:

```toml
model_instructions_file = './redteam-mode/system-instructions.md'

[features]
hooks = true
automation = true

[automation]
mode = "active"
max_actions_per_cycle = 16
action_timeout_seconds = 60
max_retries_per_action = 2
max_domains = 7
max_hypothesis_branches = 4
persist_run_state = true

# Optional capability declarations for opaque MCP tool metadata:
# [automation.tool_capabilities]
# "server:tool" = ["page_fetch", "controlled_validation"]

[mcp_servers.codex-redteam-runtime]
command = "PYTHON_EXECUTABLE"
args = ["-m", "runtime.mcp_server", "--root", "OPERATIONS_ROOT"]
enabled = true

[mcp_servers.codex-redteam-runtime.env]
PYTHONPATH = "CODEX_HOME"
CODEX_HOME = "CODEX_HOME"
```

The installer does not add a `preauthorized_targets` setting.

## App Workflow

1. Install the project and restart Codex App.
2. Start a task and submit `/redteam on`, `/redteam light`, or `/redteam full` as a standalone prompt.
3. Submit the operation objective.
4. The Hook compiles the objective, preserves cross-domain hints, or assigns each target to an independent operation.
5. `redteam_run` consumes live MCP tools directly and can combine up to three complementary discovery results.
6. If a capability exists only in the current App agent, the action contract exposes its phase, trigger, feedback gate, exit condition, and output schema for automatic Host execution and submission.
7. Every runtime transition mirrors run IDs, pending actions, artifacts, and terminal outcome into Hook session state for automatic recovery.
8. The final response is emitted only after every target/domain criterion has lineage-linked reproduction, impact, coverage, and cleanup proof.

Starting a new App task reloads `model_instructions_file`. The static system catalog selects the profile from Hook model metadata. It supports model-family selection without writing user-layer prompt text.

## CLI Workflow

Ordinary CLI sessions use the same installed system prompt, Hooks, MCP runtime, and mode commands.

The optional wrapper enforces one system profile for the process:

```bash
codex-redteam --model gpt-5.6-sol
```

The wrapper builds a temporary single-profile system instructions file and deletes it after the Codex process exits. Switching to another model family requires a new wrapper process.

## MCP Runtime Tools

| Tool | Purpose |
|---|---|
| `redteam_run` | Autonomous single entrypoint for single/batch start, resume, and Host observations |
| `redteam_start` | Compile and start a new durable operation |
| `redteam_resume` | Continue an existing operation |
| `redteam_status` | Return actions, evidence, and missing predicates |
| `redteam_submit_observation` | Submit host-agent tool output through semantic verification |
| `redteam_evidence` | Fetch one verified payload omitted from compact status output |
| `redteam_cancel` | Cancel one operation or an entire batch and persist each cleanup status |
| `redteam_events` | Return a cursor-paginated append-only event trace |

The runtime excludes its own MCP server while discovering downstream tools, preventing recursive self-discovery.

## Workflow Model

Each `codex/workflows/*.toml` file declares:

- workflow ID and version
- semantic match tags
- typed actions and dependencies
- alternative required capabilities
- expected artifact and verifier
- risk, timeout, retries, and optional rollback action
- tool strategy plus explicit phase, trigger, feedback gate, and exit condition
- terminal predicates and required artifacts

Domain names are metadata, not control-plane branches.

## Evidence Model

Every verified node contains:

- operation and action IDs
- target and tool identity
- artifact type and semantic verifier
- raw structured payload
- SHA-256 content hash
- parent evidence IDs
- confidence and timestamp

Derived evidence requires verified parents. Reproduction requires concrete replay data, impact requires measured outcomes, coverage requires negative controls, and cleanup requires verified rollback state. Evidence schema v2 preserves independent provenance when multiple tools return identical content and migrates legacy database/artifact layouts.

## Persistence

Operation state is stored below the configured operation root (default: `$CODEX_HOME/redteam-mode/operations`):

```text
runtime.sqlite3
artifacts/<run-id>/*.json
```

SQLite uses WAL mode and explicit schema metadata. An operation lease serializes schedulers, action leases protect individual calls, and deterministic idempotency keys prevent replay after recovery. Workflow version/fingerprint binding rejects silent definition drift.

Multi-target operations use a deterministic batch ID bound to parent session, objective, and targets, preventing a later goal in the same task from joining an older batch. A shared cross-process lock serializes Runtime and App/CLI Hook session-state updates before atomic replacement.

Goals without a target return `waiting_goal_input` before any action runs. Goal, event, result, and evidence payloads are recursively redacted before persistence; evidence is capped at 4 MiB. On POSIX, runtime directories and files are created with private permissions.

Status responses inline evidence payloads up to 64 KiB. Larger verified nodes retain metadata and can be fetched on demand with `redteam_evidence`, keeping normal App/CLI context compact.

## Single Boundary Skill

Only `agents/skills/redteam-boundary-policy/SKILL.md` is installed. It defines evidence integrity, target/session binding, secret handling, reversibility, and tool-handoff rules.

It does not route tasks and never participates in terminal predicates.

## Validation

Install development dependencies and run the complete suite:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/validate.py --codex-home .
```

The validator performs an MCP server self-test and loads all eight workflows. Tests cover false terminal prevention, false evidence rejection, concurrent start/recovery, actionable Host Agent handoff, cancellation, secret redaction, workflow drift, live stdio/HTTP MCP transports, installer transactions, App/CLI hooks, and uninstall preservation.

## Uninstall

```bash
python scripts/install.py --uninstall
```

For project-local installs:

```bash
python scripts/install.py --project-home PATH --uninstall
```

Only manifest-owned files and managed config/Hook values are removed. User-modified config, prompts, Hooks, and AGENTS content are preserved.

## Repository Layout

```text
codex/runtime/       durable operation engine and MCP server
codex/workflows/     typed workflow specifications
codex/hooks/         App/CLI lifecycle bridge
codex/prompts/       model-specific system profiles
agents/skills/       single boundary policy skill
scripts/             transactional installer and validator
tests/               runtime, adversarial, Hook, and install tests
```

## References

The runtime design draws from Codex Skills/MCP guidance, PentestGPT task trees, CAI agent/tool patterns, MITRE CALDERA operations, Atomic Red Team actions, Cybench, and CyberSecEval capability/utility evaluation.

The release acceptance criteria for model capability utilization, professional workflow quality, and start-to-goal automation are tracked in `CAPABILITY_ACCEPTANCE.md`.
