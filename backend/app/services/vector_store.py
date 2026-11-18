from langchain_milvus import Milvus
from langchain_core.documents import Document
from app.core.config import settings
from app.llm.client import get_embedding_client


def get_vector_store(collection_name: str) -> Milvus:
    """获取指定 Collection 的 Milvus 向量存储实例。"""
    return Milvus(
        embedding_function=get_embedding_client(),
        collection_name=collection_name,
        connection_args={"uri": settings.milvus_uri},
        auto_id=True,
    )


async def add_documents(collection_name: str, documents: list[Document]) -> list[str]:
    """向指定 Collection 批量写入文档，返回写入的 ID 列表。"""
    store = get_vector_store(collection_name)
    return await store.aadd_documents(documents)


async def search_documents(collection_name: str, query: str, top_k: int = 4) -> list[Document]:
    """在指定 Collection 中做相似度检索。"""
    store = get_vector_store(collection_name)
    return await store.asimilarity_search(query, k=top_k)
