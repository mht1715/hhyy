"""把 golden set 上传成 Langfuse Dataset，并可选择跑一次 experiment（M4-03）。

```powershell
# 只上传（幂等：同名 item 会更新）
$env:PYTHONPATH="backend"; .venv/Scripts/python -X utf8 script/upload_dataset.py

# 上传并跑一次 experiment（会真的调用 /api/chat/stream，花钱）
.venv/Scripts/python -X utf8 script/upload_dataset.py --run --limit 10 --name m4-eval

# 没有配 Langfuse key 时会打印「未启用」并退出 0——评估本身不依赖它
```

为什么用 Dataset + experiment 而不是只本地算分：Langfuse 的 experiment 会把
「一次运行」下的每条 item、每个 score、每次 LLM 调用聚在一起，两次运行能**并排对比**
指标与成本——这正是「prompt 改动可回归」要的证据链。本地 runner（tests/eval）负责
快速回归，这里负责「可展示、可对比」。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "script" / "eval_cases.json"


def load_cases(limit: int | None = None) -> list[dict]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = list(payload.get("cases") or [])
    return cases[:limit] if limit else cases


def to_input(case: dict) -> dict:
    return {
        "question": case["question"],
        "agent_code": case["agent_code"],
        "role": case["role"],
    }


def to_expected(case: dict) -> dict:
    return {
        "docs": case.get("expect_docs") or [],
        "should_refuse": bool(case.get("should_refuse")),
        "must_include": case.get("must_include") or [],
        "must_not_include": case.get("must_not_include") or [],
    }


def upload(client, dataset: str, cases: list[dict]) -> int:
    client.create_dataset(
        name=dataset,
        description="M4 golden set：药品说明书 / 售后 / 企业 / 客服 SOP 四库，含 12 条应拒答",
        metadata={"source": "script/eval_cases.json", "updated_at": datetime.utcnow().isoformat()},
    )
    for case in cases:
        client.create_dataset_item(
            dataset_name=dataset,
            id=case["id"],
            input=to_input(case),
            expected_output=to_expected(case),
            metadata={"agent_code": case["agent_code"], "role": case["role"]},
        )
    return len(cases)


# --------------------------------------------------------------------------- experiment
async def chat_once(base_url: str, token: str, case: dict) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{base_url}/api/chat/stream",
            json={
                "agent_code": case.get("agent_code") or "drug_consult",
                "conversation_id": None,
                "client_message_id": f"exp-{case['id']}-{datetime.utcnow().timestamp()}",
                "message": case["question"],
                "mentions": [],
                "context": {},
            },
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        ) as response:
            body = b"".join([chunk async for chunk in response.aiter_bytes()]).decode()

    events, name = [], ""
    for line in body.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:") and name:
            try:
                events.append((name, json.loads(line[5:].strip())))
            except ValueError:
                continue
    answer = "".join(data.get("text", "") for event, data in events if event == "delta")
    done = next((data for event, data in events if event == "done"), {})
    return {"answer": answer, "citations": done.get("citations") or [], "guardrail": done.get("guardrail")}


async def run_experiment(client, dataset: str, cases: list[dict], *, base_url: str, name: str) -> None:
    import httpx
    from langfuse.experiment import LocalExperimentItem

    async with httpx.AsyncClient(timeout=30) as http:
        tokens = {}
        for role, username in (("patient", "patient"), ("support", "support")):
            response = await http.post(
                f"{base_url}/api/auth/login",
                data={"username": username, "password": "123456"},
            )
            response.raise_for_status()
            tokens[role] = response.json()["access_token"]

    items: list[LocalExperimentItem] = [
        {
            "input": to_input(case),
            "expected_output": to_expected(case),
            "metadata": {"id": case["id"], "agent_code": case["agent_code"]},
        }
        for case in cases
    ]

    async def task(*, item, **kwargs):  # noqa: ANN001, ANN002 —— SDK 约定的签名
        payload = item.input if hasattr(item, "input") else item.get("input")
        case = dict(payload)
        token = tokens.get(payload.get("role") or "patient", tokens["patient"])
        result = await chat_once(base_url, token, case)
        from app.guardrail.compliance import looks_like_refusal

        result["refused"] = looks_like_refusal(result["answer"]) or not result["answer"].strip()
        return result

    def citation_hit(*, input, output, expected_output, metadata=None, **kwargs):  # noqa: ANN001, ANN003
        expected = set((expected_output or {}).get("docs") or [])
        cited = {item.get("doc_title") for item in (output or {}).get("citations") or []}
        if not expected:
            return {"name": "citation_hit", "value": None, "comment": "该条不期望引用"}
        return {
            "name": "citation_hit",
            "value": 1.0 if cited & expected else 0.0,
            "comment": f"引用={sorted(cited)}",
        }

    def refusal_match(*, input, output, expected_output, metadata=None, **kwargs):  # noqa: ANN001, ANN003
        expected = bool((expected_output or {}).get("should_refuse"))
        got = bool((output or {}).get("refused"))
        return {"name": "refusal_match", "value": 1.0 if expected == got else 0.0,
                "comment": f"期望拒答={expected} 实际={got}"}

    result = await client.run_experiment(
        name=name,
        run_name=f"run-{datetime.utcnow().strftime('%m%d-%H%M')}",
        description="M4 golden set 回归（langfuse experiment）",
        data=items,
        task=task,
        evaluators=[citation_hit, refusal_match],
        max_concurrency=4,
    )
    print("\n=== Langfuse experiment 已提交 ===")
    print(f"dataset={dataset} name={name}")
    print(f"items={len(items)} 结果类型={type(result).__name__}")
    print("去 Langfuse 的 Datasets / Experiments 页面即可两次 run 并排对比。")


def main() -> int:
    parser = argparse.ArgumentParser(description="上传 golden set 到 Langfuse Dataset")
    parser.add_argument("--dataset", default="m4-golden-set")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--run", action="store_true", help="上传后跑一次 experiment")
    parser.add_argument("--name", default="m4-eval")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    from app.observability.langfuse_client import get_langfuse

    client = get_langfuse()
    if client is None:
        print("Langfuse 未配置（LANGFUSE_* 三要素缺失），跳过上传。本地评估用 tests/eval/run_eval.py。")
        return 0

    cases = load_cases(args.limit or None)
    count = upload(client, args.dataset, cases)
    client.flush()
    print(f"已上传 {count} 条到 dataset={args.dataset}")

    if args.run:
        asyncio.run(run_experiment(client, args.dataset, cases, base_url=args.base_url, name=args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
