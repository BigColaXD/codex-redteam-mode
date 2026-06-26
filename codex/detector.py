# -*- coding: utf-8 -*-
"""Refusal detector for Codex CLI session JSONL files."""

from __future__ import annotations

from typing import Dict, List, Optional


class RefusalDetector:
    """Two-tier refusal detection: strong phrases + weak openers with denial context."""

    STRONG_REFUSAL_PHRASES = [
        # Chinese direct refusals
        "我无法协助",
        "我无法帮助",
        "我不能协助",
        "我不能帮助",
        "我不能提供",
        "我无法提供",
        "我不能生成",
        "我无法生成",
        "我不能执行",
        "我无法执行",
        "我不能继续",
        "我无法继续",
        "我不能做",
        "我无法做",
        "我拒绝",
        "我必须拒绝",
        "无法协助你",
        "无法帮助你",
        "不能协助你",
        "不能帮助你",
        "不能为你提供",
        "无法为你提供",
        "不适合提供",
        "不便提供",
        "不能支持该请求",
        "无法满足该请求",
        "无法完成该请求",
        "这不道德",
        "这是不道德的",
        "这是违法的",
        "这可能违法",
        "可能造成伤害",
        "可能被滥用",
        "超出了我的能力范围",
        "超出我的职责",
        "不符合安全规范",
        "不符合使用政策",
        "违反使用政策",
        "违反安全政策",
        # English direct refusals
        "i cannot assist",
        "i can't assist",
        "i'm unable to assist",
        "i cannot help",
        "i can't help",
        "i'm unable to help",
        "i cannot provide",
        "i can't provide",
        "i'm unable to provide",
        "i cannot generate",
        "i can't generate",
        "i cannot execute",
        "i can't execute",
        "i must decline",
        "i must refuse",
        "against my guidelines",
        "against my policy",
        "violates my",
        "i won't help",
        "i won't assist",
        "as an ai",
        "as a language model",
        "i apologize, but i",
        "i'm sorry, but i can't",
        "not able to provide",
        "not able to assist",
        "cannot provide",
        "cannot comply",
        "this is illegal",
        "this is unethical",
        "would be harmful",
        "potentially harmful",
        # Soft refusal / moralizing
        "建议你通过合法途径",
        "你需要先获得明确授权",
        "出于安全和法律考虑",
        "作为负责任的ai",
        "作为负责任的 ai",
        "我建议你咨询",
        "我建议不要",
        "这超出了授权范围",
        "这可能违反法律",
        "这可能违反服务条款",
        "i would recommend considering legal",
        "i suggest you consult",
        "you should seek proper authorization",
        "it would be inappropriate",
        "i'm not comfortable",
        "for ethical reasons",
        "for legal reasons",
        "as a responsible ai",
        "i would advise against",
        "this crosses an ethical boundary",
        "protect user",
        "responsible disclosure",
        "ethical hacking",
        "ethical consideration",
        "code of conduct",
        "terms of service",
        "content policy",
        "usage policy",
    ]

    WEAK_REFUSAL_KEYWORDS = [
        # Chinese, only near start and only when paired with denial context
        "抱歉",
        "很抱歉",
        "对不起",
        "不好意思",
        "恐怕我",
        "我无法",
        "我不能",
        "我不可以",
        "我不会",
        "不允许",
        "禁止",
        "不能提供",
        "无法提供",
        "不能帮",
        "无法帮",
        # English, only near start and only when paired with denial context
        "sorry",
        "apologize",
        "i cannot",
        "i can't",
        "i'm unable",
        "unable to",
        "not permitted",
        "not allowed",
        "refuse to",
        "i'm afraid i",
        "unfortunately i",
    ]

    DENIAL_CONTEXT = [
        # Chinese
        "协助",
        "帮助",
        "提供",
        "生成",
        "编写",
        "执行",
        "继续",
        "请求",
        "攻击",
        "利用",
        "漏洞",
        "绕过",
        "爆破",
        "入侵",
        "恶意",
        "违法",
        "不道德",
        "伤害",
        "滥用",
        "安全政策",
        "使用政策",
        "合规",
        # English
        "assist",
        "help",
        "provide",
        "generate",
        "write",
        "execute",
        "continue",
        "request",
        "attack",
        "exploit",
        "bypass",
        "abuse",
        "harm",
        "illegal",
        "unethical",
        "policy",
        "guidelines",
        "not allowed",
        "not permitted",
    ]

    NON_REFUSAL_CONTEXT = [
        "确认这个漏洞",
        "确认是否",
        "需要更多证据",
        "无法确认",
        "不能确认",
        "无法证明",
        "不能证明",
        "尚未确认",
        "证据不足",
        "need more evidence",
        "not confirmed yet",
        "cannot confirm",
        "can't confirm",
        "unable to confirm",
        "insufficient evidence",
    ]

    def __init__(self, custom_keywords: Optional[Dict[str, List[str]]] = None):
        self.custom_keywords: Dict[str, List[str]] = {}
        if custom_keywords:
            for lang, words in custom_keywords.items():
                self.custom_keywords[lang] = list(words)

    def detect(self, content: str) -> bool:
        if not content:
            return False

        content_lower = content.lower()

        for phrase in self.STRONG_REFUSAL_PHRASES:
            if phrase in content_lower:
                return True

        if not any(marker in content_lower for marker in self.NON_REFUSAL_CONTEXT):
            head = content_lower[:220]
            has_denial_context = any(marker in content_lower for marker in self.DENIAL_CONTEXT)
            for keyword in self.WEAK_REFUSAL_KEYWORDS:
                if keyword in head and has_denial_context:
                    return True

        for lang_keywords in self.custom_keywords.values():
            for keyword in lang_keywords:
                if keyword.lower() in content_lower:
                    return True

        return False
