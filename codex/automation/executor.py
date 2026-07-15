from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .planner import AutomationStep


@dataclass(frozen=True)
class ExecutionResult:
    step_id: str
    tool: str
    capability: str
    status: str
    artifact_type: str = ""
    artifact_path: str = ""
    summary: str = ""
    error: str = ""
    retryable: bool = False
    fallback_candidate: str = ""
    next_hint: str = ""
    artifact_payload: object | None = None


class Executor:
    """Bounded execution adapter.

    The runtime can reason about execution outcomes without directly invoking
    shell commands, scans, or network tools from this layer. Real execution is
    provided by registered adapters, which lets MCP/tool bridges stay explicit.
    """

    def __init__(self, *, plan_only: bool = True) -> None:
        self.plan_only = plan_only
        self._adapters: dict[str, Callable[[AutomationStep, Mapping[str, object]], object]] = {}

    def register_adapter(
        self,
        tool_name: str,
        adapter: Callable[[AutomationStep, Mapping[str, object]], object],
    ) -> None:
        self._adapters[str(tool_name)] = adapter

    def registered_tools(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def run_step(self, step: AutomationStep, args: Mapping[str, object] | None = None) -> ExecutionResult:
        args = args or {}
        if self.plan_only:
            return ExecutionResult(
                step_id=step.id,
                tool=step.tool,
                capability=step.required_capability,
                status="skipped",
                artifact_type=step.expected_artifact,
                summary="plan_only: tool execution was not invoked",
                retryable=False,
                fallback_candidate="" if step.fallback_reason == "preferred_tool_available" else step.preferred_tool,
                next_hint="run_through_scope_gate_before_execution",
            )
        adapter = self._adapters.get(step.tool)
        if not adapter:
            return ExecutionResult(
                step_id=step.id,
                tool=step.tool,
                capability=step.required_capability,
                status="blocked",
                artifact_type=step.expected_artifact,
                error="adapter_not_registered",
                retryable=False,
                fallback_candidate="" if step.fallback_reason == "preferred_tool_available" else step.preferred_tool,
                next_hint="register_adapter_or_select_fallback_tool",
            )
        try:
            raw = adapter(step, args)
        except (OSError, TimeoutError, ConnectionError, IOError) as exc:
            # Transient I/O or network errors — retryable
            return ExecutionResult(
                step_id=step.id,
                tool=step.tool,
                capability=step.required_capability,
                status="failed",
                artifact_type=step.expected_artifact,
                error=str(exc),
                retryable=True,
                fallback_candidate="" if step.fallback_reason == "preferred_tool_available" else step.preferred_tool,
                next_hint="retry_or_fallback_tool",
            )
        except (TypeError, AttributeError, ValueError, KeyError) as exc:
            # Programming / configuration errors — not retryable
            return ExecutionResult(
                step_id=step.id,
                tool=step.tool,
                capability=step.required_capability,
                status="failed",
                artifact_type=step.expected_artifact,
                error=str(exc),
                retryable=False,
                fallback_candidate="" if step.fallback_reason == "preferred_tool_available" else step.preferred_tool,
                next_hint="fix_adapter_or_fallback_tool",
            )
        except Exception as exc:
            # Unknown errors — conservative: not retryable
            return ExecutionResult(
                step_id=step.id,
                tool=step.tool,
                capability=step.required_capability,
                status="failed",
                artifact_type=step.expected_artifact,
                error=str(exc),
                retryable=False,
                fallback_candidate="" if step.fallback_reason == "preferred_tool_available" else step.preferred_tool,
                next_hint="investigate_error",
            )
        if isinstance(raw, ExecutionResult):
            return raw
        if isinstance(raw, Mapping):
            status = str(raw.get("status") or "success")
            artifact_payload = raw.get("artifact", raw.get("artifact_payload"))
            return ExecutionResult(
                step_id=step.id,
                tool=step.tool,
                capability=step.required_capability,
                status=status,
                artifact_type=str(raw.get("artifact_type") or step.expected_artifact),
                artifact_path=str(raw.get("artifact_path") or ""),
                summary=str(raw.get("summary") or ""),
                error=str(raw.get("error") or ""),
                retryable=bool(raw.get("retryable", False)),
                fallback_candidate=str(raw.get("fallback_candidate") or ""),
                next_hint=str(raw.get("next_hint") or "verify_artifact"),
                artifact_payload=artifact_payload,
            )
        return ExecutionResult(
            step_id=step.id,
            tool=step.tool,
            capability=step.required_capability,
            status="success",
            artifact_type=step.expected_artifact,
            summary=str(raw),
            retryable=False,
            next_hint="verify_artifact",
            artifact_payload={"output": str(raw)},
        )
