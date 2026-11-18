"""追踪出口的两种实现：真上报（Langfuse）与 no-op 降级。

业务代码只依赖 ``get_trace_sink()``，不直接 import langfuse——
这样「没配 key」「SDK 挂了」都不会让请求失败。

实现要点：只有 **建立 span 的那一步** 允许吞异常；``yield`` 之后业务抛出的异常
必须原样上抛（否则 contextmanager 会「yield 两次」而崩）。
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextlib import AbstractContextManager, ExitStack, contextmanager, suppress
from functools import lru_cache
from typing import Any, Iterator

from app.observability.base import ObservationType, TraceContext, TraceSink
from app.observability.langfuse_client import get_langfuse

logger = logging.getLogger(__name__)


class NoopTraceSink:
    """不做任何上报，但仍返回合法的 trace_id，便于日志/排障串联。"""

    def trace(
        self,
        name: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[TraceContext]:
        @contextmanager
        def _cm() -> Iterator[TraceContext]:
            yield TraceContext(
                trace_id=uuid.uuid4().hex,
                name=name,
                user_id=user_id,
                session_id=session_id,
                tags=list(tags or []),
                metadata=dict(metadata or {}),
            )

        return _cm()

    def span(
        self,
        ctx: TraceContext,
        name: str,
        *,
        as_type: ObservationType = "span",
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[TraceContext]:
        @contextmanager
        def _cm() -> Iterator[TraceContext]:
            yield ctx

        return _cm()

    def score(
        self,
        ctx: TraceContext,
        name: str,
        value: float | str,
        *,
        comment: str | None = None,
    ) -> None:
        return None

    def callbacks(self) -> list[Any]:
        return []

    def flush(self) -> None:
        return None


class LangfuseTraceSink:
    """Langfuse 5.x 实现。

    - trace 根节点用 ``propagate_attributes`` 挂 user / session / tags
    - 子节点用 ``start_as_current_observation``（OTel 上下文自动嵌套）
    - LangChain 的 ``CallbackHandler`` 会自动在**当前** span 下生成 generation
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._handler: Any | None = None
        self._handler_failed = False

    # ---- LangChain 集成 ----
    def callbacks(self) -> list[Any]:
        if self._handler is None and not self._handler_failed:
            try:
                from langfuse.langchain import CallbackHandler

                # 不传 public_key：按 LANGFUSE_PUBLIC_KEY 解析同一个全局 client
                self._handler = CallbackHandler()
            except Exception:  # noqa: BLE001
                self._handler_failed = True
                logger.exception("LangChain CallbackHandler 初始化失败，本次不采集 LLM 明细")
        return [self._handler] if self._handler is not None else []

    # ---- trace / span ----
    def trace(
        self,
        name: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[TraceContext]:
        client = self._client

        @contextmanager
        def _cm() -> Iterator[TraceContext]:
            ctx = TraceContext(
                trace_id="",
                name=name,
                user_id=user_id,
                session_id=session_id,
                tags=list(tags or []),
                metadata=dict(metadata or {}),
            )
            stack = ExitStack()
            entered = False
            try:
                if user_id or session_id or tags:
                    # langfuse 5.x 里 ``propagate_attributes`` 是**模块级函数**，
                    # 不是 client 的方法（写成 self._client.propagate_attributes 会
                    # AttributeError，然后整条 trace 静默降级成 no-op——M3 联调时才发现）。
                    from langfuse import propagate_attributes

                    stack.enter_context(
                        propagate_attributes(
                            user_id=user_id,
                            session_id=session_id,
                            tags=tags,
                            trace_name=name,
                        )
                    )
                ctx.raw = stack.enter_context(
                    client.start_as_current_observation(
                        name=name,
                        as_type="span",
                        metadata=metadata,
                    )
                )
                ctx.trace_id = client.get_current_trace_id() or ""
                entered = True
            except Exception:  # noqa: BLE001 - 只兜「建 trace 失败」
                logger.exception("Langfuse trace 创建失败，本次降级为 no-op")
                with suppress(Exception):
                    stack.close()
                ctx.trace_id = uuid.uuid4().hex

            try:
                yield ctx
            finally:
                if entered:
                    # sys.exc_info() 在异常传播时给出当前异常，让 span 带上错误状态
                    with suppress(Exception):
                        stack.__exit__(*sys.exc_info())

        return _cm()

    def span(
        self,
        ctx: TraceContext,
        name: str,
        *,
        as_type: ObservationType = "span",
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[TraceContext]:
        client = self._client

        @contextmanager
        def _cm() -> Iterator[TraceContext]:
            stack = ExitStack()
            entered = False
            try:
                stack.enter_context(
                    client.start_as_current_observation(
                        name=name,
                        as_type=as_type,
                        input=input,
                        metadata=metadata,
                    )
                )
                entered = True
            except Exception:  # noqa: BLE001
                logger.exception("Langfuse span 创建失败，本次降级为 no-op")
                with suppress(Exception):
                    stack.close()

            try:
                yield ctx
            finally:
                if entered:
                    with suppress(Exception):
                        stack.__exit__(*sys.exc_info())

        return _cm()

    def score(
        self,
        ctx: TraceContext,
        name: str,
        value: float | str,
        *,
        comment: str | None = None,
    ) -> None:
        if not ctx.trace_id:
            return
        try:
            self._client.create_score(
                trace_id=ctx.trace_id,
                name=name,
                value=value,
                comment=comment,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse score 上报失败")

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse flush 失败")


@lru_cache(maxsize=1)
def get_trace_sink() -> TraceSink:
    """取全局 sink：配置了 Langfuse 就用真的，否则 no-op。"""
    client = get_langfuse()
    if client is None:
        return NoopTraceSink()
    try:
        return LangfuseTraceSink(client)
    except Exception:  # noqa: BLE001
        logger.exception("LangfuseTraceSink 构造失败，降级为 no-op")
        return NoopTraceSink()


def reset_trace_sink_cache() -> None:
    """仅供测试：清掉单例，让下个用例重新判定配置。"""
    get_trace_sink.cache_clear()
