import os
import uuid
from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel

router = APIRouter()

# 定义上传文件的保存目录
UPLOAD_DIR = "static/uploads"
# 确保目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)


class UploadResponse(BaseModel):
    url: str


@router.post("/", response_model=UploadResponse)
async def upload_image(file: UploadFile = File(...)):
    # 获取文件后缀（如 .jpg, .png）
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    # 用 uuid 生成唯一的文件名，防止重名覆盖
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # 将文件写入本地磁盘
    with open(filepath, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    from app.schemas.response import ResponseModel
    return ResponseModel(data={"url": f"/{filepath}"})
