"""评估 runner（M4-02，PRD FR7.6）。

一条命令输出五个指标 + 失败样例清单：

```powershell
# 检索模式（默认）：只跑检索，不调生成模型，50 条约 1~2 分钟
$env:PYTHONPATH="backend"; .venv/Scripts/python -X utf8 tests/eval/run_eval.py

# 全链路模式：真正调用 /api/chat/stream（要有后端在跑），并可让模型判 faithfulness
.venv/Scripts/python -X utf8 tests/eval/run_eval.py --mode full --limit 10 --judge
```

为什么默认是「检索模式」：50 条全链路跑一遍要 5~8 分钟、要花钱；日常回归只关心
recall / 拒答有没有掉。全链路留给发版前跑一次。

指标口径：

- **recall@5**：top-5 片段里命中 `expect_docs` 任一篇的用例比例。
- **MRR**：第一个命中期望文档的排名倒数（1/rank）的均值，衡量「排得够不够前」。
- **refusal_accuracy**：拒答判定与 `should_refuse` 一致的比例。
  检索模式用 `RetrievalResult.refused`，全链路模式用回答文本（`looks_like_refusal`）。
- **citation_precision**：全链路模式下「引用到的文档中属于期望文档」的比例。
- **faithfulness**：全链路 + `--judge` 时，让模型判断「回答里的断言能否在引用片段里找到依据」。

结果会写进 `eval_runs` 表（`--no-save` 可关），看板读最新一条。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "script" / "eval_cases.json"


# --------------------------------------------------------------------------- 数据
def load_cases(limit: int | None = None) -> list[dict[str, Any]]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = list(payload.get("cases") or [])
    if limit:
        cases = cases[:limit]
    return cases


def first_hit_rank(titles: list[str], expected: list[str]) -> int | None:
    """返回第一条命中期望文档的排名（1 起）；没命中返回 None。"""
    wanted = {title for title in expected if title}
    for rank, title in enumerate(titles, start=1):
        if title in wanted:
            return rank
    return None


def mrr_value(rank: int | None) -> float:
    return 1.0 / rank if rank else 0.0


def mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


# --------------------------------------------------------------------------- 检索模式
async def run_retrieval(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal
    from app.rag.retriever import get_retrieval_service

    service = get_retrieval_service()
    recalls: list[float] = []
    mrrs: list[float] = []
    refusals: list[float] = []
    failures: list[dict[str, Any]] = []
    started = time.perf_counter()

    async with AsyncSessionLocal() as db:
        for case in cases:
            question = case["question"]
            result = await service.retrieve(
                db,
                question,
                role=case.get("role") or "patient",
                kb_ids=None,
                # 不进检索日志：评估会产生大量非真实流量，不能污染「零召回榜」
                write_log=False,
            )
            titles = [chunk.doc_title for chunk in result.chunks]
            rank = first_hit_rank(titles, case.get("expect_docs") or []) if case.get("expect_docs") else None
            expected_refuse = bool(case.get("should_refuse"))
            refused = bool(result.refused)

            hit = 1.0 if (expected_refuse and refused) or (not expected_refuse and rank) else 0.0
            recalls.append(hit)
            if case.get("expect_docs") and not expected_refuse:
                mrrs.append(mrr_value(rank))
            refusals.append(1.0 if refused == expected_refuse else 0.0)

            if hit == 0.0:
                failures.append(
                    {
                        "id": case["id"],
                        "question": question,
                        "expected_docs": case.get("expect_docs") or [],
                        "expected_refuse": expected_refuse,
                        "got_refused": refused,
                        "reason": result.reason,
                        "top_titles": titles[:3],
                        "top_score": round(result.top_score, 4),
                        "threshold": result.threshold,
                    }
                )

    elapsed = time.perf_counter() - started
    return {
        "mode": "retrieval",
        "cases": len(cases),
        "metrics": {
            "recall_at_5": mean(recalls),
            "mrr": mean(mrrs),
            "refusal_accuracy": mean(refusals),
            "citation_precision": None,
            "faithfulness": None,
            "answer_pass_rate": None,
            "elapsed_seconds": round(elapsed, 1),
        },
        "failures": failures,
    }


# --------------------------------------------------------------------------- 全链路模式
async def _login(client: Any, base_url: str, username: str) -> str:
    response = await client.post(
        f"{base_url}/api/auth/login", data={"username": username, "password": "123456"}
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    name = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:") and name:
            try:
                events.append((name, json.loads(line[5:].strip())))
            except ValueError:
                continue
    return events


async def _ask(client: Any, base_url: str, token: str, case: dict[str, Any]) -> dict[str, Any]:
    async with client.stream(
        "POST",
        f"{base_url}/api/chat/stream",
        json={
            "agent_code": case.get("agent_code") or "drug_consult",
            "conversation_id": None,
            "client_message_id": f"eval-{case['id']}-{time.time_ns()}",
            "message": case["question"],
            "mentions": [],
            "context": {},
        },
        headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        timeout=120,
    ) as response:
        chunks = [chunk async for chunk in response.aiter_bytes()]
    events = _parse_sse(b"".join(chunks).decode())
    answer = "".join(data.get("text", "") for name, data in events if name == "delta")
    done = next((data for name, data in events if name == "done"), {})
    return {"answer": answer, "done": done}


async def judge_faithfulness(answer: str, citations: list[dict[str, Any]]) -> float | None:
    """让模型判定「回答里的断言能否在引用片段里找到依据」，返回 0~1。"""
    if not answer.strip() or not citations:
        return None
    evidence = "\n\n".join(
        f"[{item.get('index')}] {item.get('doc_title')}\n{item.get('snippet') or ''}"
        for item in citations
    )
    prompt = (
        "你是严格的医药资料评审。判断下面【回答】里的每个事实性断言，是否都能在【资料片段】里找到依据。\n"
        "不要用外部知识补充，也不要因为「听起来合理」就算有依据。\n"
        '只输出 JSON：{"supported": <整数>, "total": <断言总数>}\n\n'
        f"【资料片段】\n{evidence}\n\n【回答】\n{answer[:1500]}"
    )
    try:
        from app.llm.client import get_chat_client

        # judge 是「加分项」：模型调用必须有超时，否则一条卡住会把整轮评估拖死。
        # 45s 是给「前一轮生成把配额打满、judge 被限流重试」留的余量。
        response = await asyncio.wait_for(
            get_chat_client(temperature=0).ainvoke(prompt), timeout=45
        )
        text = str(getattr(response, "content", "") or "")
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start : end + 1])
        total = int(data.get("total") or 0)
        supported = int(data.get("supported") or 0)
        if total <= 0:
            return None
        return round(min(1.0, supported / total), 4)
    except Exception:  # noqa: BLE001 —— judge 失败不该让评估整体失败
        return None


async def run_full(
    cases: list[dict[str, Any]], *, base_url: str, use_judge: bool
) -> dict[str, Any]:
    import httpx

    recalls: list[float] = []
    mrrs: list[float] = []
    refusals: list[float] = []
    citation_scores: list[float] = []
    answer_scores: list[float] = []
    faith_scores: list[float] = []
    judge_targets: list[tuple[str, list[dict[str, Any]]]] = []
    failures: list[dict[str, Any]] = []
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=120) as client:
        tokens = {
            "patient": await _login(client, base_url, "patient"),
            "support": await _login(client, base_url, "support"),
        }
        for case in cases:
            token = tokens.get(case.get("role") or "patient", tokens["patient"])
            started_case = time.perf_counter()
            try:
                result = await _ask(client, base_url, token, case)
            except Exception as exc:  # noqa: BLE001
                failures.append({"id": case["id"], "question": case["question"], "reason": f"请求失败：{exc}"})
                recalls.append(0.0)
                refusals.append(0.0)
                continue

            answer = result["answer"]
            done = result["done"]
            citations = list(done.get("citations") or [])
            cited_titles = [str(item.get("doc_title") or "") for item in citations]

            from app.guardrail.compliance import looks_like_refusal

            refused = looks_like_refusal(answer) or not answer.strip()
            expected_refuse = bool(case.get("should_refuse"))
            rank = first_hit_rank(cited_titles, case.get("expect_docs") or []) if case.get("expect_docs") else None

            ok = (refused == expected_refuse) and (
                expected_refuse or not case.get("expect_docs") or rank is not None
            )
            recalls.append(1.0 if ok else 0.0)
            if case.get("expect_docs") and not expected_refuse:
                mrrs.append(mrr_value(rank))
            refusals.append(1.0 if refused == expected_refuse else 0.0)

            if citations:
                expected = set(case.get("expect_docs") or [])
                if expected:
                    citation_scores.append(
                        len([title for title in cited_titles if title in expected]) / len(cited_titles)
                    )

            must_include = case.get("must_include") or []
            must_not = case.get("must_not_include") or []
            passed = all(token in answer for token in must_include) and not any(
                token in answer for token in must_not
            )
            answer_scores.append(1.0 if passed else 0.0)

            if use_judge and not expected_refuse:
                # judge 放到 httpx 客户端关闭之后统一跑：两者共用一个事件循环时，
                # 在 stream 客户端上下文里调 LLM 会偶发挂住（实测 20s 超时）
                judge_targets.append((answer, citations))

            if not ok or not passed:
                failures.append(
                    {
                        "id": case["id"],
                        "question": case["question"],
                        "expected_docs": case.get("expect_docs") or [],
                        "expected_refuse": expected_refuse,
                        "got_refused": refused,
                        "cited_titles": cited_titles[:3],
                        "guardrail": done.get("guardrail"),
                        "answer_head": answer[:180],
                        "elapsed_ms": int((time.perf_counter() - started_case) * 1000),
                    }
                )

    # judge 统一在 httpx 客户端关闭后跑（见上面 judge_targets 的注释）
    for answer, citations in judge_targets:
        score = await judge_faithfulness(answer, citations)
        if score is not None:
            faith_scores.append(score)

    elapsed = time.perf_counter() - started
    return {
        "mode": "full",
        "cases": len(cases),
        "metrics": {
            "recall_at_5": mean(recalls),
            "mrr": mean(mrrs),
            "refusal_accuracy": mean(refusals),
            "citation_precision": mean(citation_scores) if citation_scores else None,
            "faithfulness": mean(faith_scores) if faith_scores else None,
            "answer_pass_rate": mean(answer_scores) if answer_scores else None,
            "elapsed_seconds": round(elapsed, 1),
        },
        "failures": failures,
    }


# --------------------------------------------------------------------------- 落库 / 输出
async def save_run(report: dict[str, Any], *, notes: str = "") -> str | None:
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.eval import EvalRun

        async with AsyncSessionLocal() as db:
            row = EvalRun(
                mode=report["mode"],
                cases=report["cases"],
                metrics=report["metrics"],
                failures=report["failures"][:50],
                notes=notes,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return str(row.id)
    except Exception as exc:  # noqa: BLE001 —— 落库失败不影响本次评估结果
        print(f"! 结果没写进 eval_runs：{exc}", file=sys.stderr)
        return None


def print_report(report: dict[str, Any], run_id: str | None) -> None:
    metrics = report["metrics"]

    def fmt(value: Any, percent: bool = False) -> str:
        if value is None:
            return "-"
        return f"{value * 100:.1f}%" if percent else f"{value:.4f}"

    print("\n=== 评估结果（{}，{} 条）===".format(report["mode"], report["cases"]))
    print(f"recall@5          {fmt(metrics['recall_at_5'])}")
    print(f"MRR               {fmt(metrics['mrr'])}")
    print(f"拒答准确率        {fmt(metrics['refusal_accuracy'])}")
    print(f"引用准确率        {fmt(metrics['citation_precision'])}")
    print(f"faithfulness      {fmt(metrics['faithfulness'])}")
    if metrics.get("answer_pass_rate") is not None:
        print(f"答案断言通过率    {fmt(metrics['answer_pass_rate'])}")
    print(f"耗时              {metrics.get('elapsed_seconds')}s")
    if run_id:
        print(f"已写入 eval_runs  {run_id}")

    failures = report["failures"]
    print(f"\n失败样例（{len(failures)} 条，最多展示 10 条）：")
    for item in failures[:10]:
        print(
            f"  - [{item['id']}] {item['question']}\n"
            f"      期望文档={item.get('expected_docs')} 期望拒答={item.get('expected_refuse')}"
            f" 实际拒答={item.get('got_refused')} 引用={item.get('cited_titles') or item.get('top_titles')}"
            f" 原因={item.get('reason') or ''}"
        )


async def _run(args: argparse.Namespace, cases: list[dict[str, Any]]) -> dict[str, Any]:
    if args.mode == "full":
        report = await run_full(cases, base_url=args.base_url, use_judge=args.judge)
    else:
        report = await run_retrieval(cases)
    if not args.no_save:
        report["run_id"] = await save_run(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="M4 评估 runner")
    parser.add_argument("--mode", choices=["retrieval", "full"], default="retrieval")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="full 模式的后端地址")
    parser.add_argument("--judge", action="store_true", help="full 模式：让模型判定 faithfulness")
    parser.add_argument("--json", default="", help="把完整结果写到这个文件")
    parser.add_argument("--no-save", action="store_true", help="不写 eval_runs 表")
    args = parser.parse_args()

    cases = load_cases(args.limit or None)
    if not cases:
        print("没有评估用例", file=sys.stderr)
        return 1

    # 评估与落库必须在**同一个事件循环**里跑：asyncpg 的连接池绑定创建它的事件循环，
    # 两次 asyncio.run 会让第二次拿到已关闭循环上的连接（报 'NoneType' has no attribute 'send'）。
    report = asyncio.run(_run(args, cases))
    run_id = report.pop("run_id", None)
    print_report(report, run_id)

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"完整结果已写入 {args.json}")

    # CI 里可以按指标卡门：recall 掉到 0.8 以下就返回非 0
    return 0 if report["metrics"]["recall_at_5"] >= 0.8 else 2


if __name__ == "__main__":
    raise SystemExit(main())
