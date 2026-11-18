"""引用与拒答（PRD FR3.6 / FR3.7）。

两件事必须分开做，否则会互相打架：

- **引用校验**：模型偶尔会写出 ``[7]`` 而上下文里只有 5 条。这种"幻觉引用"比不写
  引用更糟——用户点过去发现不存在。所以回答里的每个 ``[n]`` 都要落在 citations
  范围内，越界的标记直接删掉（同时保留文字内容，不破坏语义）。
- **拒答判定**：阈值在检索层就已经判过（``RetrievalResult.refused``），这里只负责
  把"为什么拒答"翻译成用户能看懂的话术，并且**不带任何引用**。
"""

from __future__ import annotations

import re
from typing import Any

from app.rag.base import RetrievalResult, RetrievedChunk

_CITATION_MARK = re.compile(r"\[(\d{1,2})\]")

SNIPPET_CHARS = 160

REFUSAL_TEMPLATES: dict[str, str] = {
    "no_hit": "我没有在相关资料里找到对应内容，为避免误导您，这里不做推测。建议您咨询在线药师或前往正规医院就诊。",
    "low_score": "我能找到的资料与这个问题关联不大，为避免误导您，这里不做推测。建议您咨询在线药师或前往正规医院就诊。",
    "no_permission": "这个问题涉及的内容我暂时无法回答。建议您咨询在线药师或前往正规医院就诊。",
    "no_kb": "知识库尚未就绪，暂时无法检索资料。建议您稍后重试或联系人工客服。",
}


def to_citations(result: RetrievalResult) -> list[dict[str, Any]]:
    """把召回结果转成前端/SSE 用的引用列表，序号与 ``[n]`` 一一对应（从 1 开始）。"""
    citations: list[dict[str, Any]] = []
    for index, chunk in enumerate(result.chunks, start=1):
        citations.append(
            {
                "index": index,
                "doc_id": chunk.doc_id,
                "kb_id": chunk.kb_id,
                "doc_title": chunk.doc_title or chunk.doc_id,
                "section": chunk.section,
                "page": chunk.page,
                "score": round(chunk.score, 4),
                "snippet": _snippet(chunk),
                "url": chunk.source_url,
            }
        )
    return citations


def _snippet(chunk: RetrievedChunk, limit: int = SNIPPET_CHARS) -> str:
    text = " ".join(chunk.content.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def sanitize_citations(answer: str, citations: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """删掉越界的 ``[n]``，并只保留回答里真的被引用过的 citation。

    返回 ``(answer, used_citations)``，其中 ``used_citations`` 的 ``index``
    已重排为连续序号，保证「正文 [n] ↔ citations[n]」在展示层不会错位。
    """
    if not citations:
        return _strip_all_marks(answer), []

    valid = {citation["index"] for citation in citations}
    used: set[int] = set()

    def repl(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if number in valid:
            used.add(number)
            return match.group(0)
        return ""

    cleaned = _CITATION_MARK.sub(repl, answer)
    if not used:
        return cleaned, []

    ordered = [citation for citation in citations if citation["index"] in used]
    remap = {citation["index"]: new_index for new_index, citation in enumerate(ordered, start=1)}
    cleaned = _CITATION_MARK.sub(
        lambda m: f"[{remap[int(m.group(1))]}]" if int(m.group(1)) in remap else "",
        cleaned,
    )
    return cleaned, [
        {**citation, "index": remap[citation["index"]]} for citation in ordered
    ]


def _strip_all_marks(text: str) -> str:
    return _CITATION_MARK.sub("", text)


def refusal_text(reason: str | None) -> str:
    return REFUSAL_TEMPLATES.get(reason or "no_hit", REFUSAL_TEMPLATES["no_hit"])
