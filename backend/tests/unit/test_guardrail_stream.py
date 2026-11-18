"""流式引用闸门与免责声明（M2-08）。

流式下「先发后校验」不成立，所以这里测的是闸门的边界行为：
半截角标要hold住、非法角标要丢、合法角标要留、结束要清残留。
"""

from __future__ import annotations

from app.agent.registry import AgentConfig
from app.guardrail.citations import (
    DISCLAIMER,
    CitationStreamFilter,
    finalize,
    needs_disclaimer,
    select_used_citations,
)


def _feed_all(filter_: CitationStreamFilter, pieces: list[str]) -> str:
    out = []
    for piece in pieces:
        out.append(filter_.feed(piece))
    out.append(filter_.flush())
    return "".join(out)


def test_valid_marker_passes():
    guard = CitationStreamFilter({1, 2})
    assert _feed_all(guard, ["孕妇禁用[1]。"]) == "孕妇禁用[1]。"
    assert guard.used == {1}


def test_fake_marker_is_dropped():
    guard = CitationStreamFilter({1, 2})
    text = _feed_all(guard, ["依据说明书[9]，建议"])
    assert text == "依据说明书，建议"
    assert guard.dropped == [9]


def test_partial_marker_is_held_across_chunks():
    guard = CitationStreamFilter({3})
    first = guard.feed("参考[")
    second = guard.feed("3] 即可")
    rest = guard.flush()
    assert first == "参考"
    assert second == "[3] 即可"
    assert rest == ""


def test_trailing_partial_marker_is_flushed_dropped():
    guard = CitationStreamFilter({1})
    assert guard.feed("见[1") == "见"  # 角标没写完，先 hold 住
    assert guard.flush() == ""        # 流结束时半截角标直接丢弃


def test_markdown_link_is_not_mistaken_for_marker():
    guard = CitationStreamFilter(set())
    text = _feed_all(guard, ["详情见 [官网](https://x.com) 页面"])
    assert "[官网](https://x.com)" in text


def test_select_used_keeps_original_indices():
    citations = [
        {"index": 1, "doc_title": "A"},
        {"index": 2, "doc_title": "B"},
        {"index": 3, "doc_title": "C"},
    ]
    used = select_used_citations("依据[2]与[3]", citations)
    # 不重排：正文里写的是 [2][3]，citation 就必须还是 2、3
    assert [item["index"] for item in used] == [2, 3]


def test_disclaimer_required_for_drug_agent():
    assert needs_disclaimer(AgentConfig(code="drug", name="AI 药师", kb_codes=["kb_drug_manual"]))
    assert not needs_disclaimer(AgentConfig(code="intro", name="企业介绍", kb_codes=["kb_company"]))


def test_finalize_injects_disclaimer_once():
    citations = [{"index": 1, "doc_title": "说明书"}]
    outcome = finalize("孕妇禁用[1]。", citations, need_disclaimer=True)
    assert DISCLAIMER in outcome.text
    assert "disclaimer_injected" in outcome.flags
    assert [item["index"] for item in outcome.citations] == [1]

    again = finalize(outcome.text, citations, need_disclaimer=True)
    assert again.text.count(DISCLAIMER) == 1


def test_finalize_prunes_unused_citations():
    citations = [{"index": 1}, {"index": 2}]
    outcome = finalize("只说了一句没有角标的话", citations)
    assert outcome.citations == []
    assert "citations_unused" in outcome.flags
