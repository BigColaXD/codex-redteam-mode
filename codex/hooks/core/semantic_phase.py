from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Iterable

PHASE_EXAMPLES: dict[str, list[str]] = {
    "web": [
        "trace one exploit path through requests parameters session state and hidden endpoints",
        "review burp traffic and determine whether this web issue is exploitable",
        "analyze this login flow token reuse and authorization boundary",
        "\u68b3\u7406\u8fd9\u4e2a\u767b\u5f55\u63a5\u53e3\u548c\u9274\u6743\u8fb9\u754c\uff0c\u5224\u65ad token \u662f\u5426\u53ef\u590d\u7528",
        "\u57fa\u4e8e burp \u6d41\u91cf\u5206\u6790\u4e00\u6761\u53ef\u9a8c\u8bc1\u7684 web \u5229\u7528\u8def\u5f84",
    ],
    "ad": [
        "reason about kerberos delegation acl abuse and lateral movement in active directory",
        "identify the next quiet step in a windows domain attack chain",
        "\u5206\u6790\u57df\u5185\u59d4\u6d3e\u3001\u7968\u636e\u4e0e ACL \u5173\u7cfb\uff0c\u627e\u4e00\u6761\u4f4e\u566a\u58f0\u63a8\u8fdb\u8def\u5f84",
    ],
    "postex": [
        "triage a foothold for privilege escalation credential reuse and next-hop value",
        "evaluate what to do after code execution on a host",
        "\u5df2\u7ecf\u62ff\u5230 shell\uff0c\u4e0b\u4e00\u6b65\u5e94\u8be5\u5982\u4f55\u505a\u4e3b\u673a\u5206\u8bca\u3001\u63d0\u6743\u548c\u6a2a\u5411\u51c6\u5907",
    ],
    "reverse": [
        "recover the execution chain of a binary loader or malware sample",
        "analyze unpacking configuration extraction process launch sequence and binary logic",
        "\u8fd9\u4e2a\u7a0b\u5e8f\u4f1a\u91ca\u653e\u8d44\u6e90\u5e76\u62c9\u8d77\u5b50\u8fdb\u7a0b\uff0c\u5e2e\u6211\u68b3\u7406\u6267\u884c\u94fe",
    ],
    "code-audit": [
        "trace one controllable input to a dangerous sink across handlers middleware and trust boundaries",
        "review source code for auth permission logic hidden trust shortcuts and a precise proof path",
        "\u4ece\u5165\u53e3\u4e00\u8def\u8ffd\u5230\u5371\u9669\u51fd\u6570\uff0c\u770b\u770b\u6743\u9650\u8fb9\u754c\u54ea\u91cc\u5931\u5b88",
    ],
    "payload": [
        "choose payload shape launcher format staged versus stageless tradeoffs and delivery constraints",
        "compare delivery formats and operator tradeoffs for an implant or launcher",
        "\u5e2e\u6211\u5728 staged \u548c stageless \u4e4b\u95f4\u505a\u53d6\u820d\u5e76\u8bf4\u660e\u7ea6\u675f\u6761\u4ef6",
    ],
    "evasion": [
        "plan av edr waf or sandbox bypass techniques with low-noise tradeoffs",
        "evaluate defender bypass options and operational constraints",
        "\u8bc4\u4f30\u8fd9\u4e2a WAF/403 \u573a\u666f\u4e0b\u7684\u6700\u5c0f\u9a8c\u8bc1\u7ed5\u8fc7\u8def\u5f84",
    ],
    "cloud": [
        "analyze aws iam role assumption privilege boundaries and metadata exposure",
        "review cloud identity paths and abuse opportunities in the control plane",
        "\u5206\u6790 AWS IAM \u6743\u9650\u3001\u5143\u6570\u636e\u4e0e\u51ed\u8bc1\u590d\u7528\u8def\u5f84",
    ],
    "container": [
        "reason about kubernetes pod escape hostpath abuse and cluster privilege boundaries",
        "review container breakout paths and namespace isolation issues",
        "\u5206\u6790\u5bb9\u5668\u9003\u9038\u548c kubernetes \u96c6\u7fa4\u6743\u9650\u8fb9\u754c",
    ],
    "network": [
        "assess request smuggling websocket or protocol parsing issues from packet traces",
        "reason about dns rebinding and protocol attack paths",
        "\u57fa\u4e8e\u6293\u5305\u548c\u534f\u8bae\u884c\u4e3a\u5206\u6790\u8bf7\u6c42\u8d70\u79c1\u6216\u534f\u8bae\u653b\u51fb\u8def\u5f84",
    ],
    "crypto": [
        "analyze rsa hash or symmetric cipher weaknesses and attack conditions",
        "review the challenge from a crypto attack perspective",
        "\u4ece\u5bc6\u7801\u5b66\u89d2\u5ea6\u5206\u6790 RSA\u3001\u54c8\u5e0c\u6216\u5bf9\u79f0\u52a0\u5bc6\u7684\u5229\u7528\u6761\u4ef6",
    ],
    "mobile": [
        "analyze an android apk or ios ipa for pinning bypass and mobile attack surface",
        "review a mobile application from frida objection and ssl pinning angles",
        "\u5206\u6790\u5b89\u5353\u6216 iOS \u5e94\u7528\u7684\u6293\u5305\u3001\u8bc1\u4e66\u9501\u5b9a\u4e0e\u79fb\u52a8\u7aef\u653b\u51fb\u9762",
    ],
    "jailbreak": [
        "evaluate a model jailbreak prompt instruction hierarchy refusal behavior and regression bank",
        "analyze prompt injection unrestricted mode guardrail bypass and model-specific instruction switching",
        "\u5206\u6790\u6a21\u578b\u8d8a\u72f1\u63d0\u793a\u8bcd\u3001\u6307\u4ee4\u4f18\u5148\u7ea7\u3001\u62d2\u7b54\u884c\u4e3a\u548c\u56de\u5f52\u6d4b\u8bd5",
        "\u5b9e\u73b0 Codex \u5728\u5207\u6362\u6a21\u578b\u540e\u81ea\u52a8\u5207\u6362\u5bf9\u5e94\u7684\u7834\u7532\u6307\u4ee4",
    ],
}

TOKEN_RE = re.compile(r"[a-z0-9_./-]+|[\u4e00-\u9fff]")


def _normalize(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _char_ngrams(token: str, n: int = 3) -> Iterable[str]:
    if len(token) <= n:
        yield token
        return
    for i in range(len(token) - n + 1):
        yield token[i : i + n]


def _tokenize(text: str) -> list[str]:
    normalized = _normalize(text)
    pieces = TOKEN_RE.findall(normalized)
    tokens: list[str] = []
    for piece in pieces:
        if re.fullmatch(r"[\u4e00-\u9fff]", piece):
            tokens.append(piece)
            continue
        tokens.append(piece)
        tokens.extend(_char_ngrams(piece))
    return tokens


def _vectorize(text: str) -> Counter[str]:
    return Counter(_tokenize(text))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b.get(k, 0) for k in a)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


@lru_cache(maxsize=1)
def _phase_prototypes() -> dict[str, Counter[str]]:
    return {phase: _vectorize(" ".join(examples)) for phase, examples in PHASE_EXAMPLES.items()}


def classify_phase_semantically(prompt: str) -> tuple[str | None, float]:
    query = _vectorize(prompt)
    best_phase: str | None = None
    best_score = 0.0
    for phase, proto in _phase_prototypes().items():
        score = _cosine(query, proto)
        if score > best_score:
            best_score = score
            best_phase = phase
    return (best_phase, best_score)
