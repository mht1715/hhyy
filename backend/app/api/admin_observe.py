"""指标看板（M4-04，PRD FR7.6）。

数据口径全部写在返回体的 ``definitions`` 里——看板数字和 Langfuse 对不上时，
最怕的就是「各自猜口径」。这里的原则是：

- **只读业务库**，不实时调用 Langfuse API（它慢、会超时，而且看板的用途是趋势不是审计）；
- 每轮回答的 ``latency_ms`` / ``usage`` / ``citations`` / ``guardrail`` / ``feedback``
  都已经在 ``messages`` 里，聚合就够了；
- 百分比一律 0~1 小数返回，前端负责格式化（避免「有人返回 12，有人返回 0.12」）。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminOnly
from app.core.config import settings
from app.core.database import get_db
from app.core.timefmt import iso_utc
from app.guardrail.citations import DISCLAIMER
from app.guardrail.compliance import looks_like_refusal
from app.models.agent import Conversation, Message, MessageRole
from app.models.eval import EvalRun
from app.models.handoff import HandoffTicket, TicketStatus
from app.models.kb import DocumentStatus, KbDocument
from app.models.memory import UserMemory, UserProfile
from app.models.user import User
from app.schemas.response import ResponseModel

router = APIRouter()

MAX_SCAN = 2000
FEEDBACK_REASONS = ("答非所问", "引用不对", "太啰嗦", "不该拒答", "信息过时", "其他")

DEFINITIONS = {
    "refusal_rate": "回答前两句命中「没有资料 / 无法判断 / 建议就医」的比例",
    "citation_rate": "带可溯源引用的回答占比（RAG 类问题应当接近 100%）",
    "disclaimer_rate": "带免责声明的回答 / 带引用的回答（药品类合规口径）",
    "error_rate": "空回答 / 全部回答（近似错误率：中断、超时最终都表现为空）",
    "handoff_rate": "工单数 / 会话数（同一会话多次转人工会重复计数）",
    "latency": "只统计 latency_ms > 0 的回答；p95 用线性插值",
    "cost": "按配置的每千 token 单价估算，不是账单",
}


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * ratio
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return int(round(ordered[low] * (1 - weight) + ordered[high] * weight))


def _ratio(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


async def _assistant_messages(db: AsyncSession, since: datetime) -> list[Message]:
    rows = (
        await db.execute(
            select(Message)
            .where(
                Message.role == MessageRole.ASSISTANT.value,
                Message.created_at >= since,
            )
            .order_by(Message.created_at.desc())
            .limit(MAX_SCAN)
        )
    ).scalars().all()
    return list(rows)


def _is_refusal(message: Message) -> bool:
    return bool((message.content or "").strip()) and looks_like_refusal(message.content)


def _flags(message: Message) -> list[str]:
    raw = message.guardrail or {}
    flags = raw.get("flags") if isinstance(raw, dict) else None
    return [str(item) for item in (flags or [])]


def _violations(message: Message) -> list[dict[str, Any]]:
    raw = message.guardrail or {}
    items = raw.get("violations") if isinstance(raw, dict) else None
    return [item for item in (items or []) if isinstance(item, dict)]


def _cost(usage: dict[str, Any]) -> float:
    data = usage or {}
    input_tokens = int(data.get("input_tokens") or 0)
    output_tokens = int(data.get("output_tokens") or 0)
    return (
        input_tokens / 1000 * settings.llm_price_input_per_1k
        + output_tokens / 1000 * settings.llm_price_output_per_1k
    )


async def _daily_counts(db: AsyncSession, model, since: datetime) -> dict[str, int]:
    """按天计数。用 ``func.date`` 而不是在 Python 里循环，省掉全表扫描。"""
    rows = (
        await db.execute(
            select(func.date(model.created_at), func.count())
            .where(model.created_at >= since)
            .group_by(func.date(model.created_at))
        )
    ).all()
    data: dict[str, int] = {}
    for day, count in rows:
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        data[key] = int(count)
    return data


def _trend(
    days: int,
    answered: list[Message],
    conversations: dict[str, int],
    tickets: dict[str, int],
) -> list[dict[str, Any]]:
    """近 N 天逐日趋势：给看板画折线用，一眼看出「哪天真出事了」。"""
    today = datetime.utcnow().date()
    start = today - timedelta(days=days - 1)
    buckets: dict[str, dict[str, Any]] = {}
    for offset in range(days):
        key = (start + timedelta(days=offset)).isoformat()
        buckets[key] = {"date": key, "turns": 0, "refusals": 0, "conversations": 0, "tickets": 0}
    for item in answered:
        key = item.created_at.date().isoformat() if item.created_at else ""
        bucket = buckets.get(key)
        if bucket is None:
            continue
        bucket["turns"] += 1
        if _is_refusal(item):
            bucket["refusals"] += 1
    for key, bucket in buckets.items():
        bucket["conversations"] = conversations.get(key, 0)
        bucket["tickets"] = tickets.get(key, 0)
    return [buckets[key] for key in sorted(buckets)]


@router.get("/overview", response_model=ResponseModel[dict])
async def overview(
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    since = datetime.utcnow() - timedelta(days=days)
    messages = await _assistant_messages(db, since)
    answered = [item for item in messages if (item.content or "").strip()]
    with_citations = [item for item in answered if item.citations]

    latencies = [int(item.latency_ms or 0) for item in answered if int(item.latency_ms or 0) > 0]
    input_tokens = sum(int((item.usage or {}).get("input_tokens") or 0) for item in answered)
    output_tokens = sum(int((item.usage or {}).get("output_tokens") or 0) for item in answered)
    cost = sum(_cost(item.usage) for item in answered)

    conversations = (
        await db.execute(
            select(func.count()).select_from(Conversation).where(Conversation.created_at >= since)
        )
    ).scalar_one()
    tickets = (
        await db.execute(
            select(func.count()).select_from(HandoffTicket).where(HandoffTicket.created_at >= since)
        )
    ).scalar_one()
    open_tickets = (
        await db.execute(
            select(func.count())
            .select_from(HandoffTicket)
            .where(
                HandoffTicket.status.in_(
                    [TicketStatus.QUEUED.value, TicketStatus.ASSIGNED.value]
                )
            )
        )
    ).scalar_one()

    refusal_count = sum(1 for item in answered if _is_refusal(item))
    disclaimer_count = sum(1 for item in with_citations if DISCLAIMER in (item.content or ""))
    empty_count = len(messages) - len(answered)

    # M5：工作台首屏要「今天该干什么」，所以除了总量还给逐日趋势与待办
    conversation_daily = await _daily_counts(db, Conversation, since)
    ticket_daily = await _daily_counts(db, HandoffTicket, since)
    queued_tickets = (
        await db.execute(
            select(func.count())
            .select_from(HandoffTicket)
            .where(HandoffTicket.status == TicketStatus.QUEUED.value)
        )
    ).scalar_one()
    failed_docs = (
        await db.execute(
            select(func.count())
            .select_from(KbDocument)
            .where(KbDocument.status == DocumentStatus.FAILED.value)
        )
    ).scalar_one()

    up = sum(1 for item in answered if (item.feedback or {}).get("rating") == "up")
    down = sum(1 for item in answered if (item.feedback or {}).get("rating") == "down")

    flag_counter: Counter[str] = Counter()
    violation_counter: Counter[str] = Counter()
    recent_violations: list[dict[str, Any]] = []
    for item in messages:
        flags = _flags(item)
        if not flags and not _violations(item):
            continue
        flag_counter.update(flags)
        for violation in _violations(item):
            violation_counter[str(violation.get("kind") or violation.get("category") or "other")] += 1
        if len(recent_violations) < 10:
            recent_violations.append(
                {
                    "message_id": str(item.id),
                    "agent_code": item.agent_code or "",
                    "flags": flags,
                    "violation": (_violations(item) or [{}])[0].get("kind", ""),
                    "at": iso_utc(item.created_at),
                }
            )

    per_agent: dict[str, dict[str, Any]] = {}
    for item in answered:
        code = item.agent_code or "unknown"
        bucket = per_agent.setdefault(
            code, {"code": code, "turns": 0, "latency": [], "refusals": 0}
        )
        bucket["turns"] += 1
        if int(item.latency_ms or 0) > 0:
            bucket["latency"].append(int(item.latency_ms))
        if _is_refusal(item):
            bucket["refusals"] += 1

    agents = [
        {
            "code": item["code"],
            "turns": item["turns"],
            "refusal_rate": _ratio(item["refusals"], item["turns"]),
            "avg_latency_ms": int(sum(item["latency"]) / len(item["latency"])) if item["latency"] else 0,
        }
        for item in sorted(per_agent.values(), key=lambda row: row["turns"], reverse=True)
    ]

    profiles = (await db.execute(select(func.count()).select_from(UserProfile))).scalar_one()
    memories = (await db.execute(select(func.count()).select_from(UserMemory))).scalar_one()

    latest_eval = (
        await db.execute(select(EvalRun).order_by(EvalRun.ran_at.desc()).limit(1))
    ).scalar_one_or_none()
    eval_payload: dict[str, Any] = {"available": latest_eval is not None}
    if latest_eval is not None:
        metrics = dict(latest_eval.metrics or {})
        eval_payload.update(
            {
                "ran_at": iso_utc(latest_eval.ran_at),
                "mode": latest_eval.mode,
                "cases": latest_eval.cases,
                "recall_at_5": metrics.get("recall_at_5"),
                "mrr": metrics.get("mrr"),
                "refusal_accuracy": metrics.get("refusal_accuracy"),
                "citation_precision": metrics.get("citation_precision"),
                "faithfulness": metrics.get("faithfulness"),
                "failures": len(latest_eval.failures or []),
            }
        )

    # 待办：只保留「点进去能处理」的项。数量为 0 的也返回（前端自己决定要不要展示），
    # 这样看板不会因为某天没异常就少一行、把布局抖一下。
    todos = [
        {
            "key": "queued_tickets",
            "label": "排队待接管工单",
            "value": int(queued_tickets),
            "tone": "warn" if queued_tickets else "ok",
            "to": "/support",
            "note": "坐席接管后可继续对话",
        },
        {
            "key": "down_feedback",
            "label": "未处理差评",
            "value": down,
            "tone": "danger" if down else "ok",
            "to": "/admin/observe",
            "note": "可导出为评估集候选",
        },
        {
            "key": "guardrail_violations",
            "label": "输出治理拦截",
            "value": sum(violation_counter.values()),
            "tone": "warn" if violation_counter else "ok",
            "to": "/admin/observe",
            "note": "合规改写 / 引用裁剪 / 拒答",
        },
        {
            "key": "failed_documents",
            "label": "解析失败文档",
            "value": int(failed_docs),
            "tone": "danger" if failed_docs else "ok",
            "to": "/admin/kb",
            "note": "失败文档不进检索",
        },
        {
            "key": "eval_failures",
            "label": "评估失败用例",
            "value": int(eval_payload.get("failures") or 0),
            "tone": "warn" if (eval_payload.get("failures") or 0) else "ok",
            "to": "/admin/observe",
            "note": "最近一次评估的失败条数",
        },
    ]

    return ResponseModel(
        data={
            "window_days": days,
            "generated_at": iso_utc(datetime.utcnow()),
            "totals": {
                "conversations": conversations,
                "messages": len(messages),
                "turns": len(answered),
                "handoffs": tickets,
                "open_tickets": open_tickets,
            },
            "trend": _trend(days, answered, conversation_daily, ticket_daily),
            "todos": todos,
            "latency": {
                "p50_ms": _percentile(latencies, 0.50),
                "p95_ms": _percentile(latencies, 0.95),
                "avg_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
                "count": len(latencies),
            },
            "quality": {
                "refusal_rate": _ratio(refusal_count, len(answered)),
                "citation_rate": _ratio(len(with_citations), len(answered)),
                "disclaimer_rate": _ratio(disclaimer_count, len(with_citations)),
                "handoff_rate": _ratio(tickets, conversations),
                "error_rate": _ratio(empty_count, len(messages)),
                "feedback_up": up,
                "feedback_down": down,
            },
            "cost": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_cny": round(cost, 4),
                "avg_cost_per_turn_cny": round(cost / len(answered), 6) if answered else 0.0,
            },
            "guardrail": {
                "violations": sum(violation_counter.values()),
                "by_flag": dict(flag_counter.most_common()),
                "by_kind": dict(violation_counter.most_common()),
                "recent": recent_violations,
            },
            "memory": {"profiles": profiles, "memories": memories},
            "agents": agents,
            "eval": eval_payload,
            "links": {
                "langfuse": settings.langfuse_base_url or "",
                "definitions": DEFINITIONS,
            },
        }
    )


@router.get("/recent", response_model=ResponseModel[list[dict]])
async def recent(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    """最近若干轮：给看板做「点开看原文」用，也方便现场解释某个数字是怎么来的。"""
    rows = (
        await db.execute(
            select(Message)
            .where(Message.role == MessageRole.ASSISTANT.value)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    data: list[dict[str, Any]] = []
    for row in rows:
        question = (
            await db.execute(
                select(Message.content)
                .where(
                    Message.conversation_id == row.conversation_id,
                    Message.role == MessageRole.USER.value,
                    Message.created_at <= row.created_at,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        data.append(
            {
                "message_id": str(row.id),
                "conversation_id": str(row.conversation_id),
                "agent_code": row.agent_code or "",
                "question": (question or "")[:200],
                "answer": (row.content or "")[:600],
                "latency_ms": int(row.latency_ms or 0),
                "guardrail": {
                    "flags": _flags(row),
                    "violations": _violations(row),
                },
                "feedback": row.feedback or {},
                "trace_id": row.trace_id or "",
                "created_at": iso_utc(row.created_at),
            }
        )
    return ResponseModel(data=data)


@router.get("/feedback/export", response_model=ResponseModel[list[dict]])
async def export_feedback(
    days: int = Query(default=30, ge=1, le=365),
    rating: str = Query(default="down"),
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    """把反馈导出成「评估集候选」（M4-09 闭环）：人工确认后可直接进 golden set。"""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        await db.execute(
            select(Message)
            .where(Message.role == MessageRole.ASSISTANT.value, Message.created_at >= since)
            .order_by(Message.created_at.desc())
            .limit(MAX_SCAN)
        )
    ).scalars().all()

    data: list[dict[str, Any]] = []
    for row in rows:
        feedback = row.feedback or {}
        if str(feedback.get("rating") or "") != rating:
            continue
        question = (
            await db.execute(
                select(Message.content)
                .where(
                    Message.conversation_id == row.conversation_id,
                    Message.role == MessageRole.USER.value,
                    Message.created_at <= row.created_at,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        data.append(
            {
                "question": question or "",
                "answer": row.content or "",
                "agent_code": row.agent_code or "",
                "expected_docs": [item.get("doc_title") for item in (row.citations or [])],
                "rating": feedback.get("rating"),
                "reason": feedback.get("reason") or "",
                "conversation_id": str(row.conversation_id),
                "message_id": str(row.id),
                "created_at": iso_utc(row.created_at),
            }
        )
    return ResponseModel(data=data)


@router.get("/system", response_model=ResponseModel[dict])
async def system_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    """系统页：把「依赖是否真的通了」摊开给面试官看，而不是只显示绿灯图标。

    ``/health`` 是给探针用的（无鉴权、极简）；这里补上**配置快照**，方便解释
    「为什么这台机器召回是 0.94」——模型、维度、灰度开关都在这里。
    """
    from app.agent.checkpointer import get_checkpointer
    from app.core.redis import redis_ping

    db_ok = True
    try:
        await db.execute(select(func.now()))
    except Exception:  # pragma: no cover - 只有依赖真的挂了才走到
        db_ok = False

    redis_ok = await redis_ping()
    checkpointer_ok = False
    if settings.checkpointer_enabled:
        try:
            checkpointer_ok = await get_checkpointer() is not None
        except Exception:  # pragma: no cover
            checkpointer_ok = False

    components = [
        {"key": "database", "label": "PostgreSQL + pgvector", "ok": db_ok},
        {"key": "redis", "label": "Redis（事件总线 / 限流）", "ok": bool(redis_ok)},
        {
            "key": "checkpointer",
            "label": "LangGraph 检查点",
            "ok": checkpointer_ok or not settings.checkpointer_enabled,
        },
        {
            "key": "milvus",
            "label": "Milvus 向量库",
            "ok": bool(settings.milvus_uri),
        },
        {
            "key": "langfuse",
            "label": "Langfuse 链路追踪",
            "ok": bool(settings.langfuse_base_url and settings.langfuse_public_key),
        },
    ]

    return ResponseModel(
        data={
            "components": components,
            "config": {
                "chat_model": settings.deepseek_chat_model,
                "embedding_model": settings.dashscope_embedding_model,
                "embedding_dimensions": settings.embedding_dimensions,
                "rerank_model": settings.rerank_model if settings.rerank_enabled else "已关闭",
                "rag_collection": settings.rag_collection,
                "memory_collection": settings.memory_collection,
                "memory_enabled": settings.memory_enabled,
                "memory_window_turns": settings.memory_window_turns,
                "memory_history_budget": settings.memory_history_budget,
                "checkpointer_enabled": settings.checkpointer_enabled,
                "supervisor_enabled": settings.supervisor_enabled,
                "supervisor_confidence_floor": settings.supervisor_confidence_floor,
                "rerank_score_threshold": settings.rerank_score_threshold,
                "llm_timeout": settings.llm_timeout,
            },
            "generated_at": iso_utc(datetime.utcnow()),
        }
    )


__all__ = ["router", "FEEDBACK_REASONS", "DEFINITIONS"]
