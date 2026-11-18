"""对话流式端点（M2-06）。

三个必须做对的地方：

1. **流一定要有终止帧**。业务异常、客户端断开、模型超时，最后都要落到 ``error``
   或 ``done``，否则前端只能干等到超时（见 ``app/agent/sse.py``）。
2. **幂等**。同一个 ``client_message_id`` 在窗口内重复提交，直接重放上次结果
   （``done.replayed=true``），不重复调用模型、不重复计费。
3. **流里用独立 DB 会话**。请求级依赖的 session 生命周期由框架控制，长连接流式
   响应期间它可能在流结束前被回收；这里在生成器内部自己开一个 session，避免
   「回答到一半 `session is closed`」这种只在慢网络下复现的问题。
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import get_agent_registry
from app.agent.runtime import ChatRuntime, TurnContext, TurnRequest, get_chat_runtime
from app.agent.sse import SSEEvent, encode_event, error_event, sse_headers
from app.api.auth import get_optional_user
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.redis import rate_limit_hit
from app.llm.client import LLMNotConfigured, get_chat_client
from app.models.agent import Conversation, Message, MessageRole
from app.models.user import User
from app.observability.tracing import get_trace_sink
from app.rag.acl import VISITOR_ROLE
from app.schemas.chat import ChatStreamRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_key(request: Request, user: User | None) -> str:
    if user is not None:
        return f"user:{user.id}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


async def _get_agent_or_403(db: AsyncSession, code: str, role: str):
    registry = get_agent_registry()
    agent = await registry.get(db, code)
    if agent is None or not agent.is_active:
        raise HTTPException(status_code=403, detail=f"未知或已下线的 Agent：{code}")
    if not agent.allows(role):
        raise HTTPException(status_code=403, detail=f"当前身份无权使用 {agent.name}")
    return agent


async def _history(db: AsyncSession, conversation_id: uuid.UUID) -> list[dict[str, str]]:
    """取最近 N 轮一问一答，喂给模型做上下文（M3 会换成 checkpointer + 摘要）。"""
    limit = settings.chat_history_turns * 2
    rows = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_([MessageRole.USER.value, MessageRole.ASSISTANT.value]),
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {"role": row.role, "content": (row.content or "")[:1500]}
        for row in reversed(rows)
        if (row.content or "").strip()
    ]


async def _find_replay(
    db: AsyncSession, client_message_id: str
) -> Optional[tuple[Message, Message]]:
    """幂等：找窗口内同 client_message_id 的用户消息及其回答。"""
    since = _now() - timedelta(seconds=settings.chat_idempotency_seconds)
    user_message = (
        await db.execute(
            select(Message)
            .where(
                Message.client_message_id == client_message_id,
                Message.role == MessageRole.USER.value,
                Message.created_at >= since,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if user_message is None:
        return None
    answer = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == user_message.conversation_id,
                Message.role == MessageRole.ASSISTANT.value,
                Message.created_at >= user_message.created_at,
            )
            .order_by(Message.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if answer is None or not (answer.content or "").strip():
        return None
    return user_message, answer


async def _ensure_conversation(
    db: AsyncSession, req: ChatStreamRequest, user: User | None
) -> Conversation:
    if req.conversation_id:
        conversation = await db.get(Conversation, req.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if user is not None and conversation.user_id and str(conversation.user_id) != str(user.id):
            raise HTTPException(status_code=403, detail="无权访问该会话")
        return conversation

    conversation = Conversation(
        user_id=user.id if user else None,
        anonymous_id=None if user else uuid.uuid4().hex,
        agent_code=req.agent_code,
        title=req.message[:40],
        channel="web",
        context={"product_id": str(req.context.product_id) if req.context.product_id else None},
    )
    db.add(conversation)
    await db.flush()
    return conversation


def _replay_stream(
    answer: Message, conversation_id: uuid.UUID, trace_id: str | None
) -> AsyncIterator[str]:
    """重放上次结果：结构与正常流一致，只是没有真实生成。"""

    async def gen() -> AsyncIterator[str]:
        yield encode_event(
            "meta",
            {
                "conversation_id": str(conversation_id),
                "message_id": str(answer.id),
                "trace_id": trace_id or answer.trace_id or "",
                "replayed": True,
            },
        )
        for citation in answer.citations or []:
            yield encode_event("citation", citation)
        yield encode_event("delta", {"text": answer.content})
        yield encode_event(
            "done",
            {
                "message_id": str(answer.id),
                "latency_ms": answer.latency_ms or 0,
                "usage": answer.usage or {"input_tokens": 0, "output_tokens": 0, "cost": 0},
                "citations": answer.citations or [],
                "contributors": answer.contributors or [],
                "guardrail": {"passed": True, "flags": ["replayed"]},
                "suggested_actions": [],
                "replayed": True,
            },
        )

    return gen()


async def _runtime_events(runtime: ChatRuntime, ctx: TurnContext) -> AsyncIterator[SSEEvent]:
    """把运行时的异常再兜一层，保证生成器不会以异常收尾。"""
    try:
        async for event in runtime.run_turn(ctx):
            yield event
    except Exception as exc:  # noqa: BLE001
        logger.exception("对话流异常")
        yield error_event("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", retryable=True)


@router.post("/stream")
async def chat_stream(
    req: ChatStreamRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    role = current_user.role.value if current_user else VISITOR_ROLE

    allowed, _count = await rate_limit_hit(
        f"rl:chat:{_client_key(request, current_user)}:{int(time.time() // 60)}",
        limit=settings.chat_rate_limit_per_minute,
        window_seconds=60,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"对话过于频繁（每分钟 {settings.chat_rate_limit_per_minute} 次），请稍后再试",
        )

    agent = await _get_agent_or_403(db, req.agent_code, role)
    client_message_id = req.client_message_id or uuid.uuid4().hex

    replay = await _find_replay(db, client_message_id)
    if replay is not None:
        user_message, answer = replay
        logger.info("幂等重放 client_message_id=%s message=%s", client_message_id, answer.id)
        return StreamingResponse(
            _replay_stream(answer, user_message.conversation_id, answer.trace_id),
            media_type="text/event-stream",
            headers=sse_headers(),
        )

    runtime = get_chat_runtime()

    # supervisor 路由要花一次模型调用（约 0.5~1s）。它决定「没 @ 时该问谁」，
    # 不做就只能永远直连主 Agent——那样 Agent 广场的多 Agent 能力等于没有入口。
    route_llm = None
    if settings.supervisor_enabled and settings.llm_configured:
        try:
            route_llm = get_chat_client(temperature=0)
        except LLMNotConfigured:
            route_llm = None

    async def event_stream() -> AsyncIterator[str]:
        terminated = False
        sink = get_trace_sink()
        try:
            with sink.trace(
                "chat.turn",
                user_id=str(current_user.id) if current_user else None,
                tags=["chat", f"agent:{agent.code}", f"role:{role}"],
                metadata={"mentions": [m.agent_code for m in req.mentions]},
            ) as trace:
                async with AsyncSessionLocal() as sdb:
                    conversation = await _ensure_conversation(sdb, req, current_user)
                    history = await _history(sdb, conversation.id)

                    assistant = Message(
                        conversation_id=conversation.id,
                        role=MessageRole.ASSISTANT.value,
                        agent_code=agent.code,
                        content="",
                        trace_id=trace.trace_id,
                    )
                    sdb.add(assistant)
                    sdb.add(
                        Message(
                            conversation_id=conversation.id,
                            role=MessageRole.USER.value,
                            content=req.message,
                            mentions=req.mention_dicts(),
                            client_message_id=client_message_id,
                        )
                    )
                    await sdb.commit()
                    await sdb.refresh(assistant)

                    yield encode_event(
                        "meta",
                        {
                            "conversation_id": str(conversation.id),
                            "message_id": str(assistant.id),
                            "trace_id": trace.trace_id,
                            "replayed": False,
                        },
                    )

                    ctx = TurnContext(
                        db=sdb,
                        request=TurnRequest(
                            message=req.message,
                            agent_code=agent.code,
                            mentions=req.mention_dicts(),
                            role=role,
                            user_id=current_user.id if current_user else None,
                            conversation_id=conversation.id,
                            product_id=req.context.product_id,
                            order_id=req.context.order_id,
                            history=history,
                        ),
                        trace=trace,
                        route_llm=route_llm,
                    )

                    done_data: dict[str, Any] = {}
                    try:
                        async for event in _runtime_events(runtime, ctx):
                            if event.event == "done":
                                done_data = {**event.data, "message_id": str(assistant.id)}
                                yield encode_event("done", done_data)
                                terminated = True
                                continue
                            if event.event == "error":
                                terminated = True
                            yield event.encode()
                    finally:
                        # 无论正常结束还是中断，都把已生成内容落库：
                        # 中断时至少会话历史里还能看到「答到一半」的内容
                        try:
                            assistant.content = ctx.answer or ""
                            assistant.citations = done_data.get("citations") or ctx.citations
                            assistant.contributors = done_data.get("contributors") or ctx.contributors
                            assistant.tool_calls = [
                                call for draft in ctx.drafts for call in draft.tool_calls
                            ]
                            assistant.latency_ms = int(
                                (time.perf_counter() - ctx.started_at) * 1000
                            )
                            assistant.usage = done_data.get("usage") or {}
                            await sdb.commit()
                        except Exception:  # noqa: BLE001
                            logger.exception("回答落库失败 conversation=%s", conversation.id)
                            await sdb.rollback()
        except Exception as exc:  # noqa: BLE001 —— 响应头已经发出，只能发 error 帧
            logger.exception("对话端点异常")
            if not terminated:
                yield error_event("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", retryable=True).encode()
        finally:
            if not terminated:
                logger.warning("对话流未发出终止帧，补发 error")
                yield error_event("STREAM_ABORTED", "生成中断，请重试", retryable=True).encode()

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=sse_headers())
