"""静态资源路径与图片地址的小工具。

集中在这里的原因：上传（写入）、静态挂载（读取）、接口序列化（输出）三处都要用
同一个「backend/static 在哪」和同一套「URL 长什么样」，否则很容易出现
「上传成功但访问 404」「路径里有反斜杠导致图片裂开」这类只在真机才暴露的问题。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# app/core/media.py -> app/core -> app -> backend/
BACKEND_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = BACKEND_ROOT / "static"
UPLOAD_ROOT = STATIC_ROOT / "uploads"

# 药片主图允许的扩展名（前端 van-uploader 直接传原文件，不转码）
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def normalize_image_url(value: Optional[str]) -> Optional[str]:
    """把 Windows 反斜杠路径纠正成 URL 用的正斜杠。

    历史数据里存在 ``/static/uploads\\xxx.png``：那是 ``os.path.join`` 在 Windows
    上拼出来的。浏览器会把它当成非法字符（部分浏览器会静默改写，部分直接不解码），
    服务端也匹配不到这个路径，表现就是「图片怎么都显示不出来」。

    读取时纠正、不回写数据库——同一条数据被不同入口读到时都能正常显示。
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    return text.replace("\\", "/")


__all__ = [
    "ALLOWED_IMAGE_EXT",
    "BACKEND_ROOT",
    "MAX_IMAGE_BYTES",
    "STATIC_ROOT",
    "UPLOAD_ROOT",
    "normalize_image_url",
]
