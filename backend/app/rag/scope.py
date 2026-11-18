"""检索「范围守卫」（M4-02 的配套改动）。

检索层的阈值只能判断「语义像不像」，判断不了「资料有没有回答这个问题」。
最典型的翻车：问「花红片能治糖尿病吗」，top 命中《花红片说明书》（因为都提到花红片），
分数很高——但说明书里根本没写糖尿病，模型只能基于说明书硬套。

做法很土但有效：维护一份**常见疾病/诉求词表**，如果用户问题里出现了词表里的词，
而召回片段里一处都没提到，就判定「超出知识库范围」并拒答。这不是 NER，也不需要
模型调用，换来的是「不该答的不硬答」，代价是可能误杀极少数跨领域问题（可接受）。
"""

from __future__ import annotations

from typing import Iterable

# 药品/售后知识库覆盖不到的常见疾病与诉求。宁可多列，误杀一条也只是「请咨询药师」。
OUT_OF_SCOPE_TERMS: tuple[str, ...] = (
    "糖尿病",
    "高血压",
    "癌症",
    "肿瘤",
    "减肥",
    "减重",
    "骨折",
    "感冒",
    "发烧",
    "发热",
    "失眠",
    "痛风",
    "肝炎",
    "肾炎",
    "心脏病",
    "哮喘",
    "抑郁",
    "焦虑症",
    "癫痫",
    "中风",
    "血栓",
    "贫血",
    "甲亢",
    "甲减",
    "湿疹",
    "银屑病",
    "白癜风",
    "近视",
    "白内障",
    "脱发",
    "阳痿",
    "早泄",
)


def out_of_scope_terms(query: str, texts: Iterable[str]) -> list[str]:
    """返回「问题提到、但召回片段里完全没有」的超纲词。"""
    question = query or ""
    corpus = "\n".join(text or "" for text in texts)
    return [term for term in OUT_OF_SCOPE_TERMS if term in question and term not in corpus]


__all__ = ["OUT_OF_SCOPE_TERMS", "out_of_scope_terms"]
