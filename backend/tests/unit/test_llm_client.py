"""M0-01 验收：模型实例必须来自统一工厂，模型名与温度取自配置。"""

import pytest

from app.core.config import settings
from app.llm.client import LLMNotConfigured, get_chat_client


@pytest.fixture(autouse=True)
def clear_factory_cache():
    """lru_cache + monkeypatch 会串味，每个用例前后都清一次。"""
    get_chat_client.cache_clear()
    yield
    get_chat_client.cache_clear()


def _model_of(client) -> str | None:
    return getattr(client, "model_name", None) or getattr(client, "model", None)


def test_uses_configured_model_and_temperature(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    monkeypatch.setattr(settings, "deepseek_chat_model", "deepseek-test")

    client = get_chat_client(temperature=0)

    assert _model_of(client) == "deepseek-test"
    assert client.temperature == 0


def test_temperature_defaults_to_settings(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_temperature", 0.7)

    assert get_chat_client().temperature == 0.7


def test_missing_key_raises_instead_of_crashing_import(monkeypatch):
    """凭据缺失应在「取实例」时报错，而不是让整个服务起不来。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    with pytest.raises(LLMNotConfigured):
        get_chat_client()
