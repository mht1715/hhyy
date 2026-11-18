"""医药合规（M4-06）单测：违规样例、否定语境、流式跨块。"""

from app.guardrail.compliance import (
    EMERGENCY_NOTICE,
    ComplianceStreamFilter,
    apply_emergency_notice,
    detect_high_risk,
    looks_like_refusal,
    rewrite_claims,
)

# 10 个真实会出现的违规表达（PRD FR8.5 口径）
VIOLATIONS = [
    "这个药能根治咽炎",
    "坚持吃可以治愈",
    "本品无副作用",
    "这是最有效的办法",
    "包治百病",
    "药到病除",
    "立竿见影，当天见效",
    "百分百有效",
    "可以停药了",
    "不用看医生",
]


def test_each_violation_is_rewritten_and_flagged():
    for text in VIOLATIONS:
        outcome = rewrite_claims(text)
        assert outcome.hits, f"没识别出违规：{text}"
        for forbidden in ("根治", "治愈", "无副作用", "最有效", "包治", "药到病除", "立竿见影"):
            assert forbidden not in outcome.text, f"{text} 改写后仍含 {forbidden}：{outcome.text}"
        assert "compliance_rewritten" in outcome.flags()


def test_negated_claim_is_rewritten_without_flipping_meaning():
    # 「不能说它能根治」直接换成「不能说它能缓解」会把意思说反
    outcome = rewrite_claims("更不能说它能「根治」，请以说明书为准。")
    assert "根治" not in outcome.text
    assert "缓解" not in outcome.text
    assert "不能给出绝对化的疗效承诺" in outcome.text
    assert outcome.hits[0].category == "negated_claim"


def test_categories_split_absolute_claim_and_replace_doctor():
    outcomes = {item: rewrite_claims(item) for item in ("可以根治", "可以停药")}
    assert outcomes["可以根治"].hits[0].category == "absolute_claim"
    assert outcomes["可以停药"].hits[0].category == "replace_doctor"


def test_negated_claim_with_object_is_rewritten_as_a_whole():
    # 实测踩过的坑：只替换到「根治」为止，会剩下「」咽炎」这种断句
    text = "都不能用于治疗咽炎，更不能说它能「根治」咽炎。"
    outcome = rewrite_claims(text)
    assert "根治" not in outcome.text
    assert "承诺咽炎" not in outcome.text
    assert "」" not in outcome.text
    assert "不能给出绝对化的疗效承诺" in outcome.text


def test_negated_claim_does_not_cross_comma():
    # 两个分句不能被粘成一句
    text = "没有相关资料，不能保证疗效。"
    outcome = rewrite_claims(text)
    assert outcome.text == text


def test_clean_text_is_untouched():
    text = "花红片一次 4 片，一日 3 次，孕妇及哺乳期妇女禁用。"
    outcome = rewrite_claims(text)
    assert outcome.text == text
    assert outcome.hits == []
    assert outcome.flags() == []


def test_high_risk_symptoms_are_detected():
    assert detect_high_risk("我突然胸痛，还呼吸困难") == ["胸痛", "呼吸困难"]
    assert detect_high_risk("有点头晕") == []


def test_emergency_notice_is_idempotent_and_prepended():
    once = apply_emergency_notice("可以先观察。")
    assert once.startswith(EMERGENCY_NOTICE)
    assert apply_emergency_notice(once) == once


def test_stream_filter_catches_phrase_split_across_chunks():
    guard = ComplianceStreamFilter()
    parts = [guard.feed("这个药能根"), guard.feed("治咽炎吗"), guard.feed("，建议就医。")]
    parts.append(guard.flush())
    text = "".join(parts)
    assert "根治" not in text
    assert "缓解" in text
    assert guard.hits


def test_stream_filter_handles_negation_context():
    guard = ComplianceStreamFilter()
    text = "".join(
        [guard.feed("不能说它能「根"), guard.feed("治」"), guard.feed("，请遵医嘱。"), guard.flush()]
    )
    assert "根治" not in text
    assert "不能给出绝对化的疗效承诺" in text
    assert any(hit.category == "negated_claim" for hit in guard.hits)


def test_stream_filter_flushes_partial_text():
    guard = ComplianceStreamFilter()
    # 普通文本不该被扣住（扣了会拖慢首字）
    assert guard.feed("花红片") == "花红片"
    assert guard.flush() == ""


def test_refusal_detection_reads_only_the_opening():
    assert looks_like_refusal("资料中没有关于该药的信息，建议咨询药师。")
    assert looks_like_refusal("我无法判断这个问题。")
    # 免责声明里的「请及时就医」出现在结尾，不该把正常回答判成拒答
    assert not looks_like_refusal(
        "花红片一次 4 片，一日 3 次。"
        "本回答基于药品说明书整理，具体用药请遵医嘱；如症状持续或加重，请及时就医。"
    )
