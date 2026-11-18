"""SSE 编码与兜底（M2-05）。

协议见 PRD §7.2 / ``docs/接口契约-M2.md``。这一层只做两件事：

1. 把 ``(event, data)`` 编成合法的 SSE 帧；
2. **保证流一定会结束**——无论业务抛什么异常，客户端要么收到 ``error``，要么收到
   ``done``，绝不会「连接一直开着但什么都不来」。这是流式接口最容易翻车的地方，
   而前端对此几乎无法自愈（只能等超时）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable

logger = logging.getLogger(__name__)

# 正常结束的两种事件：出现任意一个，本次流就不该再有后续事件
TERMINAL_EVENTS = frozenset({"done", "error"})


def encode_event(event: str, data: dict[str, Any]) -> str:
    """编成 SSE 帧。``json.dumps`` 用 ``ensure_ascii=False``，中文别被转成 \\uXXXX。"""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@dataclass(slots=True)
class SSEEvent:
    event: str
    data: dict[str, Any]

    def encode(self) -> str:
        return encode_event(self.event, self.data)

    @property
    def terminal(self) -> bool:
        return self.event in TERMINAL_EVENTS


def sse_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        # 让 Nginx 之类的反代不要缓冲，否则「流式」会变成「一次性返回」
        "X-Accel-Buffering": "no",
        "Content-Type": "text/event-stream; charset=utf-8",
    }


def error_event(code: str, message: str, *, retryable: bool = False) -> SSEEvent:
    return SSEEvent("error", {"code": code, "message": message, "retryable": retryable})


async def to_sse(
    events: AsyncIterator[SSEEvent],
    *,
    trace_id: str | None = None,
) -> AsyncIterator[str]:
    """把事件流编码成字符串流，并兜住所有异常。

    - 业务异常 → ``error`` 帧（``retryable`` 按异常类型粗判）；
    - 业务忘了发终止事件 → 补一个 ``error``，而不是让前端傻等；
    - 已经发过 ``done``/``error`` 之后的事件一律丢弃（避免出现两个终止帧）。
    """
    terminated = False
    try:
        async for item in events:
            if terminated:
                logger.debug("SSE 终止后仍有事件被丢弃：%s", item.event)
                continue
            yield item.encode()
            if item.terminal:
                terminated = True
    except Exception as exc:  # noqa: BLE001 —— 这里就是最后一道防线
        logger.exception("SSE 流异常终止 trace=%s", trace_id)
        if not terminated:
            retryable = type(exc).__name__ in {
                "TimeoutError",
                "ReadTimeout",
                "ConnectError",
                "APIConnectionError",
                "APITimeoutError",
            }
            yield error_event("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", retryable=retryable).encode()
            terminated = True
    finally:
        if not terminated:
            logger.warning("SSE 流没有终止事件，补发 error。trace=%s", trace_id)
            yield error_event("STREAM_ABORTED", "生成中断，请重试", retryable=True).encode()


def collect_event_names(events: Iterable[SSEEvent]) -> list[str]:
    """测试用：校验事件顺序。"""
    return [item.event for item in events]
