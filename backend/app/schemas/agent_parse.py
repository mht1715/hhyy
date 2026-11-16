from pydantic import BaseModel, Field
from typing import Optional


class AgentProductParse(BaseModel):
    name: Optional[str] = Field(None, description="商品名称，如：花红消肿止痛酊")
    generic_name: Optional[str] = Field(None, description="通用名，如：消肿止痛酊")
    category: Optional[str] = Field(None,
                                    description="药品分类，必须从以下选项中选择：妇科用药、骨骼肌肉系统用药、呼吸系统用药、消化系统用药、儿科用药、皮肤科用药、大健康产品")
    price: Optional[float] = Field(None, description="现价/到手价，数字")
    original_price: Optional[float] = Field(None, description="原价/划线价，数字")
    stock: Optional[int] = Field(None, description="库存数量")
    spec: Optional[str] = Field(None, description="规格，如：45ml、0.5g*24片")
    indications: Optional[str] = Field(None, description="适应症/功能主治")
    contraindications: Optional[str] = Field(None, description="禁忌")
    precautions: Optional[str] = Field(None, description="注意事项")
    manufacturer: Optional[str] = Field(None, description="生产企业")
