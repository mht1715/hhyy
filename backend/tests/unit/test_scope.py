"""范围守卫（M4-02 配套）单测：问题超出知识库覆盖时不能硬答。"""

from app.rag.scope import OUT_OF_SCOPE_TERMS, out_of_scope_terms

CHUNK = "【功能主治】清热解毒，燥湿止带，祛瘀止痛。用于湿热瘀滞所致带下病、月经不调。"


def test_known_disease_absent_from_chunks_is_out_of_scope():
    assert out_of_scope_terms("花红片能治糖尿病吗", [CHUNK]) == ["糖尿病"]
    assert out_of_scope_terms("这个药能减肥吗", [CHUNK]) == ["减肥"]


def test_term_present_in_chunks_is_in_scope():
    chunk = "【适应症】用于 2 型糖尿病患者的血糖控制。"
    assert out_of_scope_terms("这个药对糖尿病有用吗", [chunk]) == []


def test_plain_question_has_no_out_of_scope_terms():
    assert out_of_scope_terms("花红片一次吃几片", [CHUNK]) == []
    assert out_of_scope_terms("七天无理由退货吗", ["自签收之日起 7 天内…"]) == []


def test_multiple_terms_are_all_reported():
    terms = out_of_scope_terms("又失眠又痛风怎么办", [CHUNK])
    assert set(terms) == {"失眠", "痛风"}


def test_lexicon_is_non_empty_and_deduplicated():
    assert len(OUT_OF_SCOPE_TERMS) >= 20
    assert len(set(OUT_OF_SCOPE_TERMS)) == len(OUT_OF_SCOPE_TERMS)
