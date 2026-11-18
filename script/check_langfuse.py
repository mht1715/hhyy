"""Langfuse 连通性自检。

用法（在项目根目录）::

    python script/check_langfuse.py

它会：
1. 打印当前是否启用（由 .env 的 LANGFUSE_* 决定）
2. 调一次 auth_check（需要真实 key 与网络）
3. 发一条 demo trace 并打印 trace_id / 本地视图 URL，然后 flush

注意：``get_trace_url()`` 会同步请求 Langfuse API，所以只在此类运维脚本中使用，
不要放进请求路径。
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.observability.langfuse_client import get_langfuse  # noqa: E402


def main() -> int:
    print(f"[check] LANGFUSE_BASE_URL = {settings.langfuse_base_url or '(未配置)'}")
    print(f"[check] observability_enabled = {settings.observability_enabled}")

    client = get_langfuse()
    if client is None:
        print("[check] 未启用 Langfuse，跳过（服务仍可正常运行）")
        return 0

    try:
        ok = client.auth_check()
        print(f"[check] auth_check = {ok}")
    except Exception as exc:  # noqa: BLE001
        print(f"[check] auth_check 失败：{exc}")
        return 1

    with client.start_as_current_observation(name="check.langfuse", as_type="span"):
        with client.start_as_current_observation(name="child.step", as_type="span"):
            pass
        trace_id = client.get_current_trace_id()

    client.flush()
    print(f"[check] demo trace_id = {trace_id}")
    try:
        print(f"[check] 本地视图：{client.get_trace_url(trace_id=trace_id)}")
    except Exception as exc:  # noqa: BLE001
        print(f"[check] 获取 trace URL 失败（不影响上报）：{exc}")
    print("[check] 完成。请到 Langfuse 控制台确认存在 trace 'check.langfuse'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
