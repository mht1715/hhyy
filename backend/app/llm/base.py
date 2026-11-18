"""模型调用层的最小契约。

真实实现见 :mod:`app.llm.client`（封装 langchain_openai.ChatOpenAI /
OpenAIEmbeddings）；测试中可用 :class:`app.testing.fakes.FakeLLM` 替换，
避免单测依赖外部 API。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, Sequence, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """对话模型契约：一次调用 + 一次流式调用。"""

    async def ainvoke(self, messages: Sequence[Any], **kwargs: Any) -> Any:
        """同步语义的调用，返回 AIMessage（或等价对象，取其 .content）。"""
        ...

    def astream(self, messages: Sequence[Any], **kwargs: Any) -> AsyncIterator[Any]:
        """流式调用，逐块产出 AIMessageChunk（或等价对象）。"""
        ...


@runtime_checkable
class EmbeddingClient(Protocol):
    """嵌入模型契约。"""

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def aembed_query(self, text: str) -> list[float]: ...
