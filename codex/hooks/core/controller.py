from __future__ import annotations

import json
import os
import tomllib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime import AdaptivePlanner, GoalCompiler, WorkflowRegistry

try:
    from redteam_state import RedTeamState
except ModuleNotFoundError:
    from hooks.redteam_state import RedTeamState

from .intent_engine import detect_intent


ACTIVE_AUTOMATION_MODES = {"active", "auto", "assisted", "execute", "execution"}
PLAN_ONLY_AUTOMATION_MODES = {"off", "false", "0", "plan", "plan-only", "plan_only", "dry-run"}


@dataclass
class ProcessTurnResult:
    state: RedTeamState
    brief: str
    overlay: str
    artifact: object | None
    reason_code: str


def _automation_configs(codex_dir: Path) -> list[tuple[dict[str, Any], Path]]:
    candidates: list[Path] = []
    explicit = os.environ.get("CODEX_REDTEAM_CONFIG", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(
        [
            codex_dir / "config.toml",
            codex_dir.parent / "config.toml",
            Path.home() / ".codex" / "config.toml",
        ]
    )
    resolved: list[tuple[dict[str, Any], Path]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False)).casefold()
        if key in seen or not candidate.is_file():
            continue
        seen.add(key)
        try:
            payload = tomllib.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if isinstance(payload, dict):
            resolved.append((payload, candidate))
    return resolved


def _automation_mode_from_config(codex_dir: Path, redteam_mode: str) -> str:
    if redteam_mode not in {"redteam-light", "redteam-full"}:
        return "plan-only"
    environment = os.environ.get("CODEX_REDTEAM_AUTOMATION_MODE", "").strip().casefold()
    if environment:
        return "active" if environment in ACTIVE_AUTOMATION_MODES else "plan-only"
    for config, _ in _automation_configs(codex_dir):
        features = config.get("features") if isinstance(config.get("features"), dict) else {}
        automation = config.get("automation") if isinstance(config.get("automation"), dict) else {}
        if features.get("automation") is False:
            return "plan-only"
        configured = str(automation.get("mode") or "").strip().casefold()
        if configured in ACTIVE_AUTOMATION_MODES:
            return "active"
        if configured in PLAN_ONLY_AUTOMATION_MODES:
            return "plan-only"
    return "active"


def process_turn(
    *,
    prompt: str,
    state: RedTeamState,
    codex_dir: Path,
    assistant_summary: str = "",
) -> ProcessTurnResult:
    del assistant_summary
    working = deepcopy(state).normalized()
    intent = detect_intent(prompt, working)
    if working.goal_terminal and intent.intent_type not in {"new", "revise"}:
        working.intent_type = intent.intent_type
        working.operation_status = "completed" if working.goal_success else working.operation_status
        working.next_action_id = ""
        working.pending_action = {}
        brief = "\n".join(
            [
                f"[workflow:{working.workflow_id or 'unknown'}]",
                f"[operation-status:{working.operation_status or 'terminal'}]",
                "[goal-terminal:true]",
                f"[goal-success:{str(working.goal_success).lower()}]",
                "[feedback-gate:semantic-terminal-judge]",
                "[exit-condition:goal-contract-satisfied]",
                "[next-action:none]",
            ]
        )
        if working.batch_session_id:
            reference = f"batch_session_id={working.batch_session_id!r}"
        else:
            reference = f"run_id={working.operation_run_id!r}"
        return ProcessTurnResult(
            state=working,
            brief=brief,
            overlay=f"[operation-terminal] Preserve the proven terminal state; retrieve its evidence with redteam_run using {reference}.",
            artifact=None,
            reason_code="terminal",
        )
    if not working.objective or intent.intent_type in {"new", "revise"}:
        working.objective = intent.objective_delta or prompt.strip()
        working.operation_run_id = ""
        working.workflow_terminal = False
        working.goal_terminal = False
        working.goal_success = False
    compiler = GoalCompiler()
    goal = compiler.compile(working.objective or prompt.strip())
    workflow = AdaptivePlanner().plan(goal, WorkflowRegistry())
    workflow_hint = "" if len(goal.targets) > 1 else ",".join(goal.workflow_hints)
    automation_mode = _automation_mode_from_config(codex_dir, working.mode)
    working.intent_type = intent.intent_type
    working.workflow_id = workflow.workflow_id
    working.operation_status = "dispatch_pending" if automation_mode == "active" else "planned"
    working.next_action_id = "redteam_run" if automation_mode == "active" else ""
    working.pending_action = (
        {
            "dispatch": "redteam_run",
            "session_id": working.session_id or "default",
            "objective": goal.objective,
            "targets": list(goal.targets),
            "workflow_hint": workflow_hint,
            "constraints": {"opsec_level": working.opsec_level},
        }
        if automation_mode == "active"
        else {}
    )
    brief = "\n".join(
        [
            f"[workflow:{workflow.workflow_id}]",
            f"[operation-status:{working.operation_status}]",
            f"[automation-mode:{automation_mode}]",
            "[goal-terminal:false]",
            "[goal-success:false]",
            "[feedback-gate:semantic-terminal-judge]",
            "[exit-condition:goal-contract-satisfied]",
            f"[targets:{','.join(goal.targets) or 'missing'}]",
            f"[next-action:{working.next_action_id or 'none'}]",
        ]
    )
    if automation_mode == "active":
        call = {
            "session_id": working.session_id or "default",
            "objective": goal.objective,
            "targets": list(goal.targets),
            "workflow_hint": workflow_hint,
            "constraints": {"opsec_level": working.opsec_level},
        }
        overlay = (
            "[operation-dispatch] Call redteam_run with this JSON and keep the returned run_id: "
            f"{json.dumps(call, ensure_ascii=False)}. Continue through redteam_run. "
            "For a pending host-only capability, execute the action with the current Codex tools, call "
            "redteam_run with its observation field using the returned next_action_spec/output_contract. "
            "Do not ask the user to relay tool output."
        )
        reason_code = "dispatch_pending"
    else:
        overlay = (
            f"[operation-plan] Selected workflow {workflow.workflow_id}; automation is plan-only, so do not invoke execution tools."
        )
        reason_code = "planned"
    return ProcessTurnResult(
        state=working,
        brief=brief,
        overlay=overlay,
        artifact=None,
        reason_code=reason_code,
    )
