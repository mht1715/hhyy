"""阈值口径与拒答可观测性的回归测试（M1 返工）。

这一组盯的是「检索测试台一律拒答」那次事故的三个根因：
阈值的刻度（重排分 vs 余弦分）、拒答后分数被清零、拒答后上下文仍可拼装。
"""

from app.core.config import settings
from app.rag.base import RetrievalResult, RetrievedChunk
from app.rag.retriever import resolve_threshold


def test_override_wins_over_everything():
    assert resolve_threshold(source="rerank", override=0.5, kb_threshold=0.35) == 0.5
    assert resolve_threshold(source="dense", override=0.0, kb_threshold=0.35) == 0.0


def test_rerank_source_ignores_kb_threshold():
    cut = resolve_threshold(source="rerank", kb_threshold=0.35)

    # 库上的 0.35 是余弦刻度，重排分拿它卡会把「介绍一下企业」这类泛问句全拒掉
    assert cut == settings.rerank_score_threshold
    assert cut < 0.35


def test_dense_source_prefers_kb_threshold():
    assert resolve_threshold(source="dense", kb_threshold=0.40) == 0.40
    assert resolve_threshold(source="dense", kb_threshold=None) == settings.score_threshold


def test_refused_result_never_yields_context():
    result = RetrievalResult(
        query="介绍一下企业",
        chunks=[RetrievedChunk(id="c1", content="花红药业是一家……", score=0.28, kb_id="kb1")],
        refused=True,
        reason="low_score",
        top_score=0.28,
        threshold=0.35,
        score_source="dense",
    )

    # 调用方万一只看 chunks 不看 refused，也不能拿到上下文去硬答
    assert result.as_context() == ""


def test_rejected_candidates_stay_for_observability():
    chunk = RetrievedChunk(id="c1", content="花红药业企业简介", score=0.28, kb_id="kb1")
    result = RetrievalResult(query="介绍一下企业")
    result.chunks = []
    result.rejected_chunks = [chunk]
    result.top_score = 0.28
    result.threshold = 0.35
    result.refused = True
    result.reason = "low_score"

    # 拒答时 top_score 必须保留真实值，否则测试台只能看到 0.0，无法判断差多少
    assert result.top_score == 0.28
    assert result.rejected_chunks[0].id == "c1"
    assert result.as_context() == ""
