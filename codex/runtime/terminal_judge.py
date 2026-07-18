from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .models import EvidenceNode, GoalContract, OperationState, SuccessPredicate, TerminalDecision, WorkflowSpec


class TerminalJudge:
    def evaluate(
        self,
        *,
        state: OperationState,
        goal: GoalContract,
        workflow: WorkflowSpec,
        evidence: Sequence[EvidenceNode],
    ) -> TerminalDecision:
        predicates = tuple(workflow.terminal_predicates) + tuple(goal.success_predicates)
        satisfied: list[str] = []
        missing: list[str] = []
        evidence_by_type: dict[str, list[EvidenceNode]] = {}
        for node in evidence:
            if node.verified:
                evidence_by_type.setdefault(node.artifact_type, []).append(node)

        for predicate in predicates:
            key = self._predicate_key(predicate)
            if self._evaluate_predicate(predicate, state, workflow, evidence_by_type):
                satisfied.append(key)
            else:
                missing.append(key)

        for artifact_type in workflow.required_artifacts:
            if not evidence_by_type.get(artifact_type):
                missing.append(f"required_artifact:{artifact_type}")

        evidence_by_action: dict[str, list[EvidenceNode]] = {}
        for node in evidence:
            if node.verified:
                evidence_by_action.setdefault(node.action_id, []).append(node)
        for action in workflow.actions:
            if action.optional:
                continue
            action_nodes = [
                node
                for node in evidence_by_action.get(action.action_id, ())
                if node.artifact_type == action.expected_artifact
            ]
            if state.action_status.get(action.action_id) == "completed" and not action_nodes:
                missing.append(f"required_action_evidence:{action.action_id}")
                continue
            for dependency in action.depends_on:
                dependency_ids = {node.evidence_id for node in evidence_by_action.get(dependency, ())}
                if dependency_ids and action_nodes and not any(
                    dependency_ids.intersection(node.parent_ids) for node in action_nodes
                ):
                    missing.append(f"action_lineage:{action.action_id}:{dependency}")

        final_reports = evidence_by_type.get("final_report", ())
        if final_reports:
            achieved = any(
                isinstance(node.payload, Mapping) and node.payload.get("goal_result") == "achieved"
                for node in final_reports
            )
            if not achieved:
                missing.append("final_report.goal_result:achieved")
            if not self._report_lineage_complete(final_reports, evidence):
                missing.append("final_report_lineage_complete")
            if not self._goal_criteria_complete(final_reports, goal, evidence):
                missing.append("goal_criteria_complete")

        lineage_error = self._lineage_error(evidence)
        if lineage_error:
            missing.append(lineage_error)
        if not goal.targets:
            missing.append("goal_targets_present")
        else:
            covered_targets = {node.target for node in evidence if node.verified and node.target}
            for target in goal.targets:
                if target not in covered_targets:
                    missing.append(f"target_evidence:{target}")

        if missing:
            return TerminalDecision(
                terminal=False,
                success=False,
                reason="goal_predicates_pending",
                satisfied=tuple(dict.fromkeys(satisfied)),
                missing=tuple(dict.fromkeys(missing)),
            )
        return TerminalDecision(
            terminal=True,
            success=True,
            reason="goal_contract_satisfied",
            satisfied=tuple(dict.fromkeys(satisfied)),
        )

    @staticmethod
    def _predicate_key(predicate: SuccessPredicate) -> str:
        return f"{predicate.kind}:{predicate.subject}" if predicate.subject else predicate.kind

    def _evaluate_predicate(
        self,
        predicate: SuccessPredicate,
        state: OperationState,
        workflow: WorkflowSpec,
        evidence_by_type: Mapping[str, Sequence[EvidenceNode]],
    ) -> bool:
        if predicate.kind == "workflow_actions_complete":
            required = [action for action in workflow.actions if not action.optional]
            return all(state.action_status.get(action.action_id) == "completed" for action in required)
        if predicate.kind == "artifact_verified":
            return bool(evidence_by_type.get(predicate.subject))
        if predicate.kind == "artifact_count":
            count = len(evidence_by_type.get(predicate.subject, ()))
            return self._compare(count, predicate.operator, predicate.value)
        if predicate.kind == "artifact_field":
            artifact_type, separator, field_name = predicate.subject.partition(".")
            if not separator:
                return False
            for node in evidence_by_type.get(artifact_type, ()):
                if isinstance(node.payload, Mapping) and self._compare(node.payload.get(field_name), predicate.operator, predicate.value):
                    return True
            return False
        return False

    @staticmethod
    def _compare(actual: Any, operator: str, expected: Any) -> bool:
        if operator == "exists":
            return actual not in (None, False, "", [], {}, ())
        if operator == "eq":
            return actual == expected
        if operator == "ne":
            return actual != expected
        try:
            if operator == "gte":
                return actual >= expected
            if operator == "gt":
                return actual > expected
            if operator == "lte":
                return actual <= expected
            if operator == "lt":
                return actual < expected
        except TypeError:
            return False
        if operator == "contains":
            try:
                return expected in actual
            except TypeError:
                return False
        return False

    @staticmethod
    def _lineage_error(evidence: Sequence[EvidenceNode]) -> str:
        by_id = {node.evidence_id: node for node in evidence}
        for node in evidence:
            if any(parent_id not in by_id for parent_id in node.parent_ids):
                return "evidence_lineage_missing_parent"
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(evidence_id: str) -> bool:
            if evidence_id in visiting:
                return False
            if evidence_id in visited:
                return True
            visiting.add(evidence_id)
            for parent_id in by_id[evidence_id].parent_ids:
                if not visit(parent_id):
                    return False
            visiting.remove(evidence_id)
            visited.add(evidence_id)
            return True

        for evidence_id in by_id:
            if not visit(evidence_id):
                return "evidence_lineage_cycle"
        return ""

    @staticmethod
    def _report_lineage_complete(final_reports: Sequence[EvidenceNode], evidence: Sequence[EvidenceNode]) -> bool:
        by_id = {node.evidence_id: node for node in evidence}
        required = {"reproduction_artifact", "impact_proof", "coverage_report", "cleanup_proof"}
        for report in final_reports:
            stack = list(report.parent_ids)
            visited: set[str] = set()
            artifact_types: set[str] = set()
            while stack:
                evidence_id = stack.pop()
                if evidence_id in visited or evidence_id not in by_id:
                    continue
                visited.add(evidence_id)
                node = by_id[evidence_id]
                artifact_types.add(node.artifact_type)
                stack.extend(node.parent_ids)
            if required.issubset(artifact_types):
                return True
        return False

    @staticmethod
    def _goal_criteria_complete(
        final_reports: Sequence[EvidenceNode],
        goal: GoalContract,
        evidence: Sequence[EvidenceNode],
    ) -> bool:
        expected = {criterion.criterion_id: criterion for criterion in goal.success_criteria}
        by_id = {node.evidence_id: node for node in evidence if node.verified}
        required = {"reproduction_artifact", "impact_proof", "coverage_report", "cleanup_proof"}
        for report in final_reports:
            if not isinstance(report.payload, Mapping):
                continue
            reported = {
                str(item.get("criterion_id") or ""): item
                for item in report.payload.get("criteria", ())
                if isinstance(item, Mapping)
            }
            if not expected or set(reported) != set(expected):
                continue
            valid = True
            for criterion_id, criterion in expected.items():
                item = reported[criterion_id]
                refs = [str(value) for value in item.get("evidence_refs", ()) if str(value) in by_id]
                nodes = [by_id[value] for value in refs]
                if criterion.target and any(node.target != criterion.target for node in nodes):
                    valid = False
                    break
                if criterion.workflow_id and (
                    len(goal.workflow_hints) > 1 or goal.workflow_hint != criterion.workflow_id
                ):
                    prefix = f"{criterion.workflow_id}__"
                    nodes = [node for node in nodes if node.action_id.startswith(prefix)]
                if item.get("status") != "achieved" or not required.issubset({node.artifact_type for node in nodes}):
                    valid = False
                    break
            if valid:
                return True
        return False
