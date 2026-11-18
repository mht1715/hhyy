"""模型客户端工厂。

全项目**只允许**从这里取模型实例，禁止在 API 层直接 new
``ChatOpenAI``/``OpenAIEmbeddings``，否则配置、超时、重试策略会散落各处。

凭据缺失时不抛导入期异常（保证服务能起、健康检查可用），而是在真正取实例时
抛 :class:`LLMNotConfigured`，由调用方转成 503。
"""

from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings


class LLMNotConfigured(RuntimeError):
    """缺少必需的模型凭据。"""


def _require(value: str, name: str) -> str:
    if not value:
        raise LLMNotConfigured(f"未配置 {name}，请在 .env 中补齐")
    return value


@lru_cache(maxsize=16)
def get_chat_client(
    temperature: float | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """获取对话模型实例。

    :param temperature: 覆盖默认温度（默认取 ``settings.llm_temperature``）。
    :param model: 覆盖默认模型（默认取 ``settings.deepseek_chat_model``）。
    :param max_tokens: 硬性截断输出长度。多 Agent 汇总场景必须给上限——
        没有上限时模型会把两段结论各自展开，首屏延迟直接翻倍。
    """
    kwargs: dict[str, object] = {}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(
        model=model or settings.deepseek_chat_model,
        api_key=_require(settings.deepseek_api_key, "DEEPSEEK_API_KEY"),
        base_url=settings.deepseek_base_url,
        temperature=settings.llm_temperature if temperature is None else temperature,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
        **kwargs,
    )


@lru_cache(maxsize=1)
def get_embedding_client() -> OpenAIEmbeddings:
    """获取 DashScope 兼容模式的嵌入模型实例。"""
    return OpenAIEmbeddings(
        model=settings.dashscope_embedding_model,
        api_key=_require(settings.dashscope_api_key, "DASHSCOPE_API_KEY"),
        base_url=settings.dashscope_base_url,
        dimensions=settings.embedding_dimensions,
        check_embedding_ctx_length=False,
        chunk_size=settings.embedding_batch_size,
    )
