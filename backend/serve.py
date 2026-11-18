"""启动入口（Windows 友好）。

为什么不能直接 ``uvicorn app.main:app``：uvicorn 0.36+ 的
``asyncio_loop_factory(use_subprocess=False)`` 在 Windows 上返回
``ProactorEventLoop``；而 psycopg（LangGraph checkpointer 的驱动）在 Proactor 上
会直接抛 ``InterfaceError``，checkpointer 就永远是「不可用」。

两种绕法这里都做了：

- ``RELOAD=1``：走 uvicorn 自带 reload（子进程 ``use_subprocess=True`` → Selector）；
- 否则自己建一个 ``SelectorEventLoop`` 跑 ``Server.serve()``，不经过 uvicorn 的工厂。

用法::

    python serve.py                 # 127.0.0.1:8000
    $env:PORT=8013; python serve.py
    $env:RELOAD=1; python serve.py  # 开发热重载

``script/dev.ps1 backend`` 走的就是这个入口。
"""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
RELOAD = os.getenv("RELOAD") == "1"


def main() -> None:
    if RELOAD:
        # reload 模式下 uvicorn 用子进程，工厂会给 SelectorEventLoop
        uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
        return

    config = uvicorn.Config("app.main:app", host=HOST, port=PORT)
    server = uvicorn.Server(config)

    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.serve())
        finally:
            loop.close()
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
