import asyncio
from app.core.database import AsyncSessionLocal
from app.models.product import Product


async def seed():
    async with AsyncSessionLocal() as db:
        products = [
            Product(
                name="花红消肿止痛酊", generic_name="消肿止痛酊", category="骨骼肌肉系统用药",
                price=15.73, original_price=18.00, stock=1000, spec="45ml", dosage_form="酊剂",
                indications="舒筋活络，消肿止痛。用于跌打扭伤，风湿骨痛。",
                contraindications="孕妇禁用。", precautions="忌用：皮肤破损者。",
                adverse_reactions="尚不明确。",
                approval_number="国药准字Z45021991", manufacturer="广西壮族自治区花红药业集团股份公司",
                image_url="https://hhyy.com/uploadDir/png/20210715/1626312272949.png"
            ),
            Product(
                name="花红片", generic_name="花红片", category="妇科用药",
                price=25.00, original_price=32.00, stock=500, spec="0.29g*36片", dosage_form="片剂",
                indications="清热解毒，燥湿止带，祛瘀止痛。用于湿热瘀滞所致带下病、月经不调。",
                contraindications="孕妇禁用。", precautions="忌食辛辣、生冷、油腻食物。",
                adverse_reactions="尚不明确。",
                approval_number="国药准字Z45021234", manufacturer="广西壮族自治区花红药业集团股份公司",
                image_url="https://hhyy.com/uploadDir/png/20210729/1627543136200.png"
            ),
            Product(
                name="花红胶囊", generic_name="花红胶囊", category="妇科用药",
                price=35.50, original_price=45.00, stock=200, spec="0.25g*36粒", dosage_form="胶囊",
                indications="清热解毒，燥湿止带，祛瘀止痛。用于湿热瘀滞所致带下病。",
                contraindications="孕妇禁用。", precautions="尚不明确。",
                adverse_reactions="尚不明确。",
                approval_number="国药准字Z20050123", manufacturer="广西壮族自治区花红药业集团股份公司",
                image_url="https://hhyy.com/uploadDir/png/20210714/1626254262345.png"
            )
        ]
        db.add_all(products)
        await db.commit()
        print("预置药品数据完成！")


if __name__ == "__main__":
    asyncio.run(seed())
