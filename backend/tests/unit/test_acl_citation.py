"""ACL 表达式与引用的单测。

「5 角色 × 4 库」的矩阵判定需要真库（见 ``tests/integration/test_acl_matrix.py``），
这里只测纯逻辑：过滤表达式构造、缓存序列化、引用校验。
"""

from __future__ import annotations

from app.rag.acl import AclSnapshot, build_filter, describe_acl
from app.rag.base import RetrievalResult, RetrievedChunk
from app.rag.citation import refusal_text, sanitize_citations, to_citations


# ------------------------------------------------------------------ 过滤表达式
def test_empty_kb_list_returns_none():
    """空权限必须返回 None —— 调用方据此拒答，绝不能退化成查全库。"""
    assert build_filter([]) is None


def test_filter_contains_kb_and_status():
    expr = build_filter(["kb_a", "kb_b"], include_effective=False)
    assert expr == 'kb_id in ["kb_a", "kb_b"] and status == "published"'


def test_filter_escapes_quotes():
    expr = build_filter(['bad"id'], include_effective=False)
    assert 'bad\\"id' in expr


def test_filter_has_effective_window():
    expr = build_filter(["kb_a"], now=1_700_000_000)
    assert "(effective_from == 0 or effective_from <= 1700000000)" in expr
    assert "(effective_to == 0 or effective_to >= 1700000000)" in expr


# ------------------------------------------------------------------ ACL 快照 / 缓存
def test_snapshot_json_roundtrip_marks_cache_hit():
    snapshot = AclSnapshot(
        role="patient",
        kb_ids=["a"],
        kb_codes={"a": "kb_company"},
        denied_kb_ids=["b"],
        denied_kb_codes={"b": "kb_sop"},
    )
    restored = AclSnapshot.from_json(snapshot.to_json(), role="patient")
    assert restored is not None
    assert restored.kb_ids == ["a"]
    assert restored.denied_kb_codes == {"b": "kb_sop"}
    # 从缓存读出来的快照应当被标记，方便排查"为什么权限没生效"
    assert restored.from_cache is True


def test_snapshot_from_bad_json_returns_none():
    assert AclSnapshot.from_json("not-json", role="patient") is None


def test_describe_acl_lists_both_sides():
    snapshot = AclSnapshot(
        role="visitor", kb_ids=["a"], kb_codes={"a": "kb_company"}, denied_kb_ids=["b"],
        denied_kb_codes={"b": "kb_sop"},
    )
    view = describe_acl(snapshot, names={"a": "企业介绍", "b": "客服 SOP"})
    assert view["allowed"][0]["name"] == "企业介绍"
    assert view["filtered_out_kbs"][0]["name"] == "客服 SOP"


# ------------------------------------------------------------------ 引用
def _result() -> RetrievalResult:
    return RetrievalResult(
        query="哺乳期能吃花红片吗",
        chunks=[
            RetrievedChunk(id="1", content="孕妇及哺乳期妇女禁用。", score=0.82, kb_id="kb", doc_id="d1",
                           doc_title="花红片说明书", section="禁忌", page=2),
            RetrievedChunk(id="2", content="口服，一次 4 片。", score=0.55, kb_id="kb", doc_id="d1",
                           doc_title="花红片说明书", section="用法用量", page=2),
        ],
    )


def test_to_citations_numbers_from_one():
    citations = to_citations(_result())
    assert [c["index"] for c in citations] == [1, 2]
    assert citations[0]["doc_title"] == "花红片说明书"
    assert citations[0]["section"] == "禁忌"


def test_sanitize_keeps_valid_marks():
    citations = to_citations(_result())
    answer, used = sanitize_citations("哺乳期禁用[1]。", citations)
    assert answer == "哺乳期禁用[1]。"
    assert [c["index"] for c in used] == [1]


def test_sanitize_drops_hallucinated_mark():
    citations = to_citations(_result())
    answer, used = sanitize_citations("根据资料[1]，另外[7]也有说明。", citations)
    assert "[7]" not in answer
    assert answer.count("[") == 1
    assert len(used) == 1


def test_sanitize_remaps_after_filtering():
    citations = to_citations(_result())
    answer, used = sanitize_citations("结论[2]。", citations)
    # 只引用了第 2 条，重排后它应当变成 [1]
    assert answer == "结论[1]。"
    assert used[0]["index"] == 1
    assert used[0]["section"] == "用法用量"


def test_sanitize_without_citations_strips_all_marks():
    answer, used = sanitize_citations("没有资料[1][2]。", [])
    assert answer == "没有资料。"
    assert used == []


def test_refusal_text_by_reason():
    assert "没有" in refusal_text("no_hit")
    assert "关联不大" in refusal_text("low_score")
    assert refusal_text("unknown-reason") == refusal_text("no_hit")
