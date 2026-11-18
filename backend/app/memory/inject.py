"""把记忆注入 prompt（M3-06，PRD FR6.5）。

三个约束决定了这段文案的写法：

1. **可解释**：要求模型用「您上次提到…」这种措辞把依据说出来，而不是默默用了记忆。
   用户看到「您上次提到对青霉素过敏」才知道系统记了什么，这也是 FR6.6 的底气。
2. **相关才用**：记忆是背景，不是每轮都要念一遍。prompt 里明确写「不相关就忽略」，
   否则模型会把过敏史硬塞进「退货运费谁出」这种问题里。
3. **敏感项单独措辞**：``risk`` 类型（孕期、慢病）用「需要特别留意」而不是「事实」，
   避免模型把它当成确定诊断去下结论。

注入本身失败一律降级为空（记忆是加分项，不能拖垮主回答）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.memory.base import TYPE_LABELS, MemoryItem

logger = logging.getLogger(__name__)

MAX_ITEMS = 3
MAX_BLOCK_CHARS = 900
# 语义记忆的相关度门槛（余弦）。实测：相关的用药问题 0.36~0.58，
# 「订单退款多久到账」这类无关问题 0.17~0.25——0.30 刚好落在中间。
# 低于门槛的不注入：宁可不提记忆，也不要每轮都念一遍过敏史。
MIN_SCORE = 0.30

MEMORY_HEADER = "【关于这位用户的历史信息】（来自以前的对话，可能与本轮无关）"
MEMORY_FOOTER = (
    "如果上面某条信息与本轮问题直接相关（尤其是用户问「这个药能不能吃/能不能用」，"
    "而这里有过敏、孕期哺乳、慢病等信息），请先用「您上次提到……，所以……」说明依据，"
    "再给结论；不相关就忽略，不要主动提及这些信息，也不要把它们当作诊断结论。"
)

# 记忆相关的兜底话术：有可信记忆、但知识库没资料时，用它代替「什么都不知道」的拒答
MEMORY_REFUSAL = (
    "您上次提到{points}，这一点我记着。"
    "但这次问到的药品，我在资料里没有找到可靠依据，为稳妥起见不做推测。"
    "建议您带着这个情况咨询在线药师，或前往正规医院就诊。"
)
MAX_REFUSAL_ITEMS = 2


@dataclass(slots=True)
class InjectedMemory:
    """一次注入的产物：既给 prompt 用，也给 SSE / 前端展示用。"""

    items: list[MemoryItem] = field(default_factory=list)
    profile_summary: str = ""
    enabled: bool = True
    block: str = ""
    reason: str = ""

    @property
    def injected(self) -> bool:
        return bool(self.block)

    def as_event(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": item.id,
                    "type": item.type,
                    "content": item.content,
                    "score": item.score,
                    "sensitive": item.sensitive,
                    "source_message_id": item.source_message_id,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in self.items
            ],
            "profile": {"summary": self.profile_summary, "enabled": self.enabled},
            "injected": self.injected,
        }


def render_block(items: list[MemoryItem], profile_summary: str = "") -> str:
    """拼成 prompt 里的一段。空记忆返回空串（调用方据此决定是否注入）。"""
    lines: list[str] = []
    if profile_summary.strip():
        lines.append(f"- 画像：{' '.join(profile_summary.split())[:300]}")
    for item in items[:MAX_ITEMS]:
        label = TYPE_LABELS.get(item.type, item.type)
        when = item.created_at.strftime("%Y-%m-%d") if item.created_at else ""
        lines.append(f"- {label}：{item.content}" + (f"（{when}）" if when else ""))
    if not lines:
        return ""

    block = "\n".join([MEMORY_HEADER, *lines, MEMORY_FOOTER])
    if len(block) > MAX_BLOCK_CHARS:
        block = block[: MAX_BLOCK_CHARS - 20] + "\n（其余记忆已省略）\n" + MEMORY_FOOTER
    return block


def memory_refusal_text(items: list[MemoryItem]) -> str:
    """有记忆、但资料不足时的拒答话术（M3-06 的「可解释」）。

    这种情况在真实客服里很常见：用户问的药我们没收录，但他有过敏史。
    什么都不说（标准拒答）会显得「刚说过的话你都没记住」；直接答又违反「无依据不猜」。
    折中做法是**只复述记忆、不给药品结论**，并把决定权交回给用户/药师。
    """
    points: list[str] = []
    for item in items:
        if item.type not in ("risk", "fact"):
            continue
        text = " ".join(item.content.split())
        if text and text not in points:
            points.append(f"「{text}」")
        if len(points) >= MAX_REFUSAL_ITEMS:
            break
    if not points:
        return ""
    return MEMORY_REFUSAL.format(points="、".join(points))


async def load_memory(
    db: Any,
    *,
    user_id: Any,
    query: str,
    semantic: Any = None,
    store: Any = None,
    limit: int = MAX_ITEMS,
) -> InjectedMemory:
    """读画像 + top-k 记忆，并渲染成可注入的文本块。"""
    if not user_id:
        return InjectedMemory(enabled=False, reason="anonymous")

    if store is None:
        from app.memory.long_term import PgMemoryStore

        store = PgMemoryStore(db, vectors=semantic)

    try:
        profile = await store.get_profile(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取记忆画像失败：%s", exc)
        return InjectedMemory(enabled=False, reason="profile_error")

    if not profile.enabled:
        return InjectedMemory(enabled=False, reason="memory_disabled")

    try:
        items = await store.search(user_id, query, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("记忆检索失败：%s", exc)
        items = []

    # 语义检索会按相似度排序；没有分数（本地排序 / 空查询）时不按分数过滤，
    # 交给 prompt 里的「不相关就忽略」兜底。
    relevant: list[MemoryItem] = []
    for item in items:
        if not item.content.strip():
            continue
        if item.score and item.score < MIN_SCORE:
            continue
        relevant.append(item)

    summary = (profile.summary or "").strip()
    block = render_block(relevant, summary)
    return InjectedMemory(
        items=relevant,
        profile_summary=summary,
        enabled=True,
        block=block,
        reason="" if block else "no_relevant",
    )


def describe(items: list[MemoryItem]) -> Optional[str]:
    """一句话说明「用了几条记忆」，给 done 事件用。"""
    return f"参考了 {len(items)} 条记忆" if items else None


__all__ = [
    "InjectedMemory",
    "MAX_ITEMS",
    "describe",
    "load_memory",
    "memory_refusal_text",
    "render_block",
]
