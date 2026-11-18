"""AI 药师（M1-17）：把「整篇说明书塞进 prompt」换成「按问题检索 + 引用 + 拒答」。

对外契约不变：响应里仍有 ``reply`` 与 ``agent_name``，前端一行都不用改。
新增的 ``citations`` / ``refused`` / ``retrieval`` 是纯增量字段。

这次改造解决的是原实现的两个硬伤：
1. 把说明书全文塞进 prompt —— 问题问到「禁忌」时，模型容易把「功能主治」也答进来；
   而且一篇塞满就顶到上下文上限，多文档场景直接崩。
2. 没有拒答 —— 检索不到时模型会自由发挥。医药场景里"编一个禁忌"是执业风险，
   不是体验问题，所以拒答必须是**代码层**的硬约束（阈值 + 空召回），不能指望 prompt。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_optional_user
from app.core.config import settings
from app.core.database import get_db
from app.llm.client import LLMNotConfigured, get_chat_client
from app.models.product import Product
from app.models.user import User
from app.observability.tracing import get_trace_sink
from app.rag.acl import VISITOR_ROLE
from app.rag.citation import refusal_text, sanitize_citations, to_citations
from app.rag.retriever import get_retrieval_service
from app.schemas.agent_chat import DrugChatRequest
from app.schemas.response import ResponseModel

router = APIRouter()

SYSTEM_PROMPT = """你是一个专业、温和的医药电商在线药师，代表「花红药业」与用户沟通。

【参考资料】
{context}

【回答规则】
1. 只能依据上面的参考资料回答。资料里没有的内容，明确说「资料中没有相关信息」，
   绝不猜测、绝不编造用法用量和禁忌。
2. 引用资料时在句末标注角标，例如「孕妇禁用[1]」。角标编号必须来自参考资料。
3. 涉及具体诊断、处方调整、严重不良反应时，提示用户前往正规医院就诊。
4. 语气温和专业，先安抚再给结论，不要用恐吓性表述。
"""


def _summarize(result) -> dict:
    """给前端/SSE 用的检索摘要（不含正文，避免响应体过大）。"""
    return {
        "kb_ids": result.kb_ids,
        "hits": len(result.chunks),
        "top_score": round(result.top_score, 4),
        # 分数口径与判定阈值一起给出，前端才能解释「为什么拒答」
        "threshold": result.threshold,
        "score_source": result.score_source,
        "rewritten_query": result.rewritten_query,
        "filtered_out_kb_ids": result.filtered_out_kb_ids,
    }


@router.post("/drug-consult", response_model=ResponseModel[dict])
async def drug_consult(
    req: DrugChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    started = time.perf_counter()

    # 1. 药品基本信息只用来「确定问的是哪个药」，不再当作知识源
    product = (
        await db.execute(select(Product).where(Product.id == req.product_id))
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="药品不存在")

    role = current_user.role.value if current_user else VISITOR_ROLE
    sink = get_trace_sink()

    with sink.trace(
        "agent.drug_consult",
        user_id=str(current_user.id) if current_user else None,
        tags=["agent:drug_consult", f"role:{role}"],
        metadata={"product_id": str(req.product_id), "query_chars": len(req.message)},
    ) as ctx:
        # 2. 检索：把商品名拼进 query，避免「能吃吗」这种问题丢失主体
        query = f"{product.name} {product.generic_name} {req.message}".strip()
        with sink.span(ctx, "retrieval", as_type="retriever", input=query):
            retrieval = await get_retrieval_service().retrieve(
                db,
                query,
                role=role,
                user_id=current_user.id if current_user else None,
            )

        citations = to_citations(retrieval)
        # 3. 拒答：检索层已经判过（空召回 / 分数低于阈值 / 无权限）
        if retrieval.refused:
            answer = refusal_text(retrieval.reason)
            sink.score(ctx, "answer_refused", 1.0, comment=retrieval.reason)
            return ResponseModel(
                data={
                    "reply": answer,
                    "agent_name": "DrugConsultAgent",
                    "citations": [],
                    "refused": True,
                    "refusal_reason": retrieval.reason,
                    "retrieval": _summarize(retrieval),
                    "trace_id": ctx.trace_id,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
            )

        # 4. 生成
        try:
            llm = get_chat_client(temperature=settings.llm_temperature)
        except LLMNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                ("human", "{message}"),
            ]
        )
        chain = prompt | llm

        with sink.span(ctx, "generation", as_type="generation", input=req.message):
            try:
                response = await chain.ainvoke(
                    {"context": retrieval.as_context(), "message": req.message},
                    config={"callbacks": sink.callbacks()},
                )
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"AI 药师思考失败: {exc}") from exc

        raw_answer = str(getattr(response, "content", "") or "")
        answer, used_citations = sanitize_citations(raw_answer, citations)

        return ResponseModel(
            data={
                "reply": answer,
                "agent_name": "DrugConsultAgent",
                "citations": used_citations,
                "refused": False,
                "retrieval": _summarize(retrieval),
                "trace_id": ctx.trace_id,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        )
