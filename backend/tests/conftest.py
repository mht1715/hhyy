"""公共测试夹具（M0-07）。

约定：

- **单元测试不连任何外部服务**（LLM / Milvus / PG / Langfuse），一律用
  ``app.testing.fakes`` 里的替身；
- 需要真实依赖的测试打 ``@pytest.mark.integration``，默认跳过，
  用 ``RUN_INTEGRATION=1 pytest`` 打开。
"""

import os

import pytest

from app.core.config import settings
from app.observability.langfuse_client import reset_observability_cache
from app.observability.tracing import reset_trace_sink_cache
from app.testing.fakes import FakeLLM, FakeTraceSink


def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_INTEGRATION") == "1":
        return
    skip_integration = pytest.mark.skip(reason="集成测试默认跳过，设置 RUN_INTEGRATION=1 开启")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM(reply="ok")


@pytest.fixture
def trace_sink() -> FakeTraceSink:
    return FakeTraceSink()


@pytest.fixture
def no_langfuse(monkeypatch):
    """强制关闭观测并清空单例 + 环境变量，避免用例之间串味。"""
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    monkeypatch.setattr(settings, "langfuse_base_url", "")
    reset_trace_sink_cache()
    reset_observability_cache()
    yield
    reset_trace_sink_cache()
    reset_observability_cache()
