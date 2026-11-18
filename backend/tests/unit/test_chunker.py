"""分块器单测：三条硬约束都必须真的成立（PRD FR3.2）。"""

from __future__ import annotations

import pytest

from app.rag.chunker import chunk_document, estimate_tokens, reassemble
from app.rag.parser import parse_plain_text

# 一段结构接近真实说明书的样本（7 个小节）
MANUAL = """【药品名称】通用名称：花红片。
【成份】一点红、白花蛇舌草、地桃花、白背叶根、鸡血藤、桃金娘根、菥蓂。
【性状】本品为薄膜衣片。
【功能主治】清热解毒，燥湿止带，祛瘀止痛。用于湿热瘀滞所致带下病、月经不调。
【用法用量】口服。一次 4 片，一日 3 次，7 天为一疗程。
【禁忌】孕妇及哺乳期妇女禁用。对本品成分过敏者禁用。
【注意事项】忌食辛辣、生冷、油腻食物。服药 7 天症状无缓解，应去医院就诊。
【贮藏】密封，置阴凉干燥处。
"""


def test_manual_is_split_into_sections():
    parsed = parse_plain_text(MANUAL)
    titles = [section.title for section in parsed.sections]
    assert len(parsed.sections) >= 6
    assert "禁忌" in titles
    assert "用法用量" in titles


def test_contraindication_becomes_its_own_chunk_with_section():
    chunks = chunk_document(parse_plain_text(MANUAL))
    contra = [chunk for chunk in chunks if chunk.section == "禁忌"]
    assert len(contra) == 1
    assert "哺乳期" in contra[0].content
    # 关键：禁忌这块不能把别的段落也带进来
    assert "功能主治" not in contra[0].content


def test_every_chunk_within_limit():
    chunks = chunk_document(parse_plain_text(MANUAL))
    assert chunks
    assert all(len(chunk.content) <= 800 for chunk in chunks)


def test_chunks_reassemble_to_source():
    """切分不得丢字：按 overlap 去重后拼回来必须与切分输入完全一致。"""
    parsed = parse_plain_text(MANUAL)
    chunks = chunk_document(parsed)
    source = "".join(section.text for section in parsed.sections)
    assert reassemble(chunks) == source


def test_long_section_is_split_with_declared_overlap():
    long_text = "【注意事项】" + "本品应在医师指导下使用。" * 80
    parsed = parse_plain_text(long_text)
    chunks = chunk_document(parsed, max_chars=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(chunk.content) <= 200 for chunk in chunks)
    # 除第一块外都要声明重叠，且重叠确实是上一块的结尾
    for previous, current in zip(chunks, chunks[1:]):
        if current.overlap:
            assert previous.content.endswith(current.content[: current.overlap])
    assert reassemble(chunks) == "".join(section.text for section in parsed.sections)


def test_short_chunks_from_different_sections_are_not_merged():
    """跨小节不合并：禁忌不能和注意事项粘在一起，否则 section 标签就失去意义。"""
    text = "【禁忌】孕妇禁用。\n【注意事项】忌食辛辣。"
    chunks = chunk_document(parse_plain_text(text), min_chars=50)
    assert len(chunks) == 2
    assert {chunk.section for chunk in chunks} == {"禁忌", "注意事项"}


def test_merge_short_only_within_same_section():
    from app.rag.chunker import _merge_short

    same_section = [("很短。", 0, "注意事项", None), ("接下来这一块就足够长了不用再合并了", 0, "注意事项", None)]
    assert len(_merge_short(same_section, min_chars=50, max_chars=800)) == 1

    cross_section = [("很短。", 0, "禁忌", None), ("也很短。", 0, "注意事项", None)]
    assert len(_merge_short(cross_section, min_chars=50, max_chars=800)) == 2


def test_recursive_strategy_ignores_sections():
    chunks = chunk_document(parse_plain_text(MANUAL), strategy="recursive")
    assert chunks
    assert all(chunk.section is None for chunk in chunks)


def test_chunk_does_not_split_table_rows():
    table = "| 规格 | 价格 |\n| --- | --- |\n| 0.3g*24片 | 38元 |\n"
    text = "【规格价格】\n" + table + "以上价格为含税价。"
    # max_chars 只要装得下整张表，就不该把表拆到两块里
    chunks = chunk_document(parse_plain_text(text), max_chars=120)
    assert any("0.3g*24片" in chunk.content and "| 规格 |" in chunk.content for chunk in chunks)


def test_invalid_params_rejected():
    parsed = parse_plain_text("正文")
    with pytest.raises(ValueError):
        chunk_document(parsed, max_chars=0)
    with pytest.raises(ValueError):
        chunk_document(parsed, max_chars=100, overlap=100)


def test_estimate_tokens_counts_cjk():
    assert estimate_tokens("中文四个字") == 5
    assert estimate_tokens("abcd") == 1
