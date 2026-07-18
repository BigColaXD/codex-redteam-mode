from __future__ import annotations

from dataclasses import dataclass

try:
    from redteam_state import RedTeamState
except ModuleNotFoundError:  # package import path used by tests/automation
    from hooks.redteam_state import RedTeamState


@dataclass
class IntentDecision:
    intent_type: str
    objective_delta: str = ""
    should_refresh_taskbook: bool = False
    should_verify_now: bool = False


VERIFY_MARKERS = (
    "verify",
    "验证",
    "确认漏洞",
    "确认是否",
    "是不是有效",
    "是否有效",
    "confirm whether",
    "is this valid",
    "有效漏洞",
    "需要什么证据",
)
REVISE_MARKERS = (
    "new objective",
    "新的目标",
    "新目标",
    "只测试",
    "仅测试",
    "only test",
    "revise objective",
)
SUMMARY_MARKERS = ("summarize", "总结", "汇总", "报告", "report")
CONTINUE_MARKERS = ("continue", "继续", "keep digging", "same target", "同一目标")


COLON_CN = "："
PERIOD_CN = "。"
OBJECTIVE_CN = "目标"
ONLY_TEST_MARKERS = ("只测试", "仅测试")


def _normalize(prompt: str) -> str:
    return prompt.strip()


def _looks_like_revise(prompt: str) -> bool:
    lowered = prompt.casefold()
    return any(marker in lowered for marker in REVISE_MARKERS) or COLON_CN in prompt or ":" in prompt


def _extract_revised_objective(prompt: str) -> str:
    text = prompt.strip().strip(PERIOD_CN)
    for marker in (
        "New objective:",
        "new objective:",
        "新的目标：",
        "新的目标:",
        "新目标：",
        "新目标:",
        "Only test ",
        "only test ",
    ):
        if text.startswith(marker):
            return text[len(marker):].strip().strip(PERIOD_CN)
    for marker in ONLY_TEST_MARKERS:
        if marker in text:
            idx = text.index(marker)
            return text[idx:].strip().strip(PERIOD_CN)
    if ":" in text:
        head, tail = text.split(":", 1)
        if "objective" in head.casefold():
            return tail.strip().strip(PERIOD_CN)
    if COLON_CN in text:
        head, tail = text.split(COLON_CN, 1)
        if OBJECTIVE_CN in head:
            return tail.strip().strip(PERIOD_CN)
    return text


def detect_intent(prompt: str, state: RedTeamState) -> IntentDecision:
    text = _normalize(prompt)
    lowered = text.casefold()

    if state.objective == "":
        return IntentDecision(
            intent_type="new",
            objective_delta=text,
            should_refresh_taskbook=True,
        )

    if any(marker in lowered for marker in SUMMARY_MARKERS):
        return IntentDecision(intent_type="summarize")

    if (
        any(marker in lowered for marker in VERIFY_MARKERS)
        and "confirm the callback path" not in lowered
        and "continue tracing" not in lowered
    ):
        return IntentDecision(intent_type="verify", should_verify_now=True)

    if _looks_like_revise(text) and text != state.objective:
        objective = _extract_revised_objective(text)
        if objective and objective != state.objective:
            return IntentDecision(
                intent_type="revise",
                objective_delta=objective,
                should_refresh_taskbook=True,
            )

    if any(marker in lowered for marker in CONTINUE_MARKERS):
        return IntentDecision(intent_type="continue")

    return IntentDecision(intent_type="new", objective_delta=text, should_refresh_taskbook=True)
