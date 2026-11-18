"""并发压测（M4-08，PRD FR9.1）。

```powershell
# 默认：20 个请求 / 5 并发，问一句话，统计端到端与首字延迟
$env:PYTHONPATH="backend"; .venv/Scripts/python -X utf8 script/loadtest.py

# 演示「50 并发」门槛：先临时放开限流（默认 20 次/分钟/人）
$env:CHAT_RATE_LIMIT_PER_MINUTE="999"
.venv/Scripts/python -X utf8 script/loadtest.py --n 50 --c 50 --question "花红片怎么吃"
```

读法：

- **首字延迟**（TTFT）看的是「用户多久看到第一个字」，和并发强相关；
- **端到端**包含完整生成，主要受模型速度限制；
- **429** 是限流命中，不是故障：压测前把 ``CHAT_RATE_LIMIT_PER_MINUTE`` 调大，
  否则统计里会混进一堆 429（脚本会把它们单独计数并提示）。
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from typing import Any

import httpx


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * ratio
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


async def one_request(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    question: str,
    index: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    first_token_ms: float | None = None
    chunks: list[bytes] = []
    status = 0
    try:
        async with client.stream(
            "POST",
            f"{base_url}/api/chat/stream",
            json={
                "agent_code": "drug_consult",
                "conversation_id": None,
                "client_message_id": f"load-{index}-{time.time_ns()}",
                "message": question,
                "mentions": [],
                "context": {},
            },
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
            timeout=180,
        ) as response:
            status = response.status_code
            if status != 200:
                await response.aread()
                return {"status": status, "ttft_ms": None, "total_ms": None}
            async for chunk in response.aiter_bytes():
                if first_token_ms is None and b"event: delta" in chunk:
                    first_token_ms = (time.perf_counter() - started) * 1000
                chunks.append(chunk)
    except Exception as exc:  # noqa: BLE001 —— 压测里单条失败不该中断整轮
        return {"status": 0, "ttft_ms": None, "total_ms": None, "error": str(exc)}

    body = b"".join(chunks)
    return {
        "status": status,
        "ttft_ms": first_token_ms,
        "total_ms": (time.perf_counter() - started) * 1000,
        "done": b"event: done" in body,
    }


async def main_async(args: argparse.Namespace) -> int:
    async with httpx.AsyncClient(timeout=180) as client:
        users = ["patient", "doctor", "admin", "support"]
        tokens: list[str] = []
        for username in users:
            response = await client.post(
                f"{args.base_url}/api/auth/login",
                data={"username": username, "password": "123456"},
            )
            if response.status_code == 200:
                tokens.append(response.json()["access_token"])
        if not tokens:
            print("登录失败：先确认后端在跑")
            return 1

    semaphore = asyncio.Semaphore(max(1, args.c))
    results: list[dict[str, Any]] = []

    async def worker(index: int) -> None:
        token = tokens[index % len(tokens)]
        async with semaphore:
            async with httpx.AsyncClient(timeout=180) as client:
                results.append(
                    await one_request(client, args.base_url, token, args.question, index)
                )

    started = time.perf_counter()
    await asyncio.gather(*(worker(index) for index in range(args.n)))
    wall = time.perf_counter() - started

    ok = [item for item in results if item.get("status") == 200]
    rate_limited = [item for item in results if item.get("status") == 429]
    failed = [item for item in results if item.get("status") not in (200, 429)]
    ttfbs = [item["ttft_ms"] for item in ok if item.get("ttft_ms")]
    totals = [item["total_ms"] for item in ok if item.get("total_ms")]

    print(f"\n=== 压测结果（n={args.n}，并发={args.c}，总耗时 {wall:.1f}s）===")
    print(f"成功          {len(ok)}")
    print(f"被限流 429    {len(rate_limited)}")
    print(f"失败          {len(failed)}")
    if rate_limited:
        print("  提示：把 CHAT_RATE_LIMIT_PER_MINUTE 调大再压，否则数字里混着限流")
    if ttfbs:
        print(f"首字 p50/p95  {percentile(ttfbs, 0.5):.0f}ms / {percentile(ttfbs, 0.95):.0f}ms")
    if totals:
        print(
            f"端到端 p50/p95 {statistics.median(totals):.0f}ms / {percentile(totals, 0.95):.0f}ms"
            f"（max {max(totals):.0f}ms）"
        )
        print(f"吞吐          {len(ok) / wall:.2f} req/s")
    if failed:
        print("失败样例：", failed[:3])

    target = 6000
    if totals and percentile(totals, 0.95) > target:
        print(f"\n! 端到端 p95 超过 {target}ms 目标（低配机器/冷启动会偏高，写进 README 的实测口径）")
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="对话接口并发压测")
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--c", type=int, default=5)
    parser.add_argument("--question", default="花红片怎么吃")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
