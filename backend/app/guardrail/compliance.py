"""医药合规（M4-06，PRD FR8.4 ③ / FR8.5）。

三层规则，全部是**规则引擎**（不花模型调用，可在单测里逐条断言）：

1. **绝对化疗效承诺**：根治 / 治愈 / 无副作用 / 最有效 / 包治 / 药到病除 /
   立竿见影 / 100% 有效 / 保证有效 …（《广告法》第十六条、第十七条口径）。
   命中不拦截，而是**改写成合规表述**——直接拒答会让用户觉得「答非所问」，
   而「这药能根治吗」这类问题本身是有正当信息需求的。
2. **替代医生诊断**：不用看医生 / 可以停药 / 不用吃药 …→ 改写成「建议就医 / 遵医嘱」。
3. **高危症状**：胸痛、呼吸困难、大出血、意识模糊、抽搐…→ 用户一描述就必须
   在回答前面加「立即就医 / 拨打 120」，不能先讲药理（PRD FR8.5）。

为什么要有 ``ComplianceStreamFilter``：流式输出是「发出去就收不回」的，
所以和引用闸门（``citations.CitationStreamFilter``）一样，必须**边流边改**：
把可能是敏感词前缀的尾巴先扣住，确认不是再放行。扣住的最长长度 = 最长敏感词长度 - 1，
中文短词通常 2~4 字，用户感知不到延迟。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- 规则表
# 绝对化疗效承诺 → 合规表述。顺序有意义：长词先匹配，避免「彻底治好」被「治好」截断
CLAIM_REWRITES: dict[str, str] = {
    "彻底根治": "缓解症状",
    "彻底治好": "控制症状",
    "药到病除": "按疗程服用可能改善症状",
    "立竿见影": "起效时间因人而异",
    "百分百有效": "多数情况下可能有效",
    "100%有效": "多数情况下可能有效",
    "保证有效": "效果因人而异",
    "没有任何副作用": "不良反应因人而异",
    "无任何副作用": "不良反应因人而异",
    "无副作用": "不良反应因人而异",
    "绝对安全": "相对安全性需结合个体情况评估",
    "最有效": "较常用",
    "最好的药": "较常用的药物",
    "包治": "对部分人可能有效",
    "根治": "缓解",
    "治愈": "改善症状",
    "替代药物": "不能替代医生处方",
    "可以停药": "请遵医嘱调整用药",
    "不用看医生": "建议同时咨询医生",
    "不用去医院": "建议必要时就医",
}

# 用户描述这些症状时，任何药品建议都必须让位给「立即就医」
HIGH_RISK_SYMPTOMS: tuple[str, ...] = (
    "胸痛",
    "胸闷气短",
    "呼吸困难",
    "喘不上气",
    "大出血",
    "出血不止",
    "呕血",
    "便血",
    "意识模糊",
    "昏迷",
    "抽搐",
    "晕厥",
    "休克",
    "剧烈头痛",
    "高烧不退",
    "胎动异常",
    "自杀",
    "轻生",
)

EMERGENCY_NOTICE = (
    "⚠️ 你描述的情况可能属于急症，请**立即就医**或拨打 **120**，"
    "不要只依赖线上咨询；在等待就医期间请勿自行加量服药。"
)

CATEGORY_LABELS = {
    "absolute_claim": "绝对化疗效承诺",
    "replace_doctor": "替代医生诊断",
    "negated_claim": "否定式提及（已改写为合规表述）",
    "high_risk": "高危症状",
}

_MAX_PHRASE = max(len(phrase) for phrase in CLAIM_REWRITES)

# 「否定式提及」不能直接替换：把「更不能说它能根治」改成「…能缓解」会把意思说反。
# 这类句子本身是**合规**的（它在否认疗效），但验收口径要求输出里不出现这些词，
# 所以整句改写成「不能给出绝对化的疗效承诺」——既保留了否定，也不再有违禁词。
_NEGATION_WORDS = ("不能", "无法", "不会", "不可", "不宜", "不应", "并非", "不是", "没有")
_NEGATION = "(?:" + "|".join(_NEGATION_WORDS) + ")"
_NEGATION_CLAUSE = re.compile(
    _NEGATION
    # 中间不许跨逗号/句号：跨了就会把两个分句粘成一句
    + r"[^。！？!?，,、\n]{0,10}?"
    + r"(?:根治|治愈|彻底治好|彻底根治|药到病除|包治|无副作用|副作用)"
    # 连宾语一起吃掉（「根治」咽炎 → 整句），否则会剩一个孤零零的「咽炎」
    + r"[^。！？!?，,、\n]{0,8}"
)
_NEGATED_TEXT = "不能给出绝对化的疗效承诺"

# 流式缓冲：既要放得下最长敏感词，也要能看到「不能…根治…宾语」的完整否定语境
_STREAM_HOLD = 24

# 「替代医生诊断」类：措辞不同、处置相同（都要拉回医嘱），但看板要分开统计
_REPLACE_DOCTOR = frozenset({"替代药物", "可以停药", "不用看医生", "不用去医院"})


def _category(phrase: str) -> str:
    return "replace_doctor" if phrase in _REPLACE_DOCTOR else "absolute_claim"


@dataclass(slots=True)
class ComplianceHit:
    category: str
    phrase: str
    replacement: str

    def as_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "phrase": self.phrase,
            "replacement": self.replacement,
            "label": CATEGORY_LABELS.get(self.category, self.category),
        }


@dataclass(slots=True)
class ComplianceOutcome:
    text: str
    hits: list[ComplianceHit] = field(default_factory=list)
    high_risk: list[str] = field(default_factory=list)

    @property
    def rewritten(self) -> bool:
        return bool(self.hits)

    def flags(self) -> list[str]:
        flags: list[str] = []
        if self.hits:
            flags.append("compliance_rewritten")
        if self.high_risk:
            flags.append("high_risk_notice")
        return flags

    def as_guardrail(self) -> dict[str, Any]:
        return {
            "flags": self.flags(),
            "violations": [hit.as_dict() for hit in self.hits],
            "high_risk": list(self.high_risk),
        }


def detect_high_risk(text: str) -> list[str]:
    """命中高危症状；返回命中的词（去重、保序），供日志与前端提示。"""
    value = text or ""
    found: list[str] = []
    for symptom in HIGH_RISK_SYMPTOMS:
        if symptom in value and symptom not in found:
            found.append(symptom)
    return found


def _rewrite_negated(text: str) -> tuple[str, list[ComplianceHit]]:
    """先把「不能…根治」这类否定句整句换掉，再做逐词替换。"""
    hits: list[ComplianceHit] = []

    def repl(match: re.Match[str]) -> str:
        hits.append(ComplianceHit("negated_claim", match.group(0), _NEGATED_TEXT))
        return _NEGATED_TEXT

    return _NEGATION_CLAUSE.sub(repl, text), hits


def rewrite_claims(text: str) -> ComplianceOutcome:
    """非流式路径：一次性把绝对化表述替换掉。"""
    value, negated = _rewrite_negated(text or "")
    hits: list[ComplianceHit] = list(negated)
    for phrase, replacement in CLAIM_REWRITES.items():
        if phrase in value:
            hits.append(ComplianceHit(_category(phrase), phrase, replacement))
            value = value.replace(phrase, replacement)
    return ComplianceOutcome(text=value, hits=hits)


class ComplianceStreamFilter:
    """流式合规闸门：扣住可能是敏感词前缀的尾巴，命中就改写。

    与 ``CitationStreamFilter`` 的区别：它做的是**改写**而不是丢弃，
    所以缓冲区必须足够长（最长敏感词 - 1），否则「根」「治」分两块到达时会漏。
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.hits: list[ComplianceHit] = []
        self.emitted = ""

    def feed(self, text: str) -> str:
        self.buffer += text or ""
        hold = self._pending_suffix()
        cut = len(self.buffer) - hold
        head, self.buffer = self.buffer[:cut], self.buffer[cut:]
        safe = self._rewrite(head)
        self.emitted += safe
        return safe

    def flush(self) -> str:
        tail, self.buffer = self.buffer, ""
        safe = self._rewrite(tail)
        self.emitted += safe
        return safe

    # ------------------------------------------------------------------ 内部
    def _pending_suffix(self) -> int:
        """buffer 末尾有多少字符要先扣住。

        两种情况：
        1. 末尾正好是某个敏感词的前缀 → 扣到能判定为止；
        2. 末尾处于否定语境（出现「不能 / 无法 / …」）→ **从否定词起整段扣住**，
           等看清后面接不接违禁词。否则「不能说它能根治」会被改写成
           「不能说它能缓解」，把意思说反。
        """
        # 1) 否定语境优先：一旦出现「不能 / 无法 / …」，从它开始整段扣住，
        #    否则「不能」会被先发出去，后面的「根治」就只能被孤立改写（意思说反）
        tail_start = max(0, len(self.buffer) - _STREAM_HOLD)
        tail = self.buffer[tail_start:]
        last = max((tail.rfind(neg) for neg in _NEGATION_WORDS), default=-1)
        if last >= 0:
            return len(self.buffer) - (tail_start + last)

        # 2) 末尾正好是敏感词前缀 → 扣到能判定为止
        limit = min(len(self.buffer), _STREAM_HOLD)
        for size in range(limit, 0, -1):
            suffix = self.buffer[-size:]
            if any(phrase.startswith(suffix) for phrase in CLAIM_REWRITES):
                return size
        return 0

    def _rewrite(self, text: str) -> str:
        if not text:
            return ""
        value, negated = _rewrite_negated(text)
        self.hits.extend(negated)
        for phrase, replacement in CLAIM_REWRITES.items():
            if phrase in value:
                self.hits.append(ComplianceHit(_category(phrase), phrase, replacement))
                value = value.replace(phrase, replacement)
        return value


def apply_emergency_notice(text: str) -> str:
    """在回答前插入急症提示（幂等：已经有就不重复插）。"""
    body = (text or "").strip()
    if EMERGENCY_NOTICE in body:
        return text
    if not body:
        return EMERGENCY_NOTICE
    return f"{EMERGENCY_NOTICE}\n\n{body}"


_SENTENCE = re.compile(r"[。！？!?\n]")


def looks_like_refusal(text: str) -> bool:
    """拒答判定（看板用）：回答明确说「没有资料 / 无法判断 / 建议就医」都算。

    宁可放宽一点：拒答率是用来发现「检索命中不足」的信号，不是审计口径。
    """
    body = (text or "").strip()
    if not body:
        return False
    markers = (
        "没有找到",
        "没有收录",
        "资料中没有",
        "未收录",
        "无法判断",
        "不能判断",
        "不做推测",
        "请咨询在线药师",
        "建议就医",
    )
    # 只在前 2 句里找：回答末尾的「如症状持续请就医」是免责范畴，不该算拒答
    head = "".join(_SENTENCE.split(body)[:2]) if _SENTENCE.search(body) else body[:80]
    return any(marker in head for marker in markers)


__all__ = [
    "CLAIM_REWRITES",
    "CATEGORY_LABELS",
    "EMERGENCY_NOTICE",
    "HIGH_RISK_SYMPTOMS",
    "ComplianceHit",
    "ComplianceOutcome",
    "ComplianceStreamFilter",
    "apply_emergency_notice",
    "detect_high_risk",
    "looks_like_refusal",
    "rewrite_claims",
]
