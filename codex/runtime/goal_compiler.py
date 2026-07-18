from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import GoalContract, GoalCriterion, SuccessPredicate
from .security import redact_sensitive


URL_RE = re.compile(r"\bhttps?://[^\s<>'\"]+", re.IGNORECASE)
HOST_RE = re.compile(
    r"(?<![\w.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|invalid|test)(?::\d{1,5})?(?![\w.-])",
    re.IGNORECASE,
)
IP_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\d.])")
PATH_RE = re.compile(r"(?<!\w)(?:[A-Za-z]:[\\/]|\.?\.?[\\/])[^\s<>'\"]+")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]*|[\u4e00-\u9fff]+", re.IGNORECASE)
CLAUSE_SPLIT_RE = re.compile(r"\s+(?:and|then|plus)\s+|[;；。]|(?:以及|并且|然后|和)", re.IGNORECASE)


def _matches_marker(normalized: str, tokens: set[str], marker: str) -> bool:
    return marker in normalized if any("\u4e00" <= character <= "\u9fff" for character in marker) else marker in tokens


WORKFLOW_MARKERS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "model-security-assessment",
        frozenset({"jailbreak", "prompt-injection", "prompt", "llm", "模型", "越狱", "提示词", "注入"}),
    ),
    (
        "binary-mobile-analysis",
        frozenset({"apk", "android", "ios", "binary", "firmware", "ida", "jadx", "逆向", "二进制", "固件", "移动端"}),
    ),
    (
        "source-assisted-review",
        frozenset({"source", "repository", "codebase", "code-audit", "source-code", "源码", "代码审计", "仓库"}),
    ),
    (
        "identity-cloud-operation",
        frozenset({"active-directory", "kerberos", "entra", "azure", "aws", "gcp", "iam", "ad", "域", "云", "身份"}),
    ),
    (
        "adversary-emulation",
        frozenset({"emulation", "adversary-emulation", "atomic", "ttp", "purple-team", "对抗模拟", "攻击链", "紫队"}),
    ),
    (
        "web-api-assessment",
        frozenset({"web", "api", "http", "https", "graphql", "sqli", "xss", "ssrf", "xxe", "ssti", "网页", "接口", "网站"}),
    ),
    (
        "external-assessment",
        frozenset({"recon", "domain", "host", "port", "network", "scan", "侦察", "域名", "端口", "网络", "扫描"}),
    ),
)


class GoalCompiler:
    def extract_targets(self, objective: str) -> tuple[str, ...]:
        discovered: list[tuple[int, int, int, str]] = []
        for priority, pattern in enumerate((URL_RE, IP_RE, HOST_RE, PATH_RE)):
            for match in pattern.finditer(objective):
                target = match.group(0).rstrip(".,;:!?)]}，。；：！？）】")
                if target:
                    discovered.append((match.start(), match.start() + len(target), priority, target))
        discovered.sort(key=lambda item: (item[0], item[2], -(item[1] - item[0])))
        candidates: list[str] = []
        occupied: list[tuple[int, int]] = []
        for start, end, _, target in discovered:
            if any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied):
                continue
            if target not in candidates:
                candidates.append(target)
                occupied.append((start, end))
        return tuple(candidates)

    def extract_context_targets(self, context: Mapping[str, Any] | None) -> tuple[str, ...]:
        candidates: list[str] = []
        target_keys = {"target", "targets", "url", "uri", "host", "path", "repository", "repo", "binary", "sample"}

        def visit(value: Any, key: str = "") -> None:
            if isinstance(value, Mapping):
                for item_key, item_value in value.items():
                    visit(item_value, str(item_key).casefold())
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    visit(item, key)
                return
            if not isinstance(value, str) or not value.strip():
                return
            cleaned = value.strip()
            extracted = self.extract_targets(cleaned)
            if key in target_keys and not extracted:
                extracted = (cleaned,)
            for target in extracted:
                if target not in candidates:
                    candidates.append(target)

        visit(context or {})
        return tuple(candidates)

    def workflow_hints(self, objective: str, targets: Sequence[str] = ()) -> tuple[str, ...]:
        normalized = objective.casefold().replace("_", "-")
        tokens = set(TOKEN_RE.findall(normalized))
        hints: list[str] = []
        for workflow_id, markers in WORKFLOW_MARKERS:
            if any(_matches_marker(normalized, tokens, marker) for marker in markers):
                hints.append(workflow_id)
        for target in targets:
            suffix = Path(target).suffix.casefold()
            if suffix in {".apk", ".ipa", ".exe", ".dll", ".so", ".bin", ".elf", ".dylib"}:
                hints.append("binary-mobile-analysis")
            if target.casefold().startswith(("http://", "https://")):
                hints.append("web-api-assessment")
        return tuple(dict.fromkeys(hints)) or ("generic-adaptive",)

    def workflow_hint(self, objective: str, targets: Sequence[str] = ()) -> str:
        return self.workflow_hints(objective, targets)[0]

    def workflow_hints_for_target(self, objective: str, target: str) -> tuple[str, ...]:
        segments = [
            item.strip()
            for item in CLAUSE_SPLIT_RE.split(objective)
            if item.strip()
        ]
        local_context = next((item for item in segments if target in item), objective)
        hints = list(self.workflow_hints(local_context, (target,)))
        normalized = target.casefold()
        suffix = Path(target).suffix.casefold()
        binary_suffixes = {".apk", ".ipa", ".exe", ".dll", ".so", ".bin", ".elf", ".dylib"}
        is_url = normalized.startswith(("http://", "https://"))
        is_local = not is_url and (bool(PATH_RE.search(target)) or Path(target).is_absolute())
        if is_url and suffix not in binary_suffixes:
            hints = [item for item in hints if item not in {"source-assisted-review", "binary-mobile-analysis"}]
        elif is_local and suffix not in binary_suffixes:
            hints = [item for item in hints if item not in {"web-api-assessment", "external-assessment"}]
        elif not is_local and not is_url:
            hints = [item for item in hints if item not in {"source-assisted-review", "binary-mobile-analysis"}]
        return tuple(dict.fromkeys(hints)) or ("generic-adaptive",)

    @staticmethod
    def success_criteria(
        objective: str,
        targets: Sequence[str],
        workflow_hints: Sequence[str],
    ) -> tuple[GoalCriterion, ...]:
        criteria: list[GoalCriterion] = []
        resolved_targets = tuple(targets) or ("",)
        resolved_workflows = tuple(dict.fromkeys(workflow_hints)) or ("generic-adaptive",)
        for target in resolved_targets:
            for workflow_id in resolved_workflows:
                identity = f"{objective}\0{target}\0{workflow_id}"
                criterion_id = f"criterion-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
                scope = f" for {target}" if target else ""
                criteria.append(
                    GoalCriterion(
                        criterion_id=criterion_id,
                        statement=f"Complete the {workflow_id} evidence path{scope}: {objective}",
                        target=target,
                        workflow_id=workflow_id,
                    )
                )
        return tuple(criteria)

    def compile(
        self,
        objective: str,
        *,
        targets: Sequence[str] | None = None,
        workflow_hint: str = "",
        starting_context: Mapping[str, Any] | None = None,
        constraints: Mapping[str, Any] | None = None,
        success_predicates: Sequence[SuccessPredicate | Mapping[str, Any]] = (),
        max_actions: int = 64,
        max_retries_per_action: int = 2,
    ) -> GoalContract:
        cleaned = objective.strip()
        if not cleaned:
            raise ValueError("objective_required")
        resolved_targets = tuple(targets or self.extract_targets(cleaned) or self.extract_context_targets(starting_context))
        explicit_hints = tuple(
            item.strip()
            for item in re.split(r"[,+]", workflow_hint)
            if item.strip()
        )
        resolved_hints = explicit_hints or self.workflow_hints(cleaned, resolved_targets)
        resolved_hint = resolved_hints[0]
        redacted_objective = str(redact_sensitive(cleaned))
        redacted_targets = tuple(str(redact_sensitive(target)) for target in resolved_targets)
        predicates = tuple(
            item if isinstance(item, SuccessPredicate) else SuccessPredicate.from_dict(item)
            for item in success_predicates
        )
        return GoalContract.create(
            objective=redacted_objective,
            targets=redacted_targets,
            workflow_hint=resolved_hint,
            workflow_hints=resolved_hints,
            starting_context=redact_sensitive(dict(starting_context or {})),
            constraints=redact_sensitive(dict(constraints or {})),
            success_criteria=self.success_criteria(redacted_objective, redacted_targets, resolved_hints),
            success_predicates=predicates,
            stop_conditions=("action_budget_exhausted", "explicit_stop_condition", "nonrecoverable_tool_failure"),
            max_actions=max_actions,
            max_retries_per_action=max_retries_per_action,
        )
