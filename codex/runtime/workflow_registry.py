from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Iterable

from .models import GoalContract, WorkflowSpec


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]*|[\u4e00-\u9fff]+", re.IGNORECASE)
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _tag_matches(normalized: str, tokens: set[str], tag: str) -> bool:
    return tag in normalized if any("\u4e00" <= character <= "\u9fff" for character in tag) else tag in tokens


class WorkflowRegistry:
    def __init__(self, roots: Iterable[Path] | None = None) -> None:
        default_root = Path(__file__).resolve().parent.parent / "workflows"
        self.roots = tuple(roots or (default_root,))
        self._workflows: dict[str, WorkflowSpec] = {}

    def load(self, *, refresh: bool = False) -> tuple[WorkflowSpec, ...]:
        if self._workflows and not refresh:
            return tuple(self._workflows.values())
        loaded: dict[str, WorkflowSpec] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.toml")):
                payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
                workflow = WorkflowSpec.from_dict(payload)
                self._validate(workflow, path)
                if workflow.workflow_id in loaded:
                    raise ValueError(f"duplicate_workflow_id:{workflow.workflow_id}")
                loaded[workflow.workflow_id] = workflow
        if "generic-adaptive" not in loaded:
            raise ValueError("generic_workflow_missing")
        self._workflows = loaded
        return tuple(loaded.values())

    def _validate(self, workflow: WorkflowSpec, path: Path) -> None:
        if not workflow.workflow_id:
            raise ValueError(f"workflow_id_missing:{path}")
        if not IDENTIFIER_RE.fullmatch(workflow.workflow_id):
            raise ValueError(f"workflow_id_invalid:{workflow.workflow_id}")
        if not workflow.actions:
            raise ValueError(f"workflow_actions_missing:{workflow.workflow_id}")
        action_ids = [action.action_id for action in workflow.actions]
        if any(not action_id for action_id in action_ids):
            raise ValueError(f"workflow_action_id_missing:{workflow.workflow_id}")
        if any(not IDENTIFIER_RE.fullmatch(action_id) for action_id in action_ids):
            raise ValueError(f"workflow_action_id_invalid:{workflow.workflow_id}")
        if len(action_ids) != len(set(action_ids)):
            raise ValueError(f"workflow_duplicate_action:{workflow.workflow_id}")
        known = set(action_ids)
        for action in workflow.actions:
            if not action.required_capabilities:
                raise ValueError(f"workflow_capability_missing:{workflow.workflow_id}:{action.action_id}")
            if not action.expected_artifact:
                raise ValueError(f"workflow_artifact_missing:{workflow.workflow_id}:{action.action_id}")
            unknown = set(action.depends_on) - known
            if unknown:
                raise ValueError(f"workflow_unknown_dependency:{workflow.workflow_id}:{action.action_id}:{sorted(unknown)}")
        self._validate_acyclic(workflow)

    def _validate_acyclic(self, workflow: WorkflowSpec) -> None:
        dependencies = {action.action_id: set(action.depends_on) for action in workflow.actions}
        remaining = set(dependencies)
        while remaining:
            ready = {action_id for action_id in remaining if not (dependencies[action_id] & remaining)}
            if not ready:
                raise ValueError(f"workflow_dependency_cycle:{workflow.workflow_id}")
            remaining -= ready

    def get(self, workflow_id: str) -> WorkflowSpec:
        self.load()
        if workflow_id not in self._workflows:
            raise KeyError(f"workflow_not_found:{workflow_id}")
        return self._workflows[workflow_id]

    def match(self, goal: GoalContract) -> WorkflowSpec:
        return self.match_many(goal, limit=1)[0]

    def match_many(self, goal: GoalContract, *, limit: int = 3) -> tuple[WorkflowSpec, ...]:
        self.load()
        requested = tuple(dict.fromkeys((*goal.workflow_hints, goal.workflow_hint)))
        explicit = tuple(self._workflows[item] for item in requested if item in self._workflows and item != "generic-adaptive")
        if explicit:
            return explicit[: max(1, limit)]
        if goal.workflow_hint == "generic-adaptive":
            return (self._workflows["generic-adaptive"],)
        tokens = set(TOKEN_RE.findall(goal.objective.casefold().replace("_", "-")))
        ranked: list[tuple[int, str, WorkflowSpec]] = []
        for workflow in self._workflows.values():
            if workflow.workflow_id == "generic-adaptive":
                continue
            score = sum(1 for tag in workflow.match_tags if _tag_matches(goal.objective.casefold(), tokens, tag))
            ranked.append((score, workflow.workflow_id, workflow))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        matched = tuple(item[2] for item in ranked if item[0] > 0)
        return matched[: max(1, limit)] or (self._workflows["generic-adaptive"],)
