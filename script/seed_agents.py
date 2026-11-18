"""Agent 与 Prompt 模板种子数据（M2-01）。

四个 Agent 覆盖三种差异化演示：

- ``drug_consult``（AI 药师）：药品说明书 RAG + 药品查询，全角色可用；
- ``order_after_sale``（订单售后）：订单工具 + 售后政策库，游客不可用；
- ``company_intro``（企业介绍）：``kb_company`` 是 public 库，**游客也能用**；
- ``customer_service``（客服助手）：SOP 内部库，仅 support/admin —— 专门用来演示
  「`@` 候选列表按权限过滤」（患者看不到它）。

幂等：按 code upsert；prompt 按 (code, version) upsert，重复执行不会产生 v2/v3。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import delete, select  # noqa: E402

from app.agent.registry import get_agent_registry  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.agent import Agent, PromptTemplate  # noqa: E402

DRUG_PROMPT = """你是「{agent_name}」，{description}

【参考资料】
{context}

【回答规则】
1. 只能依据参考资料回答。资料里没有的内容，明确说「资料中没有相关信息」，绝不猜测。
2. 引用资料时在句末标注角标，例如「孕妇及哺乳期妇女禁用[1]」。角标编号必须来自参考资料。
3. 涉及诊断、处方调整、严重不良反应时，提示用户前往正规医院就诊。
4. 语气温和专业，先给结论再解释；不要写免责声明（系统会统一追加）。

【当前用户身份】{role}
"""

ORDER_PROMPT = """你是「{agent_name}」，{description}

【参考资料】
{context}

【回答规则】
1. 订单状态、金额、商品以【订单信息】为准，不要臆测；没有订单信息就说「我这边没有查到您的订单」。
2. 退换货规则以参考资料为准，引用时标 [n]。
3. 涉及投诉、赔偿、医疗纠纷时，直接建议转人工，不要自行承诺。
4. 回答简洁，先给结论（能不能退 / 几天到账），再给依据。

【当前用户身份】{role}
"""

INTRO_PROMPT = """你是「{agent_name}」，{description}

【参考资料】
{context}

【回答规则】
1. 只依据参考资料介绍公司，不要编造营收、人数、资质等数字。
2. 引用时标 [n]。
3. 如果问的是具体药品或订单，说明这里只提供企业信息，建议找对应助手。

【当前用户身份】{role}
"""

SERVICE_PROMPT = """你是「{agent_name}」，{description}

【参考资料】
{context}

【回答规则】
1. 依据客服 SOP 回答，引用时标 [n]；SOP 是内部资料，不要把「话术」原样暴露给用户。
2. 遇到投诉、纠纷、赔偿要求，按 SOP 升级流程建议转人工。
3. 语气友好克制，不承诺无法兑现的补偿。

【当前用户身份】{role}
"""

AGENTS: list[dict] = [
    {
        "code": "drug_consult",
        "name": "AI 药师",
        "description": "基于药品说明书回答用法用量、禁忌、不良反应与注意事项",
        "system_prompt_code": "drug_consult",
        "prompt": DRUG_PROMPT,
        "kb_ids": ["kb_drug_manual"],
        "tools": ["kb_search", "product_lookup", "escalate_human"],
        "allowed_roles": ["patient", "doctor", "support", "admin"],
        "handoff_targets": ["order_after_sale", "human_support"],
        "sort_order": 10,
    },
    {
        "code": "order_after_sale",
        "name": "订单售后",
        "description": "查订单状态与物流，回答退换货、退款时效、运费与发票规则",
        "system_prompt_code": "order_after_sale",
        "prompt": ORDER_PROMPT,
        "kb_ids": ["kb_after_sale"],
        "tools": ["order_lookup", "policy_search", "escalate_human"],
        "allowed_roles": ["patient", "doctor", "support", "admin"],
        "handoff_targets": ["human_support"],
        "sort_order": 20,
    },
    {
        "code": "company_intro",
        "name": "企业介绍",
        "description": "介绍花红药业的企业概况、产品线与公益项目（游客可用）",
        "system_prompt_code": "company_intro",
        "prompt": INTRO_PROMPT,
        "kb_ids": ["kb_company"],
        "tools": ["kb_search"],
        "allowed_roles": ["visitor", "patient", "doctor", "support", "admin"],
        "handoff_targets": [],
        "sort_order": 30,
    },
    {
        "code": "customer_service",
        "name": "客服助手",
        "description": "内部客服 SOP：话术规范、投诉升级、交接流程（仅客服/管理员）",
        "system_prompt_code": "customer_service",
        "prompt": SERVICE_PROMPT,
        "kb_ids": ["kb_sop", "kb_company"],
        "tools": ["kb_search", "escalate_human"],
        "allowed_roles": ["support", "admin"],
        "handoff_targets": ["human_support"],
        "sort_order": 40,
    },
]


async def _upsert_prompt(db, code: str, content: str) -> None:
    existing = (
        await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.code == code, PromptTemplate.version == 1
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            PromptTemplate(
                code=code,
                version=1,
                content=content,
                status="production",
                labels=["seed"],
                rollout=100,
                variables_schema={"required": ["context", "role", "agent_name"]},
            )
        )
        print(f"  + prompt {code} v1")
    else:
        existing.content = content
        existing.status = "production"
        print(f"  = prompt {code} v1（更新内容）")
    await db.commit()


async def seed(*, reset: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        if reset:
            await db.execute(delete(Agent))
            await db.execute(delete(PromptTemplate))
            await db.commit()
            print("已清空 agents / prompt_templates")

        for spec in AGENTS:
            await _upsert_prompt(db, spec["system_prompt_code"], spec["prompt"])

            row = (
                await db.execute(select(Agent).where(Agent.code == spec["code"]))
            ).scalar_one_or_none()
            if row is None:
                db.add(
                    Agent(
                        code=spec["code"],
                        name=spec["name"],
                        description=spec["description"],
                        system_prompt_code=spec["system_prompt_code"],
                        temperature=0.3,
                        kb_ids=spec["kb_ids"],
                        tools=spec["tools"],
                        allowed_roles=spec["allowed_roles"],
                        handoff_targets=spec["handoff_targets"],
                        ui_mode="chat",
                        status="active",
                        sort_order=spec["sort_order"],
                    )
                )
                print(f"  + agent {spec['code']}（{spec['name']}）")
            else:
                row.name = spec["name"]
                row.description = spec["description"]
                row.system_prompt_code = spec["system_prompt_code"]
                row.kb_ids = spec["kb_ids"]
                row.tools = spec["tools"]
                row.allowed_roles = spec["allowed_roles"]
                row.handoff_targets = spec["handoff_targets"]
                row.status = "active"
                row.sort_order = spec["sort_order"]
                print(f"  = agent {spec['code']}（更新）")
            await db.commit()

        get_agent_registry().invalidate()

    print("\n完成。查看方式：")
    print("  - 前台：GET /api/agents（游客只看到「企业介绍」）")
    print("  - 后台：GET /api/admin/agents（admin）")
    print("  - 对话：POST /api/chat/stream")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent 与 prompt 种子数据")
    parser.add_argument("--reset", action="store_true", help="清空 agents/prompt_templates 后重建")
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))
