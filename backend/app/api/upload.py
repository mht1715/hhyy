"""药品主图上传。

这个接口之前是坏的，而且坏得很隐蔽——文件写盘成功，接口却返回 500：

1. 声明了 ``response_model=UploadResponse``（顶层 ``url``），实际返回的是
   ``ResponseModel`` 外壳 ``{code, message, data:{url}}``。FastAPI 响应校验不通过，
   直接 500，前端只能弹「图片上传失败」，但 ``static/uploads`` 里已经躺了一个文件。
2. URL 用 ``os.path.join`` 拼，Windows 上得到 ``/static/uploads\\xxx.png``，
   浏览器/路由都对不上，即使上传成功图片也显示不出来。
3. 上传目录是相对路径，取决于启动时的工作目录（``backend/`` 或仓库根）。
   换个启动方式就写到别处去了。

现在：目录按文件位置定位、URL 一律正斜杠、顺带加上扩展名与体积校验。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.media import ALLOWED_IMAGE_EXT, MAX_IMAGE_BYTES, UPLOAD_ROOT
from app.schemas.response import ResponseModel

router = APIRouter()


class UploadedImage(BaseModel):
    url: str


@router.post("/", response_model=ResponseModel[UploadedImage])
async def upload_image(file: UploadFile = File(...)):
    """接收一张药品图片，返回可直接放进 ``<img src>`` 的站内地址。

    只校验扩展名和体积，不做内容嗅探——这是演示项目，但「非图片后缀」和
    「几十 MB 的文件」必须挡住，否则 ``static/`` 就成了公开网盘。
    """
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_IMAGE_EXT:
        allowed = "/".join(sorted(ALLOWED_IMAGE_EXT))
        raise HTTPException(400, f"只支持 {allowed} 格式的图片")

    content = await file.read()
    if not content:
        raise HTTPException(400, "文件内容为空，请重新选择图片")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(400, f"图片不能超过 {MAX_IMAGE_BYTES // (1024 * 1024)}MB")

    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    (UPLOAD_ROOT / stored_name).write_bytes(content)

    # 正斜杠是硬要求：这个值会被原样存进 products.image_url 并渲染到 <img>
    return ResponseModel(data={"url": f"/static/uploads/{stored_name}"})


__all__ = ["router", "upload_image"]
