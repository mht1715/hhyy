"""图片上传与路由顺序的回归测试（M5 修复）。

这两个坑都只在「真用」的时候暴露，编译和一键启动都发现不了：

1. 上传接口声明 ``response_model=UploadResponse``，实际返回 ``ResponseModel`` 外壳，
   FastAPI 响应校验失败 → 500。文件已经落盘，前端却只看到「上传失败」。
2. ``/api/orders/admin/all`` 如果排在 ``/api/orders/{order_id}`` 之后，
   ``admin`` 会被当成 UUID 解析 → 422，管理员永远打不开订单管理。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import upload as upload_module
from app.core.media import normalize_image_url


def test_normalize_image_url_fixes_windows_separators():
    assert normalize_image_url("/static/uploads\\a.png") == "/static/uploads/a.png"
    # 已经是正斜杠的不要动，也不要给绝对 URL 加东西
    assert normalize_image_url("https://hhyy.com/x.png") == "https://hhyy.com/x.png"
    assert normalize_image_url("  /static/a.png  ") == "/static/a.png"
    assert normalize_image_url(None) is None
    assert normalize_image_url("") == ""


def _client() -> TestClient:
    # 只挂上传路由：不触发 app.main 的 lifespan（否则会去连 PG / checkpointer）
    app = FastAPI()
    app.include_router(upload_module.router, prefix="/api/upload")
    return TestClient(app)


def test_upload_returns_envelope_with_forward_slash_url(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_module, "UPLOAD_ROOT", tmp_path)
    client = _client()

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    resp = client.post(
        "/api/upload/",
        files={"file": ("药品主图.png", png, "image/png")},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 外壳必须是 {code, message, data}，data.url 是前端 axios 剥壳后拿到的值
    assert body["code"] == 200
    url = body["data"]["url"]
    assert url.startswith("/static/uploads/")
    assert "\\" not in url
    stored = tmp_path / url.rsplit("/", 1)[-1]
    assert stored.is_file()
    assert stored.read_bytes() == png


def test_upload_rejects_non_image_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_module, "UPLOAD_ROOT", tmp_path)
    client = _client()
    resp = client.post("/api/upload/", files={"file": ("shell.exe", b"MZ", "application/octet-stream")})
    assert resp.status_code == 400
    assert "只支持" in resp.json()["detail"]


def test_upload_rejects_empty_file(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_module, "UPLOAD_ROOT", tmp_path)
    client = _client()
    resp = client.post("/api/upload/", files={"file": ("empty.png", b"", "image/png")})
    assert resp.status_code == 400


def test_admin_order_routes_are_declared_before_dynamic_order_id():
    """Starlette 按声明顺序匹配：`/admin/all` 必须排在 `/{order_id}` 前面。

    否则 ``admin`` 会被当成 UUID 去解析，管理员点开订单管理直接 422。
    直接查 APIRouter 的声明顺序（FastAPI 0.163 起 include_router 是懒展开的，
    `app.routes` 里看不到具体路径）。
    """
    from app.api import order as order_api

    paths = [getattr(route, "path", "") for route in order_api.router.routes]
    admin_all = paths.index("/admin/all")
    admin_summary = paths.index("/admin/summary")
    detail = paths.index("/{order_id}")
    assert admin_all < detail
    assert admin_summary < detail
