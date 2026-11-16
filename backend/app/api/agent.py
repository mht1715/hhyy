from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from app.api.deps import AdminOrDoctor
from app.core.config import settings
from app.models import User
from app.schemas.agent_parse import AgentProductParse
from app.schemas.response import ResponseModel
import os

router = APIRouter()


class ParseRequest(BaseModel):
    text: str


@router.post("/parse-product", response_model=ResponseModel[dict])
async def parse_product(req: ParseRequest, current_user: User = AdminOrDoctor):
    api_key = settings.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="未配置 DEEPSEEK_API_KEY")

    llm = ChatOpenAI(
        model=settings.deepseek_chat_model,
        api_key=api_key,
        base_url=settings.deepseek_base_url,
        temperature=0
    )

    parser = JsonOutputParser(pydantic_object=AgentProductParse)

    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一个医药电商后台的数据录入助手。请从用户的输入中提取药品信息，并严格按照 JSON 格式输出。\n"
                   "【强制规则】：\n"
                   "1. 药品分类必须从以下选项选：妇科用药、骨骼肌肉系统用药、呼吸系统用药、消化系统用药、儿科用药、皮肤科用药、大健康产品。\n"
                   "2. 剂型必须从名称或说明中推断（如：颗粒、片剂、胶囊、酊剂、丸剂等）。\n"
                   "3. 如果输入了【成份】或【用法用量】，请将它们合并到【precautions】（注意事项）字段中，格式为：'成份：xxx。用法用量：xxx。'\n"
                   "4. 必须提取【批准文号】。\n"
                   "5. 对于未提及的字段保留 null。\n"
                   "{format_instructions}\n\n"
                   "【参考示例】：\n"
                   "用户输入：感冒清热颗粒。成份：荆芥穗。功能主治：疏风散寒。用法用量：开水冲服。规格：12g*10袋。批准文号：国药准字Z11020361。有效期：36个月。禁忌：尚不明确。不良反应：偶见皮疹。生产企业：北京同仁堂。价格15，原价20，库存200。\n"
                   "你的输出：\n"
                   "```json\n"
                   "{{\n"
                   "  \"name\": \"感冒清热颗粒\",\n"
                   "  \"generic_name\": \"感冒清热颗粒\",\n"
                   "  \"category\": \"呼吸系统用药\",\n"
                   "  \"dosage_form\": \"颗粒剂\",\n"
                   "  \"spec\": \"12g*10袋\",\n"
                   "  \"price\": 15,\n"
                   "  \"original_price\": 20,\n"
                   "  \"stock\": 200,\n"
                   "  \"indications\": \"疏风散寒。\",\n"
                   "  \"precautions\": \"成份：荆芥穗。用法用量：开水冲服。\",\n"
                   "  \"shelf_life\": \"36个月\",\n"
                   "  \"contraindications\": \"尚不明确\",\n"
                   "  \"adverse_reactions\": \"偶见皮疹\",\n"
                   "  \"manufacturer\": \"北京同仁堂\",\n"
                   "  \"approval_number\": \"国药准字Z11020361\"\n"
                   "}}\n"
                   "```\n"),
        ("human", "{text}")
    ])

    prompt = prompt.partial(format_instructions=parser.get_format_instructions())
    chain = prompt | llm | parser

    try:
        result = chain.invoke({"text": req.text})
        result = {k: v for k, v in result.items() if v is not None}
        return ResponseModel(data=result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Agent 解析失败: {str(e)}")
