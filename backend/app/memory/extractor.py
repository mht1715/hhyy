"""记忆抽取（M3-04，PRD FR6.4）。

流程：**规则优先 → 模型补充 → PII 脱敏 → 去重 → 落库**。

几个刻意的选择：

- **规则先行**：用户说「我对青霉素过敏」这种最典型的记忆，根本不需要调模型——
  正则 + 关键词就够，还省一次调用。模型只用来补「语义上等价但说法不同」的表达。
- **只记用户自述**：没有第一人称、也没有「记住」类显式指令的句子，一律不记。
  宁可少记，也不要从客服的话里反推出用户属性（那是编造）。
- **PII 一律脱敏**：手机号、身份证、详细地址在入库前就被替换。记忆是长期保存的，
  它的隐私风险和一次性的对话内容不是一个量级。
- **失败不影响回答**：整个函数在后台任务里跑，任何异常只记日志。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from app.memory.base import MemoryItem
from app.memory.long_term import PgMemoryStore
from app.models.memory import MemoryType

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 3
MIN_CONFIDENCE = 0.6
MAX_CONTENT_CHARS = 200

# 显式指令：用户说「记住…」时立即写入并回执（PRD FR6.4-4）
EXPLICIT_TRIGGERS = ("记住", "记一下", "帮我记", "别忘了", "记得")

RISK_HINTS = ("过敏", "孕", "哺乳", "备孕", "糖尿病", "高血压", "心脏病", "哮喘", "癫痫", "手术", "透析", "肝功能", "肾功能", "禁忌")
PREFERENCE_HINTS = ("喜欢", "偏好", "习惯", "希望", "最好", "方便", "不喜欢", "想要")
EPISODE_HINTS = ("上次", "之前", "上回", "买过", "咨询过", "吃过")

# 第一人称：只记用户自己的事
FIRST_PERSON = re.compile(r"(我|本人|自己|孩子|宝宝|家里|老公|老婆|父亲|母亲|爸|妈)")
# 问候/寒暄：没有抽取价值，直接跳过，省一次模型调用
CHITCHAT = re.compile(r"^(你好|您好|hi|hello|在吗|谢谢|好的|嗯|哦|ok)[!！。.\s]*$", re.IGNORECASE)

PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
ID_CARD = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
ADDRESS = re.compile(r"([\u4e00-\u9fa5]{2,6}(?:省|市|区|县|镇|乡|街道))([\u4e00-\u9fa5A-Za-z0-9]{2,20}(?:路|街|号|栋|单元|室))")

EXTRACT_PROMPT = """从用户这句话里抽取值得长期记住的信息。只抽用户关于**自己**的事实、偏好、禁忌；不要抽取商品价格、客服话术、临时性问题。

用户这句话：{message}

只输出 JSON 数组，最多 3 条，没有就给 []。每条形如：
{{"type": "fact|preference|episode|risk", "content": "一句话，20~80字，用第三人称陈述", "confidence": 0.0~1.0}}

判断标准：
- fact：稳定的个人信息（过敏史、慢病、长期服药）
- preference：稳定的偏好（剂型偏好、联系方式偏好）
- episode：某次咨询/购买经历
- risk：需要特别当心的身体状况（孕期、哺乳期、严重疾病）
"""


@dataclass(slots=True)
class Candidate:
    type: str
    content: str
    confidence: float = 0.8
    sensitive: bool = False
    source: str = "rule"

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "content": self.content,
            "confidence": round(self.confidence, 3),
            "sensitive": self.sensitive,
            "source": self.source,
        }


@dataclass(slots=True)
class ExtractionResult:
    items: list[MemoryItem] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    skipped: str = ""
    enabled: bool = True


def has_explicit_trigger(text: str) -> bool:
    return any(trigger in (text or "") for trigger in EXPLICIT_TRIGGERS)


def should_attempt(text: str) -> bool:
    """值不值得抽取：太短或纯寒暄就别花这个钱。"""
    value = (text or "").strip()
    if len(value) < 4:
        return False
    if CHITCHAT.match(value):
        return False
    return True


def redact_pii(text: str) -> tuple[str, list[str]]:
    """把手机号/身份证/详细地址替换成掩码，返回 (脱敏文本, 命中类型列表)。"""
    hits: list[str] = []
    value = text or ""
    if PHONE.search(value):
        value = PHONE.sub(lambda m: m.group(1)[:3] + "****" + m.group(1)[-4:], value)
        hits.append("phone")
    if ID_CARD.search(value):
        value = ID_CARD.sub(lambda m: m.group(1)[:6] + "********" + m.group(1)[-4:], value)
        hits.append("id_card")
    if ADDRESS.search(value):
        value = ADDRESS.sub(lambda m: m.group(1) + "***", value)
        hits.append("address")
    return value, hits


def classify(text: str) -> str:
    """按关键词判类型。顺序很重要：``risk`` 优先于 ``preference``。"""
    value = text or ""
    if any(hint in value for hint in RISK_HINTS):
        return MemoryType.RISK.value
    if any(hint in value for hint in PREFERENCE_HINTS):
        return MemoryType.PREFERENCE.value
    if any(hint in value for hint in EPISODE_HINTS):
        return MemoryType.EPISODE.value
    return MemoryType.FACT.value


def rule_candidates(message: str) -> list[Candidate]:
    """不花模型就能拿到的高置信候选。

    触发条件（必须满足其一，宁可漏记也不要污染记忆库）：

    1. 显式指令（「记住…」）；
    2. 第一人称 + 命中风险/偏好/情节关键词（过敏、孕、哺乳、慢病、偏好、上次…）。

    为什么第二条要收紧：如果只按「有第一人称」就记，那「我想问下这个药怎么吃」
    也会被记成一条 fact——用户打开「我的记忆」看到一堆废话，会立刻关掉这个功能。
    """
    value = (message or "").strip()
    if not value:
        return []
    explicit = has_explicit_trigger(value)

    pieces = [p.strip() for p in re.split(r"[，。；;！!？?\n]+", value) if p.strip()]
    candidates: list[Candidate] = []
    for piece in pieces:
        # 把「记住」「帮我记一下」这类指令词剥掉后再判断：光一句「这个要记住」
        # 不该变成一条记忆（用户看到会很困惑）
        stripped = piece
        for trigger in EXPLICIT_TRIGGERS:
            stripped = stripped.replace(trigger, "")
        stripped = stripped.strip(" 的了吧呢啊，。")
        if len(stripped) < 4:
            continue
        has_hint = any(
            hint in piece for hint in (*RISK_HINTS, *PREFERENCE_HINTS, *EPISODE_HINTS)
        )
        if not explicit and not (has_hint and FIRST_PERSON.search(piece)):
            continue
        kind = classify(piece)
        candidates.append(
            Candidate(
                type=kind,
                content=piece[:MAX_CONTENT_CHARS],
                confidence=0.9 if explicit else 0.75,
                sensitive=kind == MemoryType.RISK.value,
                source="rule",
            )
        )
    return candidates[:MAX_CANDIDATES]


def _parse_candidates(raw: str) -> list[Candidate]:
    """容错解析模型输出：允许 ```json 围栏、允许外面包一层对象。"""
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        data = data.get("items") or data.get("memories") or []
    if not isinstance(data, list):
        return []

    candidates: list[Candidate] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        content = " ".join(str(row.get("content") or "").split())[:MAX_CONTENT_CHARS]
        kind = str(row.get("type") or "").strip()
        if not content or kind not in {item.value for item in MemoryType}:
            continue
        try:
            confidence = float(row.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        candidates.append(
            Candidate(
                type=kind,
                content=content,
                confidence=max(0.0, min(confidence, 1.0)),
                sensitive=bool(row.get("sensitive")) or kind == MemoryType.RISK.value,
                source="llm",
            )
        )
    return candidates[:MAX_CANDIDATES]


async def llm_candidates(message: str, llm: Any) -> list[Candidate]:
    """模型补充候选。失败返回空列表（不抛）。"""
    if llm is None:
        return []
    try:
        response = await llm.ainvoke(
            [
                {"role": "system", "content": "你是信息抽取器，只输出 JSON。"},
                {"role": "user", "content": EXTRACT_PROMPT.format(message=message[:500])},
            ]
        )
        return _parse_candidates(str(getattr(response, "content", "") or ""))
    except Exception as exc:  # noqa: BLE001 —— 抽取失败不能影响回答
        logger.warning("记忆抽取模型调用失败：%s", exc)
        return []


def dedupe(candidates: Sequence[Candidate]) -> list[Candidate]:
    """同一批候选内部去重（不同的 type 不算重复）。"""
    from app.memory.long_term import normalize_text

    seen: dict[str, Candidate] = {}
    for candidate in candidates:
        key = f"{candidate.type}:{normalize_text(candidate.content)}"
        existing = seen.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            seen[key] = candidate
    return list(seen.values())


async def extract_memories(
    *,
    store: PgMemoryStore,
    user_id: Any,
    message: str,
    message_id: Any = None,
    conversation_id: Any = None,
    llm: Any = None,
    force: bool = False,
) -> ExtractionResult:
    """抽取并写入。``force=True``（显式「记住…」）时跳过「值不值得」的判断。"""
    profile = await store.get_profile(user_id)
    if not profile.enabled:
        return ExtractionResult(skipped="memory_disabled", enabled=False)
    if not force and not should_attempt(message):
        return ExtractionResult(skipped="trivial")

    candidates = rule_candidates(message)
    if not candidates:
        # 规则没命中时才问模型：绝大多数轮次走不到这里，省下的是真金白银的延迟
        candidates = await llm_candidates(message, llm)
    candidates = dedupe(candidates)

    items: list[MemoryItem] = []
    for candidate in candidates:
        if candidate.confidence < MIN_CONFIDENCE:
            continue
        content, pii_hits = redact_pii(candidate.content)
        content = " ".join(content.split())
        if len(content) < 4:
            continue
        if pii_hits:
            logger.info("记忆内容已脱敏（%s）", ",".join(pii_hits))
        items.append(
            MemoryItem(
                id=str(uuid.uuid4()),
                user_id=str(user_id),
                type=candidate.type,
                content=content,
                confidence=candidate.confidence,
                sensitive=candidate.sensitive,
                source_message_id=str(message_id) if message_id else None,
                source_conversation_id=str(conversation_id) if conversation_id else None,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    written: list[MemoryItem] = []
    for item in items:
        memory_id = await store.add(item)
        item.id = memory_id
        written.append(item)
    return ExtractionResult(items=written, candidates=candidates, enabled=True)


async def refresh_profile_summary(store: PgMemoryStore, user_id: Any, *, llm: Any = None) -> str:
    """把记忆压成 ≤300 token 的画像摘要（PRD FR6.5）。

    有模型时用模型写；没有就按类型拼要点。画像只在「注入」时用，不对外暴露原文。
    """
    items = await store.list_for_user(user_id, limit=20)
    if not items:
        return ""
    lines = [f"{kind}：{content}" for kind, content in _group(items)]
    if llm is not None and len(lines) > 6:
        prompt = (
            "把下面的用户记忆要点压缩成一段不超过 150 字的中文画像，"
            "只保留对用药建议有影响的信息（过敏、慢病、孕期哺乳、剂型偏好）：\n"
            + "\n".join(lines)
        )
        try:
            response = await llm.ainvoke(
                [
                    {"role": "system", "content": "你是严谨的信息压缩器。"},
                    {"role": "user", "content": prompt},
                ]
            )
            text = str(getattr(response, "content", "") or "").strip()
            if text:
                return text[:600]
        except Exception as exc:  # noqa: BLE001
            logger.warning("画像摘要生成失败，改用要点拼接：%s", exc)
    return "\n".join(lines)[:600]


def _group(items: Sequence[MemoryItem]) -> list[tuple[str, str]]:
    from app.memory.base import TYPE_LABELS

    ordered = sorted(items, key=lambda item: 0 if item.type == MemoryType.RISK.value else 1)
    return [(TYPE_LABELS.get(item.type, item.type), item.content) for item in ordered]


__all__ = [
    "Candidate",
    "EXPLICIT_TRIGGERS",
    "ExtractionResult",
    "RISK_HINTS",
    "classify",
    "dedupe",
    "extract_memories",
    "has_explicit_trigger",
    "llm_candidates",
    "redact_pii",
    "refresh_profile_summary",
    "rule_candidates",
    "should_attempt",
]
