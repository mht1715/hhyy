"""M0-06 验收：观测必须「一键关闭」，且关闭/故障时行为与不存在时完全一致。

这里不联网：用 stub client 验证降级路径，用 monkeypatch 验证选择逻辑。
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.observability.langfuse_client import reset_observability_cache
from app.observability.tracing import (
    LangfuseTraceSink,
    NoopTraceSink,
    get_trace_sink,
    reset_trace_sink_cache,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_trace_sink_cache()
    reset_observability_cache()
    yield
    reset_trace_sink_cache()
    reset_observability_cache()


@pytest.fixture
def blank_langfuse(monkeypatch):
    for name in ("langfuse_public_key", "langfuse_secret_key", "langfuse_base_url"):
        monkeypatch.setattr(settings, name, "")


def test_blank_config_degrades_to_noop(blank_langfuse):
    sink = get_trace_sink()

    assert isinstance(sink, NoopTraceSink)
    assert sink.callbacks() == []


def test_partial_config_is_still_disabled(blank_langfuse, monkeypatch):
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")

    assert settings.observability_enabled is False
    assert isinstance(get_trace_sink(), NoopTraceSink)


def test_noop_sink_is_transparent(blank_langfuse):
    sink = get_trace_sink()

    with sink.trace("chat.turn", user_id="u1", session_id="c1", tags=["drug"]) as ctx:
        assert ctx.trace_id  # 没有后端也要有 id，便于日志串联
        with sink.span(ctx, "retrieval"):
            pass
        sink.score(ctx, "user_feedback", 1.0)

    sink.flush()


def test_noop_sink_does_not_swallow_business_error(blank_langfuse):
    sink = get_trace_sink()

    with pytest.raises(RuntimeError, match="boom"):
        with sink.trace("agent.parse_product"):
            raise RuntimeError("boom")


def test_langfuse_sink_selected_when_configured(monkeypatch):
    """配了 key 就该选真 sink；用 stub client 避免真实网络。"""
    monkeypatch.setattr(
        "app.observability.tracing.get_langfuse",
        lambda: object(),
    )

    assert isinstance(get_trace_sink(), LangfuseTraceSink)


class _BrokenClient:
    """模拟 Langfuse 挂了：一进 span 就抛异常。"""

    def start_as_current_observation(self, **kwargs):
        raise RuntimeError("langfuse down")

    def propagate_attributes(self, **kwargs):
        raise RuntimeError("langfuse down")

    def get_current_trace_id(self):
        return None

    def create_score(self, **kwargs):
        raise RuntimeError("langfuse down")

    def flush(self):
        raise RuntimeError("langfuse down")


def test_langfuse_sink_degrades_gracefully_when_client_broken():
    sink = LangfuseTraceSink(_BrokenClient())

    with sink.trace("chat.turn", user_id="u1") as ctx:
        assert ctx.trace_id  # 降级后仍有 id
        with sink.span(ctx, "child"):
            pass
        sink.score(ctx, "user_feedback", 1.0)

    sink.flush()  # 不抛异常
    assert isinstance(sink.callbacks(), list)


def test_langfuse_sink_still_propagates_business_error():
    sink = LangfuseTraceSink(_BrokenClient())

    with pytest.raises(ValueError, match="business"):
        with sink.trace("chat.turn"):
            raise ValueError("business")
