from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.core.database import get_db
from app.core.config import settings
from app.models.product import Product
from app.schemas.agent_chat import DrugChatRequest
from app.schemas.response import ResponseModel
from app.api.deps import AnyUser
from app.models.user import User
import os

router = APIRouter()


@router.post("/drug-consult", response_model=ResponseModel[dict])
async def drug_consult(
        req: DrugChatRequest,
        db: AsyncSession = Depends(get_db),
        # current_user: User = AnyUser # 如果你要强制登录，可以放开这行，否则游客也能问
):
    # 1. 查数据库，获取该药品的说明书内容
    result = await db.execute(select(Product).where(Product.id == req.product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="药品不存在")

    # 2. 准备大模型
    api_key = settings.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY")
    llm = ChatOpenAI(
        model=settings.deepseek_chat_model,
        api_key=api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.3
    )

    # 3. 核心：构造带有药品说明书的 System Prompt
    # 将药品信息直接作为 Context 塞给大模型，这就是最简单的 RAG
    system_prompt = f"""你是一个专业的医药电商在线药师。当前用户正在咨询以下药品：
【药品名称】{product.name}
【通用名】{product.generic_name}
【功能主治】{product.indications}
【禁忌】{product.contraindications}
【注意事项】{product.precautions}
【不良反应】{product.adverse_reactions}
【用法用量】{product.spec} (请结合常识回答，若不知具体用量请建议查看说明书)

【回答规则】：
1. 必须严格基于上述说明书信息回答，绝不编造。
2. 语气要温和、专业，起到安抚用户的作用。
3. 如果用户问的问题超出该药品范围，或者涉及严重疾病，必须提示：“建议您前往正规医院就诊，听从医生专业指导。”
"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", req.message)
    ])

    chain = prompt | llm

    try:
        # 调用大模型
        response = await chain.ainvoke({"message": req.message})

        return ResponseModel(data={
            "reply": response.content,
            "agent_name": "DrugConsultAgent"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 药师思考失败: {str(e)}")
