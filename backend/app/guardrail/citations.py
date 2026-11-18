"""输出治理（M2-08）：流式引用过滤 + 免责声明。

流式场景下「先发 token，再校验引用」是行不通的：``[9]`` 已经出现在用户屏幕上了，
事后删不掉。所以这里做的是**流式引用闸门**：

- 保留尾部可能还没写完的角标（``[``、``[1``），等下一块 token 到齐再判断；
- 完整的 ``[n]`` 如果不在本次上下文范围内，直接丢弃（不破坏句子语义）；
- 流结束时把残留的半截角标清掉。

另一个刻意的取舍：**不重排引用序号**。``sanitize_citations`` 会重排成连续序号，
但那要求同时改写已经发出去的正文。这里保留原序号（``[2]``、``[4]`` 就还是 2、4），
保证「正文角标 ↔ citations」在流式下永远对得上。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DISCLAIMER = "本回答基于药品说明书与企业资料整理，具体用药请遵医嘱；如症状持续或加重，请及时就医。"

# 绑定这些知识库的 Agent 必须带免责声明（药品械字号相关内容，合规硬要求）
DISCLAIMER_KB_CODES = frozenset({"kb_drug_manual"})

_MARK = re.compile(r"\[(\d{1,2})\]")
_TAIL = re.compile(r"\[(\d{0,2})$")


def needs_disclaimer(agent: Any) -> bool:
    """按 Agent 绑定的知识库判断是否需要免责声明。"""
    codes = set(getattr(agent, "kb_codes", None) or [])
    return bool(codes & DISCLAIMER_KB_CODES)


class CitationStreamFilter:
    """流式引用闸门：只放行本次上下文里真实存在的 ``[n]``。"""

    def __init__(self, valid_indices: set[int]) -> None:
        self.valid = set(valid_indices)
        self.buffer = ""
        self.used: set[int] = set()
        self.dropped: list[int] = []

    def feed(self, text: str) -> str:
        self.buffer += text or ""
        hold = _TAIL.search(self.buffer)
        cut = hold.start() if hold else len(self.buffer)
        head, self.buffer = self.buffer[:cut], self.buffer[cut:]
        return self._clean(head)

    def flush(self) -> str:
        tail, self.buffer = self.buffer, ""
        if not tail:
            return ""
        # 只有「[」「[1」「[12」这种半截角标才丢，普通文本（含 markdown 链接）照发
        if re.fullmatch(r"\[\d{1,2}", tail):
            return ""
        return self._clean(tail)

    def _clean(self, text: str) -> str:
        if not text:
            return ""

        def repl(match: re.Match[str]) -> str:
            number = int(match.group(1))
            if number in self.valid:
                self.used.add(number)
                return match.group(0)
            self.dropped.append(number)
            return ""

        return _MARK.sub(repl, text)


@dataclass(slots=True)
class GuardrailOutcome:
    text: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    passed: bool = True


def select_used_citations(
    text: str, citations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """只保留正文真正引用到的 citation，且**保持原序号**（见模块注释）。"""
    used = {int(match.group(1)) for match in _MARK.finditer(text)}
    return [citation for citation in citations if citation.get("index") in used]


def append_disclaimer(text: str) -> tuple[str, bool]:
    if DISCLAIMER in text:
        return text, False
    body = text.rstrip()
    if not body:
        return text, False
    return f"{body}\n\n> {DISCLAIMER}", True


def finalize(
    text: str,
    citations: list[dict[str, Any]],
    *,
    need_disclaimer: bool = False,
) -> GuardrailOutcome:
    """收尾治理：裁引用 + 补免责声明。返回的 ``flags`` 会进 SSE 的 ``guardrail``。"""
    flags: list[str] = []
    used = select_used_citations(text, citations)
    if citations and not used:
        flags.append("citations_unused")
    if len(used) < len(citations):
        flags.append("citations_pruned")

    if need_disclaimer:
        text, injected = append_disclaimer(text)
        if injected:
            flags.append("disclaimer_injected")

    return GuardrailOutcome(text=text, citations=used, flags=flags, passed=True)
