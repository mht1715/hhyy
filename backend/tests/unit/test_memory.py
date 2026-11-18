"""记忆纯逻辑测试（M3-03 ~ M3-06）。

覆盖四件事：去重口径、PII 脱敏、抽取的「该记/不该记」边界、注入文案。
这些都是「记忆功能会不会被用户当垃圾」的分界线，必须锁死。
"""

from __future__ import annotations

from app.memory.base import MemoryItem
from app.memory.extractor import (
    Candidate,
    classify,
    dedupe,
    extract_memories,
    has_explicit_trigger,
    redact_pii,
    rule_candidates,
    should_attempt,
)
from app.memory.inject import load_memory, render_block
from app.memory.long_term import normalize_text, similarity
from app.testing.fakes import FakeMemoryStore

USER = "user-1"


def test_normalize_and_similarity_dedupe():
    assert normalize_text("我对青霉素 过敏。") == normalize_text("我对青霉素过敏")
    # 同义改写：多说/少说几个字，加权相似度要能过 0.72 的去重线
    assert similarity("我对青霉素过敏", "我青霉素过敏") > 0.7
    # 无关句子必须明显低于阈值，否则会把偏好和禁忌合并成一条
    assert similarity("我对青霉素过敏", "希望寄颗粒剂") < 0.2
    assert similarity("我对青霉素过敏", "我对花粉过敏") < 0.45


def test_redact_pii_masks_phone_id_and_address():
    text, hits = redact_pii("我电话13800001111，身份证110101199001011234，住北京市朝阳区建国路88号")
    assert "13800001111" not in text
    assert "138****1111" in text
    assert "110101199001011234" not in text
    assert "北京市朝阳区" in text  # 保留到区/街道，门牌被抹掉
    assert set(hits) == {"phone", "id_card", "address"}


def test_rule_candidates_are_conservative():
    """只有「显式指令」或「第一人称 + 风险/偏好关键词」才记，普通提问不记。"""
    assert rule_candidates("我想问下这个药怎么吃") == []
    assert rule_candidates("今天天气不错") == []

    risk = rule_candidates("我对青霉素过敏")
    assert len(risk) == 1
    assert risk[0].type == "risk" and risk[0].sensitive is True

    pref = rule_candidates("我希望能寄颗粒剂，不喜欢胶囊")
    assert {item.type for item in pref} == {"preference"}

    explicit = rule_candidates("记住，我下周三去复查")
    assert explicit and explicit[0].confidence >= 0.9

    # 指令词本身不能变成一条记忆
    mixed = rule_candidates("我对青霉素过敏，这个要记住")
    assert len(mixed) == 1 and "过敏" in mixed[0].content


def test_memory_refusal_keeps_user_context():
    from app.memory.inject import memory_refusal_text

    items = [
        MemoryItem(id="1", user_id=USER, type="risk", content="对青霉素过敏"),
        MemoryItem(id="2", user_id=USER, type="preference", content="偏好颗粒剂"),
    ]
    text = memory_refusal_text(items)
    assert "对青霉素过敏" in text
    assert "不做推测" in text
    # 偏好不是「能不能吃」的依据，不该出现在拒答里
    assert "颗粒剂" not in text
    assert memory_refusal_text([items[1]]) == ""


def test_classify_priority():
    assert classify("我孕早期能吃吗") == "risk"
    assert classify("我偏好颗粒剂") == "preference"
    assert classify("我上次咨询过这个药") == "episode"
    assert classify("我的名字是张三") == "fact"


def test_explicit_trigger_and_trivial_filter():
    assert has_explicit_trigger("帮我记一下：我对酒精过敏")
    assert not has_explicit_trigger("我对酒精过敏")
    assert should_attempt("我对青霉素过敏")
    assert not should_attempt("你好")


async def test_extract_memories_writes_risk_item_and_masks_pii():
    store = FakeMemoryStore()
    result = await extract_memories(
        store=store,
        user_id=USER,
        message="我对青霉素过敏，留个手机号13800001111",
        message_id="m-1",
        conversation_id="c-1",
    )
    assert len(result.items) == 1
    item = result.items[0]
    assert item.type == "risk" and item.sensitive is True
    assert "13800001111" not in item.content
    assert item.source_message_id == "m-1"
    stored = await store.list_for_user(USER)
    assert [row.id for row in stored] == [item.id]


async def test_extract_memories_ignores_chitchat():
    store = FakeMemoryStore()
    result = await extract_memories(store=store, user_id=USER, message="你好")
    assert result.items == [] and result.skipped == "trivial"


async def test_extract_memories_respects_user_switch():
    store = FakeMemoryStore()
    await store.set_enabled(USER, False)
    result = await extract_memories(store=store, user_id=USER, message="我对青霉素过敏")
    assert result.items == [] and result.skipped == "memory_disabled"


def test_dedupe_keeps_highest_confidence_per_type():
    candidates = [
        Candidate(type="fact", content="用户叫张三", confidence=0.6),
        Candidate(type="fact", content="用户叫张三", confidence=0.9),
        Candidate(type="preference", content="用户叫张三", confidence=0.5),
    ]
    merged = dedupe(candidates)
    assert len(merged) == 2
    assert next(c for c in merged if c.type == "fact").confidence == 0.9


def test_render_block_has_labels_sources_and_footer():
    items = [
        MemoryItem(id="1", user_id=USER, type="risk", content="孕早期", sensitive=True),
        MemoryItem(id="2", user_id=USER, type="fact", content="对青霉素过敏"),
    ]
    block = render_block(items, "慢病患者")
    assert "需要特别留意：孕早期" in block
    assert "已知事实：对青霉素过敏" in block
    assert "您上次提到" in block  # 可解释话术的要求写进了 prompt
    assert "画像：慢病患者" in block


async def test_load_memory_returns_nothing_for_anonymous():
    injected = await load_memory(None, user_id=None, query="能吃吗")
    assert injected.enabled is False and injected.injected is False


async def test_load_memory_respects_switch_and_injects_items():
    store = FakeMemoryStore()
    await store.add(MemoryItem(id="1", user_id=USER, type="fact", content="对青霉素过敏"))

    injected = await load_memory(None, user_id=USER, query="这个药能吃吗", store=store)
    assert injected.enabled is True
    assert injected.injected is True
    assert "对青霉素过敏" in injected.block
    assert injected.as_event()["items"][0]["source_message_id"] is None

    await store.set_enabled(USER, False)
    disabled = await load_memory(None, user_id=USER, query="这个药能吃吗", store=store)
    assert disabled.enabled is False and disabled.block == ""
