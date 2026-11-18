"""SSE 编码与兜底测试（M2-05）。

验收标准只有一句：**任何异常路径都必须发出 `error` 或 `done`**，不能让前端挂住。
"""

from __future__ import annotations

import json

from app.agent.sse import SSEEvent, encode_event, error_event, sse_headers, to_sse


async def _collect(events) -> list[tuple[str, dict]]:
    frames = [frame async for frame in to_sse(events)]
    parsed: list[tuple[str, dict]] = []
    for frame in frames:
        assert frame.endswith("\n\n")
        name = ""
        data = ""
        for line in frame.strip().split("\n"):
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = line.removeprefix("data: ")
        parsed.append((name, json.loads(data)))
    return parsed


def test_encode_keeps_chinese_readable():
    frame = encode_event("delta", {"text": "孕妇禁用"})
    assert "孕妇禁用" in frame
    assert "\\u" not in frame
    assert frame.startswith("event: delta\n")


def test_headers_disable_buffering():
    headers = sse_headers()
    assert headers["X-Accel-Buffering"] == "no"
    assert "text/event-stream" in headers["Content-Type"]


async def test_normal_stream_passes_through():
    async def gen():
        yield SSEEvent("meta", {"conversation_id": "c1"})
        yield SSEEvent("delta", {"text": "你好"})
        yield SSEEvent("done", {"latency_ms": 1})

    parsed = await _collect(gen())
    assert [name for name, _ in parsed] == ["meta", "delta", "done"]


async def test_exception_becomes_error_frame():
    async def gen():
        yield SSEEvent("meta", {})
        raise RuntimeError("boom")

    parsed = await _collect(gen())
    assert parsed[-1][0] == "error"
    assert parsed[-1][1]["code"] == "INTERNAL_ERROR"


async def test_stream_without_terminal_gets_error():
    async def gen():
        yield SSEEvent("delta", {"text": "半句"})

    parsed = await _collect(gen())
    assert [name for name, _ in parsed] == ["delta", "error"]
    assert parsed[-1][1]["code"] == "STREAM_ABORTED"


async def test_events_after_done_are_dropped():
    async def gen():
        yield SSEEvent("done", {"ok": True})
        yield SSEEvent("delta", {"text": "不该出现"})

    parsed = await _collect(gen())
    assert [name for name, _ in parsed] == ["done"]


async def test_timeout_is_marked_retryable():
    async def gen():
        if False:  # 让这个函数成为 async generator（否则 gen() 是协程）
            yield SSEEvent("never", {})
        raise TimeoutError("慢")

    parsed = await _collect(gen())
    assert parsed[-1][0] == "error"
    assert parsed[-1][1]["retryable"] is True


def test_error_event_shape():
    event = error_event("RATE_LIMITED", "太快了", retryable=True)
    assert event.event == "error"
    assert event.data == {"code": "RATE_LIMITED", "message": "太快了", "retryable": True}
