import asyncio

from langchain_core.documents import Document

from app.services.vector_store import add_documents, get_vector_store, search_documents


async def main():
    collection = "test_kb"

    # 1. 写入测试文档
    docs = [
        Document(page_content="高血压患者禁止服用含有麻黄碱的感冒药。", metadata={"source": "test"}),
        Document(page_content="服用头孢类抗生素期间严禁饮酒。", metadata={"source": "test"}),
    ]
    ids = await add_documents(collection, docs)
    print(f"[写入成功] 文档数量: {len(ids)}")

    # 2. 相似度检索
    results = await search_documents(collection, "高血压感冒不能吃什么", top_k=2)
    print(f"[检索结果] 命中 {len(results)} 条：")
    for doc in results:
        print(f"  - {doc.page_content}")

    # 3. 触发一次 get_vector_store，确认 collection 可访问
    get_vector_store(collection)
    print(f"[Collection] {collection} 已就绪")


if __name__ == "__main__":
    asyncio.run(main())
