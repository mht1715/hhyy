"""对话流式端点（M2-06 / M3）。

四个必须做对的地方：

1. **流一定要有终止帧**。业务异常、客户端断开、模型超时，最后都要落到 ``error``
   或 ``done``，否则前端只能干等到超时（见 ``app/agent/sse.py``）。
2. **幂等**。同一个 ``client_message_id`` 在窗口内重复提交，直接重放上次结果
   （``done.replayed=true``），不重复调用模型、不重复计费。
3. **流里用独立 DB 会话**。请求级依赖的 session 生命周期由框架控制，长连接流式
   响应期间它可能在流结束前被回收；这里在生成器内部自己开一个 session，避免
   「回答到一半 `session is closed`」这种只在慢网络下复现的问题。
4. **人工接管后 AI 静默**（M3）。``conversation.status == human_active`` 时不再调模型，
   只把用户消息落库 + 广播给坐席，然后回一个 ``silenced=true`` 的终止帧。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.checkpointer import get_checkpointer
from app.agent.registry import get_agent_registry
from app.agent.runtime import ChatRuntime, TurnContext, TurnRequest, get_chat_runtime
from app.agent.sse import SSEEvent, encode_event, error_event, sse_headers
from app.api.auth import get_optional_user
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.redis import rate_limit_hit
from app.llm.client import LLMNotConfigured, get_chat_client
from app.memory.extractor import extract_memories
from app.memory.long_term import PgMemoryStore
from app.memory.short_term import load_history, maybe_summarize
from app.models.agent import Conversation, ConversationStatus, Message, MessageRole
from app.models.handoff import HandoffTicket
from app.models.user import User
from app.observability.tracing import get_trace_sink
from app.rag.acl import VISITOR_ROLE
from app.schemas.chat import ChatStreamRequest
from app.services import handoff as handoff_service
from app.services.support_bus import publish

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


async def _active_ticket(db: AsyncSession, conversation_id: Any) -> Optional[HandoffTicket]:
    return await handoff_service.active_ticket(db, conversation_id)


def _meta_payload(
    conversation: Conversation,
    assistant_id: Any,
    trace_id: str,
    *,
    ticket: Optional[HandoffTicket] = None,
    memory: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "conversation_id": str(conversation.id),
        "message_id": str(assistant_id) if assistant_id else "",
        "trace_id": trace_id,
        "replayed": False,
        "status": conversation.status,
        "memory": memory or {"enabled": False, "count": 0},
        "ticket": handoff_service.ticket_payload(ticket) if ticket else None,
    }


async def _memory_state(db: AsyncSession, user: User | None) -> dict[str, Any]:
    """``meta.memory``：只给「开关 + 条数」，具体记忆条目走 ``memory`` 事件。"""
    if user is None or not settings.memory_enabled:
        return {"enabled": False, "count": 0}
    store = PgMemoryStore(db)
    profile = await store.get_profile(user.id)
    if not profile.enabled:
        return {"enabled": False, "count": 0}
    stats = await store.count_by_type(user.id)
    return {"enabled": True, "count": sum(stats.values())}


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
                "status": "bot_active",
                "memory": {"enabled": False, "count": 0},
                "ticket": None,
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
                "status": "bot_active",
                "ticket": None,
                "silenced": False,
                "memory_used": 0,
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


def _spawn(coro: Any, *, label: str) -> None:
    """后台任务：失败只记日志，绝不影响正在进行的回答。"""
    task = asyncio.create_task(coro)

    def _done(t: asyncio.Task) -> None:
        try:
            exc = t.exception()
        except asyncio.CancelledError:  # pragma: no cover - 进程退出时可能发生
            return
        if exc is not None:
            logger.warning("后台任务 %s 失败：%s", label, exc)

    task.add_done_callback(_done)


async def _background_memory(conversation_id: Any, user_id: Any, message: str, message_id: Any) -> None:
    """一轮结束后的异步记忆工作：滚动摘要 + 长期记忆抽取。

    单独开 session，并逐步 try/except：任何一步失败都不该让「回答已经发完了」这件事
    变成一次 500（前端此时已经渲染完内容了）。
    """
    llm = None
    if settings.llm_configured:
        try:
            llm = get_chat_client(temperature=0)
        except LLMNotConfigured:
            llm = None

    async with AsyncSessionLocal() as db:
        try:
            outcome = await maybe_summarize(db, conversation_id, llm=llm)
            await db.commit()
            if outcome is not None:
                logger.info(
                    "会话 %s 滚动摘要更新到第 %d 条（llm=%s）",
                    conversation_id,
                    outcome.upto,
                    outcome.generated_with_llm,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("滚动摘要失败：%s", exc)
            await db.rollback()

    if not (user_id and settings.memory_extract_enabled):
        return
    async with AsyncSessionLocal() as db:
        try:
            from app.memory.semantic import get_semantic_memory

            store = PgMemoryStore(db, vectors=get_semantic_memory())
            result = await extract_memories(
                store=store,
                user_id=user_id,
                message=message,
                message_id=message_id,
                conversation_id=conversation_id,
                llm=llm,
            )
            await db.commit()
            if result.items:
                logger.info("会话 %s 写入 %d 条记忆", conversation_id, len(result.items))
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆抽取失败：%s", exc)
            await db.rollback()


async def _background_ticket_summary(ticket_id: Any) -> None:
    """用模型把交接摘要润色一遍（失败保留确定性摘要）。"""
    if not settings.llm_configured:
        return
    async with AsyncSessionLocal() as db:
        try:
            ticket = await db.get(HandoffTicket, ticket_id)
            if ticket is None:
                return
            await handoff_service.refresh_summary(db, ticket, llm=get_chat_client(temperature=0))
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("交接摘要润色失败：%s", exc)
            await db.rollback()


async def _persist_user_message(
    db: AsyncSession, conversation: Conversation, req: ChatStreamRequest, client_message_id: str
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        role=MessageRole.USER.value,
        content=req.message,
        mentions=req.mention_dicts(),
        client_message_id=client_message_id,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


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

    # checkpointer 拿不到（没装依赖 / PG 没起 / Windows 事件循环不对）就按无状态跑，
    # 对话必须照常可用——持久化是能力，不是前置条件。
    checkpointer = await get_checkpointer() if settings.checkpointer_enabled else None

    # 会话在进流**之前**解析/创建：非法的 conversation_id 要返回 404/403，
    # 而不是等响应头发出去了才在流里抛异常（那样前端只能看到一条断掉的流）。
    conversation = await _ensure_conversation(db, req, current_user)
    conversation_id = conversation.id
    await db.commit()

    async def event_stream() -> AsyncIterator[str]:
        terminated = False
        sink = get_trace_sink()
        try:
            with sink.trace(
                "chat.turn",
                user_id=str(current_user.id) if current_user else None,
                # session_id = conversation_id：Langfuse 里同一会话的轮次才能串起来
                session_id=str(conversation_id),
                tags=["chat", f"agent:{agent.code}", f"role:{role}"],
                metadata={"mentions": [m.agent_code for m in req.mentions]},
            ) as trace:
                async with AsyncSessionLocal() as sdb:
                    conversation = await sdb.get(Conversation, conversation_id)
                    if conversation is None:
                        yield error_event("NOT_FOUND", "会话不存在", retryable=False).encode()
                        terminated = True
                        return
                    memory_state = await _memory_state(sdb, current_user)

                    # ---- 人工接管后 AI 静默 ----
                    if conversation.status == ConversationStatus.HUMAN_ACTIVE.value:
                        user_message = await _persist_user_message(
                            sdb, conversation, req, client_message_id
                        )
                        ticket = await _active_ticket(sdb, conversation.id)
                        from app.core.timefmt import iso_utc

                        await publish(
                            conversation.id,
                            {
                                "type": "message",
                                "message": {
                                    "id": str(user_message.id),
                                    "role": MessageRole.USER.value,
                                    "content": user_message.content,
                                    "client_message_id": user_message.client_message_id or "",
                                    "created_at": iso_utc(user_message.created_at),
                                },
                            },
                        )
                        yield encode_event(
                            "meta",
                            _meta_payload(
                                conversation,
                                None,
                                trace.trace_id,
                                ticket=ticket,
                                memory=memory_state,
                            ),
                        )
                        yield encode_event(
                            "done",
                            {
                                "message_id": str(user_message.id),
                                # 静默路径没有生成环节，耗时就是一次落库
                                "latency_ms": 0,
                                "usage": {"input_tokens": 0, "output_tokens": 0, "cost": 0},
                                "citations": [],
                                "contributors": [],
                                "guardrail": {"passed": True, "flags": ["silenced"]},
                                "suggested_actions": [],
                                "replayed": False,
                                "status": ConversationStatus.HUMAN_ACTIVE.value,
                                "ticket": handoff_service.ticket_payload(ticket) if ticket else None,
                                "silenced": True,
                                "memory_used": 0,
                            },
                        )
                        terminated = True
                        return

                    history = await load_history(
                        sdb,
                        conversation.id,
                        max_turns=settings.memory_window_turns,
                        budget=settings.memory_history_budget,
                    )

                    # 先把用户消息落库：下面敏感场景建单时要生成交接摘要，
                    # 摘要必须能读到最后这句话（否则坐席只看到「敏感场景」四个字）
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

                    # 敏感场景：在进流之前就把工单建好（坐席端 1 秒内可见），
                    # 而不是等模型写完一轮回答（那要 3~5 秒，投诉场景等不起）。
                    pre_handoff: Optional[dict[str, Any]] = None
                    ticket_id: Any = None
                    if current_user is not None:
                        sensitive, risk_flags = handoff_service.detect_sensitive(req.message)
                        if sensitive:
                            try:
                                ticket, _created = await handoff_service.request_handoff(
                                    sdb,
                                    conversation=conversation,
                                    user_id=current_user.id,
                                    reason="敏感场景，立即转人工",
                                    trigger="sensitive",
                                    risk_flags=risk_flags,
                                )
                                await sdb.commit()
                                await handoff_service.refresh_summary(sdb, ticket)
                                await sdb.commit()
                                pre_handoff = handoff_service.ticket_payload(ticket)
                                ticket_id = ticket.id
                            except Exception as exc:  # noqa: BLE001 —— 建单失败不影响回答
                                logger.warning("敏感场景建单失败：%s", exc)
                                await sdb.rollback()

                    assistant = Message(
                        conversation_id=conversation.id,
                        role=MessageRole.ASSISTANT.value,
                        agent_code=agent.code,
                        content="",
                        trace_id=trace.trace_id,
                    )
                    sdb.add(assistant)
                    await sdb.commit()
                    await sdb.refresh(assistant)

                    ticket = await _active_ticket(sdb, conversation.id)
                    yield encode_event(
                        "meta",
                        _meta_payload(
                            conversation,
                            assistant.id,
                            trace.trace_id,
                            ticket=ticket,
                            memory=memory_state,
                        ),
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
                            history=history.messages,
                            summary=history.summary,
                        ),
                        trace=trace,
                        route_llm=route_llm,
                        checkpointer=checkpointer,
                        status=conversation.status,
                        pre_handoff=pre_handoff,
                    )

                    done_data: dict[str, Any] = {}
                    persisted = False

                    async def persist_answer() -> None:
                        """把这一轮生成的内容写回 assistant 行并提交。"""
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

                    try:
                        async for event in _runtime_events(runtime, ctx):
                            if event.event == "done":
                                done_data = {**event.data, "message_id": str(assistant.id)}
                                # **必须先落库再发 done**：前端收到 done 就会立刻断开，
                                # 连接一断生成器就被取消，之后 finally 里的 await 不会执行——
                                # 结果就是「AI 回答过、刷新后却不见了」
                                await persist_answer()
                                persisted = True
                                yield encode_event("done", done_data)
                                terminated = True
                                continue
                            if event.event == "error":
                                terminated = True
                            yield event.encode()
                    finally:
                        # 兜底：中途断开/异常时也别丢已生成的内容
                        if not persisted:
                            try:
                                await persist_answer()
                            except Exception:  # noqa: BLE001
                                logger.exception("回答落库失败 conversation=%s", conversation.id)
                                await sdb.rollback()

                        # 后台：滚动摘要 / 记忆抽取 / 交接摘要润色（都不阻塞本次响应）
                        if current_user is not None:
                            _spawn(
                                _background_memory(
                                    conversation.id,
                                    current_user.id,
                                    req.message,
                                    assistant.id,
                                ),
                                label="memory",
                            )
                        if ticket_id is not None:
                            _spawn(
                                _background_ticket_summary(ticket_id),
                                label="ticket_summary",
                            )
        except Exception as exc:  # noqa: BLE001 —— 响应头已经发出，只能发 error 帧
            logger.exception("对话端点异常")
            if not terminated:
                yield error_event("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", retryable=True).encode()
        finally:
            if not terminated:
                logger.warning("对话流未发出终止帧，补发 error")
                yield error_event("STREAM_ABORTED", "生成中断，请重试", retryable=True).encode()

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=sse_headers())
