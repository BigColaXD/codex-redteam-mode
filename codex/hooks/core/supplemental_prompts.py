from __future__ import annotations

from pathlib import Path


def build_prompt_chain_notice(codex_dir: Path, mode: str = "normal") -> str:
    del codex_dir
    if mode not in {"redteam-light", "redteam-full"}:
        return ""
    return (
        "[redteam-runtime] Compile each objective into GoalContract and one typed WorkflowSpec. "
        "Use redteam_run for durable start, resume, batch execution, and Host Agent observations; attach only "
        "tool-derived evidence and continue without user relay until TerminalJudge proves GoalContract criteria."
    )
