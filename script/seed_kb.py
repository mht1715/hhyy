"""知识库 seed 数据（M1-18）：4 个库 + 12 篇文档，一条命令跑完到 ready。

```bash
python script/seed_kb.py          # 幂等：已存在的库/文档跳过
python script/seed_kb.py --reset  # 删掉这 4 个库重建（含向量）
```

内容刻意做成「有真有假」的样子：药品说明书按真实说明书的小节结构写，
售后政策写成条款体，客服 SOP 写成对话体——这样检索时不同 chunk 策略的效果差异
能被看出来（说明书 structured 效果明显，话术 recursive 更合适）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, select

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.kb import (  # noqa: E402
    DocumentStatus,
    KbDocument,
    KbRolePermission,
    KnowledgeBase,
)
from app.models.user import User  # noqa: E402
from app.rag.acl import invalidate_acl  # noqa: E402
from app.rag.indexer import index_document, storage_root  # noqa: E402
from app.rag.milvus_repo import get_milvus_repo  # noqa: E402

KB_SPECS = [
    {
        "code": "kb_company",
        "name": "企业介绍与品牌故事",
        "description": "花红药业公司简介、品牌故事、社会责任，面向全部用户（含游客）",
        "visibility": "public",
        "chunk_strategy": "recursive",
        # 阈值是标定出来的，不是拍的：同一批 query 下「无关问题」最高约 0.31、
        # 「相关问题」约 0.39~0.94。0.35 卡在两者之间（详见 docs/任务清单.md 进度记录）。
        "score_threshold": 0.35,
        "roles": ["visitor", "patient", "doctor", "support", "admin"],
    },
    {
        "code": "kb_drug_manual",
        "name": "药品说明书",
        "description": "在售药品的说明书原文，按【成份】【禁忌】【用法用量】等小节切分",
        "visibility": "private",
        "chunk_strategy": "structured",
        "score_threshold": 0.40,
        "roles": ["patient", "doctor", "support", "admin"],
    },
    {
        "code": "kb_after_sale",
        "name": "订单与售后政策",
        "description": "退换货、配送时效、发票与售后流程。游客不可见",
        "visibility": "private",
        "chunk_strategy": "structured",
        "score_threshold": 0.40,
        "roles": ["patient", "doctor", "support", "admin"],
    },
    {
        "code": "kb_sop",
        "name": "客服 SOP 与话术库",
        "description": "内部客服标准话术、投诉升级流程。仅客服坐席与管理员可见",
        "visibility": "private",
        "chunk_strategy": "recursive",
        "score_threshold": 0.40,
        "roles": ["support", "admin"],
    },
]

DOCS: dict[str, list[dict[str, str]]] = {
    "kb_company": [
        {
            "title": "花红药业企业简介",
            "filename": "company.md",
            "content": """# 花红药业企业简介

## 企业概况
花红药业是一家专注于妇科、骨科用药的现代中药企业，总部位于广西柳州。公司拥有
片剂、胶囊剂、酊剂等多条生产线，核心产品包括花红片、花红胶囊、花红消肿止痛酊。

## 质量理念
公司坚持「药材好，药才好」的理念，从道地药材种植基地到成品出厂建立全流程质量控制，
所有车间通过国家 GMP 认证。

## 研发与专利
公司设有省级技术中心，围绕妇科炎症、跌打损伤等适应症持续投入循证研究，
拥有多项发明专利。
""",
        },
        {
            "title": "花红品牌故事",
            "filename": "brand.md",
            "content": """# 花红品牌故事

## 名字的由来
「花红」取自广西民间对当地草本植物的称呼，也寓意女性健康与红润气色。
品牌创立之初，创始人走遍桂北山区收集民间验方，最终形成了今天的花红片组方。

## 品牌主张
花红主张「专业、温和、可信赖」。我们相信，妇科用药既要有疗效，也要讲究温和，
因此产品在组方和工艺上都尽量避免对胃肠与肝肾的额外负担。

## 用户承诺
1. 说明书信息完整公开，不隐瞒不良反应与禁忌；
2. 客服药师团队提供 8:00-22:00 在线咨询；
3. 所有药品支持批次溯源查询。
""",
        },
        {
            "title": "社会责任与公益项目",
            "filename": "csr.md",
            "content": """# 社会责任与公益项目

## 女性健康公益行
自 2015 年起，公司在广西、贵州、云南的乡镇开展「女性健康公益行」，累计义诊
超过 300 场，免费发放健康手册 20 万册。

## 药材助农
公司在融水、三江等地建立药材种植合作社，以保底价收购，带动当地农户增收。

## 安全用药科普
官网与公众号长期连载「安全用药 100 问」，内容由执业药师审校，
不发布任何夸大疗效的宣传。
""",
        },
    ],
    "kb_drug_manual": [
        {
            "title": "花红片说明书",
            "filename": "huahongpian.md",
            "content": """【药品名称】通用名称：花红片。

【成份】一点红、白花蛇舌草、地桃花、白背叶根、鸡血藤、桃金娘根、菥蓂。辅料为淀粉、硬脂酸镁。

【性状】本品为薄膜衣片，除去包衣后显棕褐色；味微苦。

【功能主治】清热解毒，燥湿止带，祛瘀止痛。用于湿热瘀滞所致带下病、月经不调，
症见带下量多、色黄质稠、小腹隐痛、腰骶酸痛、经行腹痛；慢性盆腔炎、附件炎见上述证候者。

【用法用量】口服。一次 4 片，一日 3 次，7 天为一疗程。

【不良反应】偶见胃部不适、恶心、皮疹。症状明显者应停药并咨询医师。

【禁忌】孕妇及哺乳期妇女禁用。对本品成分过敏者禁用。

【注意事项】
1. 忌食辛辣、生冷、油腻食物。
2. 患有糖尿病或其他慢性病者应在医师指导下服用。
3. 服药 7 天症状无缓解，应去医院就诊。
4. 本品不宜长期服用。

【贮藏】密封，置阴凉干燥处。

【有效期】36 个月。
""",
        },
        {
            "title": "花红胶囊说明书",
            "filename": "huahongjiaonang.md",
            "content": """【药品名称】通用名称：花红胶囊。

【成份】一点红、白花蛇舌草、地桃花、白背叶根、鸡血藤、桃金娘根、菥蓂。

【性状】本品为硬胶囊，内容物为棕褐色粉末；味微苦。

【功能主治】清热解毒，燥湿止带，祛瘀止痛。用于湿热瘀滞所致的带下病、月经不调。

【用法用量】口服。一次 3 粒，一日 3 次。

【不良反应】少数患者服药后出现轻度腹泻，停药后可自行缓解。

【禁忌】孕妇及哺乳期妇女禁用。

【注意事项】
1. 服药期间忌食辛辣、生冷食物。
2. 儿童、年老体弱者应在医师指导下服用。
3. 对本品过敏者禁用，过敏体质者慎用。

【贮藏】密封，置阴凉干燥处。
""",
        },
        {
            "title": "花红消肿止痛酊说明书",
            "filename": "xiaozhongzhitongding.md",
            "content": """【药品名称】通用名称：花红消肿止痛酊。

【成份】大罗伞、小罗伞、九龙川、红花、三七、薄荷脑、樟脑。辅料为乙醇。

【性状】本品为红棕色的澄清液体；气香。

【功能主治】舒筋活络，消肿止痛。用于跌打扭伤、风湿骨痛、腰腿酸痛。

【用法用量】外用。涂擦患处，一日 3 至 4 次。

【不良反应】个别患者用药部位出现皮肤瘙痒、潮红，停药后可缓解。

【禁忌】皮肤破损处禁用；孕妇禁用；对本品及酒精过敏者禁用。

【注意事项】
1. 本品为外用药，禁止内服。
2. 切勿接触眼睛、口腔等黏膜处。
3. 用药部位如有明显灼热感或瘙痒，应停止用药并清洗。
4. 儿童必须在成人监护下使用。

【贮藏】密封，避光，置阴凉处。
""",
        },
        {
            "title": "说明书用药常见问答",
            "filename": "faq.md",
            "content": """【哺乳期能吃花红片吗】不能。花红片说明书【禁忌】明确标注「孕妇及哺乳期妇女禁用」，
哺乳期如需用药请先咨询医师，并评估是否需要暂停哺乳。

【经期能吃吗】经期可以使用，但若经量明显增多应暂停并咨询医师。

【吃了花红片胃不舒服怎么办】建议改为饭后服用；如仍有明显胃部不适、恶心，
应停药并咨询医师或药师。

【花红片能和抗生素一起吃吗】不确定时应咨询医师。抗生素与中成药联用存在相互作用可能，
不建议自行叠加用药。

【小孩能外用消肿止痛酊吗】儿童必须在成人监护下使用，且皮肤破损处禁用。
""",
        },
    ],
    "kb_after_sale": [
        {
            "title": "退换货政策",
            "filename": "refund.md",
            "content": """# 退换货政策

## 七天无理由退货
自签收之日起 7 天内，未拆封且不影响二次销售的药品，支持无理由退货。
**已拆封的药品不支持无理由退货**，这是药品监管要求，不是平台自行设定的门槛。

## 质量问题退换
存在质量问题（包装破损、药品变质、批号异常）的，签收后 30 天内可申请退换，
运费由我们承担，请在申请时上传实物照片。

## 不予退换的情形
1. 已拆封的口服药品；
2. 超过有效期的订单；
3. 因个人储存不当导致变质的；
4. 冷藏药品（如益生菌）签收后不支持退换。

## 退款时效
审核通过后 1-3 个工作日原路退回，银行卡到账时间以发卡行为准。
""",
        },
        {
            "title": "配送与时效说明",
            "filename": "shipping.md",
            "content": """# 配送与时效说明

## 发货时间
现货商品在付款后 24 小时内出库，节假日顺延。预售商品以页面标注为准。

## 配送范围与时效
1. 全国大部分地区 3-5 天送达；
2. 新疆、西藏、内蒙古偏远地区 5-8 天；
3. 港澳台及境外暂不支持配送。

## 运费规则
单笔订单满 99 元包邮，未满 99 元收取 8 元运费。偏远地区加收 10 元。

## 签收提醒
请当面验货。若外包装明显破损，可拒收并联系客服，我们会重新发货。
""",
        },
        {
            "title": "发票与售后流程",
            "filename": "invoice.md",
            "content": """# 发票与售后流程

## 发票
支持电子普通发票，下单时填写抬头与税号，发货后 24 小时内开具并发送至预留邮箱。
暂不支持专用发票。

## 售后申请流程
1. 进入「我的订单」，选择对应订单点击「申请售后」；
2. 选择售后类型（退货/换货/仅退款）并上传凭证；
3. 客服在 24 小时内审核；
4. 审核通过后按短信提示寄回商品；
5. 仓库签收后 1-3 个工作日完成退款或补发。

## 售后时效
质量问题 30 天内受理，无理由退货 7 天内受理，以签收时间为准。
""",
        },
    ],
    "kb_sop": [
        {
            "title": "客服标准话术",
            "filename": "scripts.md",
            "content": """# 客服标准话术（内部资料）

## 开场
「您好，我是花红药业客服，很高兴为您服务。请问有什么可以帮您？」

## 用户询问禁忌/孕妇能否服用
先确认具体药品，再引导用户查看说明书的【禁忌】小节。不得自行判断用户是否可以用药，
统一表述为「说明书标注孕妇及哺乳期妇女禁用，建议您遵医嘱」。
**禁止**说「可以吃」「没问题」这类肯定性结论。

## 用户询问价格优惠
统一回复当前页面价格，不承诺额外折扣。如用户坚持，引导至「转人工」。

## 用户投诉药品无效
先表达理解与歉意，记录用药时间、症状变化，然后升级为投诉工单，不得评价疗效。

## 结束语
「感谢您的咨询，祝您身体健康。如后续还有问题，随时联系我们。」
""",
        },
        {
            "title": "投诉与升级处理流程",
            "filename": "escalation.md",
            "content": """# 投诉与升级处理流程（内部资料）

## 升级触发条件
出现以下任一情况，必须在 3 分钟内转人工并建工单：
1. 用户明确要求投诉或索赔；
2. 用户反馈服用后出现严重不适；
3. 涉及药品质量疑似问题；
4. 用户情绪激动，连续两次表示不满。

## 工单必填字段
订单号、药品名称与批号、问题描述、用户诉求、已沟通内容摘要。

## 严重不良反应处理
立即记录并上报质量部，2 小时内回电用户，告知其携带药品包装前往医院就诊，
并说明我们会配合提供批号溯源信息。

## 交接规范
转人工时必须提供「用户画像 + 已确认事实 + 未解决诉求」三段式摘要，
不得让用户重复描述问题。
""",
        },
    ],
}


async def _upsert_kb(db, spec: dict, *, owner_id, reset: bool) -> KnowledgeBase:
    kb = (
        await db.execute(select(KnowledgeBase).where(KnowledgeBase.code == spec["code"]))
    ).scalar_one_or_none()

    if kb is not None and reset:
        await get_milvus_repo().delete_by_kb(str(kb.id))
        await db.delete(kb)
        await db.commit()
        kb = None

    if kb is None:
        kb = KnowledgeBase(
            code=spec["code"],
            name=spec["name"],
            description=spec["description"],
            visibility=spec["visibility"],
            chunk_strategy=spec["chunk_strategy"],
            score_threshold=spec["score_threshold"],
            status="active",
            owner_id=owner_id,
        )
        db.add(kb)
        await db.commit()
        await db.refresh(kb)
        print(f"  + 建库 {spec['code']}")
    else:
        # 已有库也刷新一遍配置，保证 seed 是可重复执行的
        kb.name = spec["name"]
        kb.description = spec["description"]
        kb.visibility = spec["visibility"]
        kb.chunk_strategy = spec["chunk_strategy"]
        kb.score_threshold = spec["score_threshold"]
        kb.status = "active"
        await db.commit()
    return kb


async def _set_permissions(db, kb: KnowledgeBase, roles: list[str]) -> None:
    await db.execute(delete(KbRolePermission).where(KbRolePermission.kb_id == kb.id))
    for role in roles:
        db.add(KbRolePermission(kb_id=kb.id, role=role, can_read=True))
    await db.commit()


async def _seed_doc(db, kb: KnowledgeBase, spec: dict[str, str]) -> None:
    existing = (
        await db.execute(
            select(KbDocument).where(
                KbDocument.kb_id == kb.id, KbDocument.title == spec["title"]
            )
        )
    ).scalar_one_or_none()

    target_dir = storage_root() / str(kb.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / spec["filename"]
    path.write_text(spec["content"], encoding="utf-8")

    if existing is not None and existing.status == DocumentStatus.READY.value:
        print(f"    = 跳过（已就绪）{spec['title']}")
        return

    if existing is None:
        doc = KbDocument(
            kb_id=kb.id,
            title=spec["title"],
            source_type="md",
            file_path=str(path),
            status=DocumentStatus.PENDING.value,
            last_indexed_offset=0,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
    else:
        doc = existing
        doc.file_path = str(path)
        doc.status = DocumentStatus.PENDING.value
        doc.last_indexed_offset = 0
        await db.commit()

    outcome = await index_document(db, doc.id)
    flag = "ok" if outcome.status == DocumentStatus.READY.value else "FAILED"
    print(f"    {flag:<7}{spec['title']}  chunks={outcome.chunk_count}  {outcome.error or ''}")


async def seed(*, reset: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
        for spec in KB_SPECS:
            print(f"[{spec['code']}] {spec['name']}")
            kb = await _upsert_kb(db, spec, owner_id=admin.id if admin else None, reset=reset)
            await _set_permissions(db, kb, spec["roles"])
            for doc_spec in DOCS[spec["code"]]:
                await _seed_doc(db, kb, doc_spec)
        await invalidate_acl()
    print("\n完成。请用 admin 登录后台 /admin/kb 查看，或用 search-test 验证权限差异。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="知识库 seed 数据")
    parser.add_argument("--reset", action="store_true", help="删除这 4 个库后重建")
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))
