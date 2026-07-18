from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .models import ActionSpec, EvidenceNode, GoalContract, ToolCallResult
from .security import redact_sensitive


@dataclass(frozen=True)
class VerificationDecision:
    passed: bool
    payload: Mapping[str, Any]
    confidence: float
    reason: str
    parent_ids: tuple[str, ...] = ()


DERIVED_ARTIFACTS = {
    "hypothesis_queue",
    "reproduction_artifact",
    "impact_proof",
    "coverage_report",
    "cleanup_proof",
    "final_report",
}
MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
OUTPUT_CONTRACTS: dict[str, Mapping[str, Any]] = {
    "surface_map": {"any_of": ["targets", "assets", "hosts", "routes", "services", "files", "components", "results"]},
    "hypothesis_queue": {
        "required": ["evidence_refs", "hypotheses"],
        "hypotheses": "non-empty array of {id, statement, priority, evidence_refs, negative_control}",
    },
    "reproduction_artifact": {
        "required": ["reproducible", "evidence_refs", "negative_controls", "side_effects"],
        "reproducible": True,
        "any_of": ["request_response", "commands", "tests", "observations", "results", "transcript"],
    },
    "impact_proof": {
        "required": ["evidence_refs"],
        "one_of": [{"verified": True}, {"measured": True}],
        "any_of": ["impact", "outcomes", "before_after", "observations", "results", "metrics"],
    },
    "coverage_report": {
        "required": ["evidence_refs"],
        "any_of": ["checked", "coverage", "matrix", "metrics"],
        "control_any_of": ["negative_controls", "false_positive_controls", "excluded"],
    },
    "cleanup_proof": {
        "required": ["evidence_refs", "verified", "outstanding_changes"],
        "verified": True,
        "outstanding_changes": [],
        "any_of": ["actions", "rollback", "results", "checks"],
    },
    "final_report": {
        "required": ["evidence_refs", "goal_result", "criteria"],
        "goal_result": ["achieved", "not_achieved", "partial"],
        "criteria": "exact GoalContract criteria with status and evidence_refs",
        "any_of": ["report", "findings", "summary"],
    },
}

class SemanticVerifier:
    @staticmethod
    def output_contract(verifier: str) -> Mapping[str, Any]:
        return dict(OUTPUT_CONTRACTS.get(verifier, {"any_of": ["results", "output", "findings", "observations"]}))

    @classmethod
    def _redact(cls, value: Any, key: str = "") -> Any:
        return redact_sensitive(value, key)

    def normalize_output(self, output: Any) -> Mapping[str, Any]:
        if isinstance(output, Mapping):
            structured = output.get("structuredContent")
            if isinstance(structured, Mapping):
                return self._redact(dict(structured))
            if "artifact" in output and isinstance(output.get("artifact"), Mapping):
                return self._redact(dict(output["artifact"]))
            content = output.get("content")
            if isinstance(content, list):
                texts = [str(item.get("text")) for item in content if isinstance(item, Mapping) and item.get("type") == "text"]
                joined = "\n".join(texts).strip()
                if joined:
                    try:
                        decoded = json.loads(joined)
                    except json.JSONDecodeError:
                        return self._redact({"output": joined, "raw_mcp": dict(output)})
                    if isinstance(decoded, Mapping):
                        return self._redact(dict(decoded))
                    return self._redact({"output": decoded, "raw_mcp": dict(output)})
            return self._redact(dict(output))
        if isinstance(output, str):
            stripped = output.strip()
            if not stripped:
                return {}
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                return self._redact({"output": stripped})
            return self._redact(dict(decoded) if isinstance(decoded, Mapping) else {"output": decoded})
        if output is None:
            return {}
        return self._redact({"output": output})

    @staticmethod
    def _nonempty(payload: Mapping[str, Any], keys: Sequence[str]) -> bool:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (str, list, tuple, dict, set)) and len(value) > 0:
                return True
            if value not in (None, False, "", [], {}, ()):
                return True
        return False

    @staticmethod
    def _evidence_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
        raw = payload.get("evidence_refs")
        if not isinstance(raw, list):
            return ()
        return tuple(dict.fromkeys(str(item) for item in raw if str(item).strip()))

    def _validate_schema(self, verifier: str, payload: Mapping[str, Any]) -> tuple[bool, str]:
        if verifier == "surface_map":
            passed = self._nonempty(
                payload,
                ("targets", "assets", "hosts", "addresses", "routes", "services", "files", "components", "surface", "results", "output"),
            )
            return passed, "surface_evidence_missing" if not passed else "surface_verified"
        if verifier == "hypothesis_queue":
            hypotheses = payload.get("hypotheses")
            passed = (
                isinstance(hypotheses, list)
                and bool(hypotheses)
                and all(
                    isinstance(item, Mapping)
                    and bool(item.get("id"))
                    and bool(item.get("statement"))
                    and item.get("priority") in {"critical", "high", "medium", "low"}
                    and isinstance(item.get("evidence_refs"), list)
                    and bool(item.get("evidence_refs"))
                    and bool(item.get("negative_control"))
                    for item in hypotheses
                )
            )
            return passed, "hypotheses_missing" if not passed else "hypotheses_verified"
        if verifier == "reproduction_artifact":
            reproducible = payload.get("reproducible") is True
            concrete = self._nonempty(payload, ("request_response", "commands", "tests", "observations", "results", "transcript"))
            controls = self._nonempty(payload, ("negative_controls", "false_positive_controls"))
            side_effects_declared = "side_effects" in payload
            passed = reproducible and concrete and controls and side_effects_declared
            return passed, "reproduction_requires_concrete_replay" if not passed else "reproduction_verified"
        if verifier == "impact_proof":
            measured = payload.get("verified") is True or payload.get("measured") is True
            concrete = self._nonempty(payload, ("impact", "outcomes", "before_after", "observations", "results", "metrics"))
            passed = measured and concrete
            return passed, "impact_requires_measured_outcome" if not passed else "impact_verified"
        if verifier == "coverage_report":
            checked = self._nonempty(payload, ("checked", "coverage", "matrix", "metrics"))
            controls = self._nonempty(payload, ("negative_controls", "false_positive_controls", "excluded"))
            passed = checked and controls
            return passed, "coverage_requires_checks_and_negative_controls" if not passed else "coverage_verified"
        if verifier == "cleanup_proof":
            actions = self._nonempty(payload, ("actions", "rollback", "results", "checks"))
            verified = payload.get("verified") is True and not payload.get("outstanding_changes")
            passed = actions and verified
            return passed, "cleanup_requires_verified_rollback" if not passed else "cleanup_verified"
        if verifier == "final_report":
            report = self._nonempty(payload, ("report", "findings", "summary"))
            goal_result = payload.get("goal_result") in {"achieved", "not_achieved", "partial"}
            criteria = payload.get("criteria")
            criteria_valid = (
                isinstance(criteria, list)
                and bool(criteria)
                and all(
                    isinstance(item, Mapping)
                    and bool(item.get("criterion_id"))
                    and item.get("status") in {"achieved", "not_achieved"}
                    and isinstance(item.get("evidence_refs"), list)
                    and bool(item.get("evidence_refs"))
                    for item in criteria
                )
            )
            passed = report and goal_result and criteria_valid
            return passed, "report_requires_goal_criteria_and_findings" if not passed else "report_verified"
        passed = self._nonempty(payload, ("results", "output", "findings", "observations"))
        return passed, "generic_evidence_missing" if not passed else "generic_verified"

    def verify(
        self,
        *,
        action: ActionSpec,
        result: ToolCallResult,
        goal: GoalContract,
        available_evidence: Sequence[EvidenceNode],
    ) -> VerificationDecision:
        if result.status != "success":
            return VerificationDecision(False, {}, 0.0, result.error or "tool_call_failed")
        payload = self.normalize_output(result.output)
        if not payload:
            return VerificationDecision(False, {}, 0.0, "empty_tool_output")
        serialized_size = len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
        if serialized_size > MAX_EVIDENCE_BYTES:
            return VerificationDecision(False, {}, 0.0, "evidence_payload_too_large")
        declared_artifact = str(payload.get("artifact_type") or payload.get("kind") or "")
        if declared_artifact and declared_artifact != action.expected_artifact:
            return VerificationDecision(False, payload, 0.0, "artifact_type_mismatch")
        declared_target = str(payload.get("target") or "")
        if declared_target and goal.targets and declared_target not in goal.targets:
            return VerificationDecision(False, payload, 0.0, "evidence_target_mismatch")
        try:
            confidence = float(payload.get("confidence", 1.0))
        except (TypeError, ValueError):
            return VerificationDecision(False, payload, 0.0, "invalid_confidence")
        confidence = max(0.0, min(1.0, confidence))
        if confidence < 0.7:
            return VerificationDecision(False, payload, confidence, "confidence_below_threshold")
        passed, reason = self._validate_schema(action.verifier, payload)
        if not passed:
            return VerificationDecision(False, payload, confidence, reason)
        evidence_by_id = {node.evidence_id: node for node in available_evidence}
        parent_ids = self._evidence_refs(payload)
        if action.expected_artifact in DERIVED_ARTIFACTS:
            if not parent_ids:
                return VerificationDecision(False, payload, confidence, "derived_evidence_requires_parents")
            if not set(parent_ids).issubset(evidence_by_id):
                return VerificationDecision(False, payload, confidence, "unknown_evidence_reference")
            if any(not evidence_by_id[parent_id].verified for parent_id in parent_ids):
                return VerificationDecision(False, payload, confidence, "unverified_evidence_reference")
        if action.expected_artifact == "final_report":
            expected = {item.criterion_id: item for item in goal.success_criteria}
            reported = {
                str(item.get("criterion_id") or ""): item
                for item in payload.get("criteria", ())
                if isinstance(item, Mapping)
            }
            if set(reported) != set(expected):
                return VerificationDecision(False, payload, confidence, "goal_criteria_mismatch")
            for criterion_id, criterion in expected.items():
                result_item = reported[criterion_id]
                refs = tuple(str(item) for item in result_item.get("evidence_refs", ()) if str(item))
                if not refs or not set(refs).issubset(evidence_by_id):
                    return VerificationDecision(False, payload, confidence, "goal_criterion_evidence_invalid")
                scoped_nodes = [evidence_by_id[item] for item in refs]
                if criterion.target and any(node.target != criterion.target for node in scoped_nodes):
                    return VerificationDecision(False, payload, confidence, "goal_criterion_target_mismatch")
                if criterion.workflow_id and (
                    len(goal.workflow_hints) > 1 or goal.workflow_hint != criterion.workflow_id
                ):
                    prefix = f"{criterion.workflow_id}__"
                    scoped_nodes = [node for node in scoped_nodes if node.action_id.startswith(prefix)]
                scoped_types = {node.artifact_type for node in scoped_nodes}
                required = {"reproduction_artifact", "impact_proof", "coverage_report", "cleanup_proof"}
                achieved = result_item.get("status") == "achieved"
                if achieved != required.issubset(scoped_types):
                    return VerificationDecision(False, payload, confidence, "goal_criterion_status_unproven")
            if payload.get("goal_result") == "achieved" and any(
                item.get("status") != "achieved" for item in reported.values()
            ):
                return VerificationDecision(False, payload, confidence, "goal_result_exceeds_criteria")
        return VerificationDecision(True, payload, confidence, reason, parent_ids)
