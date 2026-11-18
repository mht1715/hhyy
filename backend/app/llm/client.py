from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings


@lru_cache(maxsize=1)
def get_chat_client() -> ChatOpenAI:
    """Deepseek llm模型"""
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.3
    )


@lru_cache(maxsize=1)
def get_embedding_client() -> OpenAIEmbeddings:
    """"DashScope 嵌入模型"""
    return OpenAIEmbeddings(
        model=settings.dashscope_embedding_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        dimensions=settings.embedding_dimensions,
        check_embedding_ctx_length=False,
        chunk_size=10
    )
