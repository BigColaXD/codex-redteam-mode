from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from .models import ActionSpec, GoalContract, SuccessPredicate, WorkflowSpec
from .workflow_registry import WorkflowRegistry


class AdaptivePlanner:
    def __init__(self, *, max_domains: int = 7, max_hypothesis_branches: int = 4) -> None:
        self.max_domains = max(1, min(7, int(max_domains)))
        self.max_hypothesis_branches = max(1, min(8, int(max_hypothesis_branches)))

    def plan(self, goal: GoalContract, registry: WorkflowRegistry) -> WorkflowSpec:
        workflows = registry.match_many(goal, limit=self.max_domains)
        return workflows[0] if len(workflows) == 1 else self.compose(workflows)

    def compose(self, workflows: tuple[WorkflowSpec, ...]) -> WorkflowSpec:
        actions: list[ActionSpec] = []
        report_dependencies: list[str] = []
        required_artifacts: list[str] = []
        match_tags: list[str] = []

        for workflow in workflows:
            prefix = workflow.workflow_id
            included = tuple(action for action in workflow.actions if action.expected_artifact != "final_report")
            id_map = {action.action_id: f"{prefix}__{action.action_id}" for action in included}
            for action in included:
                actions.append(
                    replace(
                        action,
                        action_id=id_map[action.action_id],
                        name=f"[{workflow.name}] {action.name}",
                        depends_on=tuple(id_map[item] for item in action.depends_on if item in id_map),
                        attack_tags=tuple(dict.fromkeys((*action.attack_tags, workflow.workflow_id))),
                    )
                )
            terminal_actions = [
                id_map[action.action_id]
                for action in included
                if not any(action.action_id in candidate.depends_on for candidate in included)
            ]
            report_dependencies.extend(terminal_actions)
            required_artifacts.extend(item for item in workflow.required_artifacts if item != "final_report")
            match_tags.extend(workflow.match_tags)

        actions.append(
            ActionSpec(
                action_id="composite-report",
                name="Build the cross-domain evidence report",
                required_capabilities=("report_generation", "reasoning"),
                expected_artifact="final_report",
                verifier="final_report",
                depends_on=tuple(dict.fromkeys(report_dependencies)),
                risk="safe",
            )
        )
        workflow_ids = tuple(workflow.workflow_id for workflow in workflows)
        return WorkflowSpec(
            workflow_id=f"composite-{'-'.join(workflow_ids)}"[:128],
            version=max(workflow.version for workflow in workflows),
            name="Cross-domain adaptive operation",
            description=f"Composed execution across: {', '.join(workflow_ids)}",
            match_tags=tuple(dict.fromkeys(match_tags)),
            actions=tuple(actions),
            terminal_predicates=(
                SuccessPredicate(kind="workflow_actions_complete", subject="required"),
                SuccessPredicate(kind="artifact_verified", subject="reproduction_artifact"),
                SuccessPredicate(kind="artifact_verified", subject="impact_proof"),
                SuccessPredicate(kind="artifact_verified", subject="cleanup_proof"),
                SuccessPredicate(kind="artifact_verified", subject="final_report"),
            ),
            required_artifacts=tuple(dict.fromkeys((*required_artifacts, "final_report"))),
        )

    def expand_hypotheses(
        self,
        workflow: WorkflowSpec,
        *,
        hypothesis_action_id: str,
        hypotheses: Sequence[Mapping[str, Any]],
        max_branches: int | None = None,
    ) -> tuple[WorkflowSpec, tuple[str, ...]]:
        branch_limit = self.max_hypothesis_branches if max_branches is None else max(1, int(max_branches))
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        selected = tuple(
            sorted(
                (item for item in hypotheses if isinstance(item, Mapping)),
                key=lambda item: (
                    priority_rank.get(str(item.get("priority") or "").casefold(), 4),
                    str(item.get("id") or ""),
                ),
            )[:branch_limit]
        )
        if not selected:
            return workflow, ()
        direct_validations = tuple(
            action
            for action in workflow.actions
            if hypothesis_action_id in action.depends_on and action.expected_artifact == "reproduction_artifact"
        )
        if not direct_validations:
            return workflow, ()

        actions = list(workflow.actions)
        added_ids: list[str] = []
        report_dependencies: list[str] = []
        for validation in direct_validations:
            validation_index = next(index for index, action in enumerate(actions) if action.action_id == validation.action_id)
            actions[validation_index] = replace(
                validation,
                parameters={**dict(validation.parameters), "hypothesis": dict(selected[0])},
            )
            if len(selected) == 1:
                continue

            branch_ids = {validation.action_id}
            changed = True
            while changed:
                changed = False
                for candidate in workflow.actions:
                    if candidate.expected_artifact == "final_report" or candidate.action_id in branch_ids:
                        continue
                    if any(dependency in branch_ids for dependency in candidate.depends_on):
                        branch_ids.add(candidate.action_id)
                        changed = True
            branch_actions = tuple(action for action in workflow.actions if action.action_id in branch_ids)
            terminal_ids = {
                action.action_id
                for action in branch_actions
                if not any(action.action_id in candidate.depends_on for candidate in branch_actions)
            }
            for branch_index, hypothesis in enumerate(selected[1:], start=2):
                suffix = f"--h{branch_index}"
                id_map = {action.action_id: f"{action.action_id}{suffix}" for action in branch_actions}
                for action in branch_actions:
                    cloned = replace(
                        action,
                        action_id=id_map[action.action_id],
                        name=f"{action.name} [hypothesis {branch_index}]",
                        depends_on=tuple(id_map.get(item, item) for item in action.depends_on),
                        rollback_action=id_map.get(action.rollback_action, action.rollback_action),
                        parameters={**dict(action.parameters), "hypothesis": dict(hypothesis)},
                        attack_tags=tuple(dict.fromkeys((*action.attack_tags, str(hypothesis.get("id") or suffix)))),
                    )
                    actions.append(cloned)
                    added_ids.append(cloned.action_id)
                report_dependencies.extend(id_map[item] for item in terminal_ids)

        if report_dependencies:
            actions = [
                replace(action, depends_on=tuple(dict.fromkeys((*action.depends_on, *report_dependencies))))
                if action.expected_artifact == "final_report"
                else action
                for action in actions
            ]
        if not added_ids and actions == list(workflow.actions):
            return workflow, ()
        expanded = replace(workflow, actions=tuple(actions))
        return expanded, tuple(added_ids)
