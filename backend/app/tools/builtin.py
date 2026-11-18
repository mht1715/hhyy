"""内置工具（M2-02）：6 个。

| 工具 | 作用 | 权限 |
| --- | --- | --- |
| ``kb_search`` | 检索 Agent 绑定的知识库（再叠加 ACL） | 继承调用者 |
| ``policy_search`` | 售后政策快捷检索 | 所有 |
| ``product_lookup`` | 按名称/ID 查药品 | 所有 |
| ``order_lookup`` | 查订单与物流 | 本人 / support / admin |
| ``remember`` | 写一条记忆草稿 | 登录用户 |
| ``escalate_human`` | 请求转人工 | 所有 |

三条原则：

1. **权限在工具层**：``required_roles`` 由 :func:`call_tool` 统一校验，工具实现里
   再校验「数据归属」（例如 ``order_lookup`` 只能看自己的订单）。
2. **知识库先取交集**：Agent 绑定的 code ∩ 调用方 ACL，交给 ``RetrievalService``
   做真正的过滤，工具层不自己拼表达式。
3. **可预期失败抛 ``ToolError``**：模型能看懂 ``FORBIDDEN``/``NOT_FOUND``，
   而「代码炸了」会被 ``call_tool`` 收敛成 ``ERROR``。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.kb import KbStatus, KnowledgeBase
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.rag.retriever import get_retrieval_service
from app.tools.base import ToolContext, ToolError, ToolSpec, register_tool

# 售后单查权限：这两个角色可以看别人的订单（工单处理需要）
_ORDER_VIEW_ALL_ROLES = {"support", "admin"}
_MAX_ORDERS = 5


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


async def _kb_ids_for_codes(ctx: ToolContext, codes: list[str]) -> list[str]:
    """把知识库 code 解析成 id，并且只保留 active 的库。"""
    if not codes:
        return []
    rows = (
        await ctx.db.execute(
            select(KnowledgeBase.id, KnowledgeBase.code).where(
                KnowledgeBase.code.in_(codes),
                KnowledgeBase.status == KbStatus.ACTIVE.value,
            )
        )
    ).all()
    return [str(kb_id) for kb_id, _code in rows]


async def _run_kb_search(
    ctx: ToolContext,
    *,
    query: str,
    kind: str,
    top_k: int = 5,
    kb_codes: Optional[list[str]] = None,
) -> dict[str, Any]:
    wanted = [code for code in (kb_codes or ctx.kb_codes) if code in set(ctx.kb_codes)]
    if not wanted:
        raise ToolError("FORBIDDEN", f"当前 Agent 未绑定这些知识库：{kb_codes or ctx.kb_codes}")

    kb_ids = await _kb_ids_for_codes(ctx, wanted)
    if not kb_ids:
        raise ToolError("KB_NOT_READY", "绑定的知识库不存在或未启用")

    service = ctx.retrieval or get_retrieval_service()
    result = await service.retrieve(
        ctx.db,
        query,
        role=ctx.role,
        user_id=ctx.user_id,
        kb_ids=kb_ids,
        top_k=top_k,
    )

    hits = [
        {
            "doc_title": chunk.doc_title or chunk.doc_id,
            "section": chunk.section,
            "page": chunk.page,
            "score": round(chunk.score, 4),
            "snippet": " ".join(chunk.content.split())[:160],
            "url": chunk.source_url,
        }
        for chunk in result.chunks
    ]
    return {
        "_summary": f"{kind}：命中 {len(hits)} 段"
        + ("（已拒答：" + (result.reason or "") + "）" if result.refused else ""),
        "query": query,
        "kb_ids": result.kb_ids,
        "hits": hits,
        "top_score": round(result.top_score, 4),
        "refused": result.refused,
        "reason": result.reason,
        # chunks 不参与序列化，只给子 Agent 拼上下文与引用用
        "chunks": list(result.chunks),
    }


# --------------------------------------------------------------------------- 知识库
@register_tool(
    ToolSpec(
        name="kb_search",
        description="在当前 Agent 绑定的知识库中做混合检索（BM25+向量+重排），返回最相关的段落。回答专业问题前应先调用它。",
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题，用用户的原始说法即可"},
                "top_k": {"type": "integer", "description": "返回条数，默认 5", "minimum": 1, "maximum": 10},
                "kb_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：只在这些库里检索（必须是该 Agent 绑定库的子集）",
                },
            },
            "required": ["query"],
        },
        timeout_seconds=20.0,
    )
)
async def kb_search(
    ctx: ToolContext,
    query: str,
    top_k: int = 5,
    kb_codes: Optional[list[str]] = None,
) -> dict[str, Any]:
    return await _run_kb_search(ctx, query=query, kind="知识库检索", top_k=top_k, kb_codes=kb_codes)


@register_tool(
    ToolSpec(
        name="policy_search",
        description="查询订单与售后政策（退换货、退款时效、运费、发票）。只有被问及售后规则时使用。",
        args_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "售后问题，例如「七天无理由退货」"}},
            "required": ["query"],
        },
        timeout_seconds=20.0,
    )
)
async def policy_search(ctx: ToolContext, query: str) -> dict[str, Any]:
    return await _run_kb_search(
        ctx, query=query, kind="售后政策检索", kb_codes=["kb_after_sale"]
    )


# --------------------------------------------------------------------------- 药品
@register_tool(
    ToolSpec(
        name="product_lookup",
        description="按名称或 ID 查药品的结构化信息（价格、规格、厂家、批准文号）。适合确认「说的是哪个药」以及报价。",
        args_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "药品名称或通用名，支持模糊匹配"},
                "product_id": {"type": "string", "description": "已知的商品 UUID"},
            },
        },
        timeout_seconds=8.0,
    )
)
async def product_lookup(
    ctx: ToolContext, name: Optional[str] = None, product_id: Optional[str] = None
) -> dict[str, Any]:
    if product_id:
        try:
            product = await ctx.db.get(Product, uuid.UUID(str(product_id)))
        except ValueError as exc:
            raise ToolError("BAD_ARGS", f"product_id 不是合法 UUID：{product_id}") from exc
        if not product:
            raise ToolError("NOT_FOUND", "药品不存在")
        rows = [product]
    elif name:
        statement = (
            select(Product)
            .where(Product.name.ilike(f"%{name}%") | Product.generic_name.ilike(f"%{name}%"))
            .limit(5)
        )
        rows = list((await ctx.db.execute(statement)).scalars().all())
    else:
        raise ToolError("BAD_ARGS", "name 与 product_id 至少给一个")

    if not rows:
        raise ToolError("NOT_FOUND", "没有找到匹配的药品")

    items = [
        {
            "id": str(p.id),
            "name": p.name,
            "generic_name": p.generic_name,
            "spec": p.spec,
            "price": p.price,
            "manufacturer": p.manufacturer,
            "approval_number": p.approval_number,
            "in_stock": (p.stock or 0) > 0,
        }
        for p in rows
    ]
    return {
        "_summary": f"药品查询：找到 {len(items)} 个药品",
        "items": items,
    }


# --------------------------------------------------------------------------- 订单
@register_tool(
    ToolSpec(
        name="order_lookup",
        description="查当前用户的订单与物流状态（近 5 单，或按订单号查）。涉及「我的订单能不能退」时必须先调用它确认状态。",
        args_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单 UUID；不传则返回最近几单"},
                "limit": {"type": "integer", "description": "最近订单数，默认 3", "minimum": 1, "maximum": 5},
            },
        },
        required_roles=("patient", "doctor", "support", "admin"),
        timeout_seconds=8.0,
    )
)
async def order_lookup(
    ctx: ToolContext, order_id: Optional[str] = None, limit: int = 3
) -> dict[str, Any]:
    if not ctx.user_id:
        raise ToolError("AUTH_REQUIRED", "查询订单需要先登录")

    options = (selectinload(Order.items).selectinload(OrderItem.product),)

    if order_id:
        try:
            order_uuid = uuid.UUID(str(order_id))
        except ValueError as exc:
            raise ToolError("BAD_ARGS", f"order_id 不是合法 UUID：{order_id}") from exc
        order = (
            await ctx.db.execute(select(Order).options(*options).where(Order.id == order_uuid))
        ).scalar_one_or_none()
        if not order:
            raise ToolError("NOT_FOUND", "订单不存在")
        # 归属校验：非 support/admin 只能看自己的订单，且要明确回 FORBIDDEN 而不是「查无此单」
        if str(order.user_id) != str(ctx.user_id) and ctx.role not in _ORDER_VIEW_ALL_ROLES:
            raise ToolError("FORBIDDEN", "无权查看他人的订单")
        rows = [order]
    else:
        statement = (
            select(Order)
            .options(*options)
            .where(Order.user_id == ctx.user_id)
            .order_by(Order.created_at.desc())
            .limit(max(1, min(int(limit or 3), _MAX_ORDERS)))
        )
        rows = list((await ctx.db.execute(statement)).scalars().all())

    now = datetime.now(timezone.utc)
    orders = []
    for order in rows:
        age_days = (
            (now - order.created_at.astimezone(timezone.utc)).days
            if getattr(order, "created_at", None)
            else None
        )
        orders.append(
            {
                "order_id": str(order.id),
                "status": order.status,
                "total_amount": order.total_amount,
                "created_at": _iso(getattr(order, "created_at", None)),
                "age_days": age_days,
                "items": [
                    {
                        "name": item.product.name if item.product else "",
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                    }
                    for item in order.items
                ],
            }
        )

    summary = f"订单查询：{len(orders)} 单" if orders else "订单查询：没有查到订单"
    return {"_summary": summary, "orders": orders, "viewer_role": ctx.role}


# --------------------------------------------------------------------------- 记忆 / 转人工
@register_tool(
    ToolSpec(
        name="remember",
        description="把用户明确表达的长期偏好或事实记下来（例如「我对青霉素过敏」）。只记用户主动说的事实，不要自行推断。",
        args_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的一句话，20~100 字"},
                "key": {"type": "string", "description": "可选分类键，如 allergy / preference"},
            },
            "required": ["content"],
        },
        required_roles=("patient", "doctor", "support", "admin"),
        timeout_seconds=5.0,
    )
)
async def remember(
    ctx: ToolContext, content: str, key: Optional[str] = None
) -> dict[str, Any]:
    """写入长期记忆（M3-04）：走 ``MemoryStore``，不再是会话级的临时 notes。

    三条约束：
    1. 先看用户开关——关掉记忆后连显式「记住…」也不写（PRD FR6.6）；
    2. PII 先脱敏再入库（手机号/身份证/详细地址）；
    3. 失败只回 ``ok=False``，不要因为记忆写不进去影响这轮回答。
    """
    if not ctx.user_id:
        raise ToolError("AUTH_REQUIRED", "写记忆需要先登录")
    text = " ".join(str(content or "").split())[:500]
    if not text:
        raise ToolError("BAD_ARGS", "content 不能为空")

    from app.memory.base import MemoryItem
    from app.memory.extractor import classify, redact_pii
    from app.memory.long_term import PgMemoryStore

    store = PgMemoryStore(ctx.db)
    profile = await store.get_profile(ctx.user_id)
    if not profile.enabled:
        raise ToolError("MEMORY_DISABLED", "用户已关闭记忆功能，本条不保存")

    safe, pii_hits = redact_pii(text)
    kind = classify(safe)
    item = MemoryItem(
        id="",
        user_id=str(ctx.user_id),
        type=kind,
        content=safe[:200],
        confidence=0.95,
        sensitive=kind == "risk",
        source_conversation_id=str(ctx.conversation_id) if ctx.conversation_id else None,
    )
    memory_id = await store.add(item)
    await ctx.db.commit()

    return {
        "_summary": f"已记录：{safe[:24]}",
        "saved": True,
        "memory_id": memory_id,
        "type": kind,
        "redacted": bool(pii_hits),
        "key": key,
    }


@register_tool(
    ToolSpec(
        name="escalate_human",
        description="请求转人工客服。遇到投诉、医疗纠纷、要求赔偿、用药过量等敏感情况，或你无法给出可靠回答时调用。",
        args_schema={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "为什么要转人工，一句话"},
                "summary": {"type": "string", "description": "给坐席看的交接摘要"},
            },
            "required": ["reason"],
        },
        timeout_seconds=5.0,
    )
)
async def escalate_human(
    ctx: ToolContext, reason: str, summary: Optional[str] = None
) -> dict[str, Any]:
    text = " ".join(str(reason or "").split())[:200]
    if not text:
        raise ToolError("BAD_ARGS", "reason 不能为空")
    return {
        "_summary": f"请求转人工：{text[:30]}",
        "requested": True,
        "reason": text,
        "handoff_summary": " ".join(str(summary or "").split())[:400],
        # 真正的工单在 M3 建（handoff_tickets），这里只表达「需要人工」
        "suggested_action": {"type": "handoff", "label": "转人工客服"},
    }
