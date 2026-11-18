"""路由测试（M2-04）。

最关键的一条：**有 mentions 时不许调用 LLM**。这是「`@` 可靠」的技术前提——
用户已经用结构化数据表达了意图，再让模型猜一遍只会引入不确定性。
"""

from __future__ import annotations

import json

import pytest

from app.agent.registry import AgentConfig
from app.agent.router import (
    RouteError,
    build_supervisor_prompt,
    decide_route,
    parse_decision,
    resolve_mentions,
)
from app.testing.fakes import FakeLLM


def _agent(code: str, *, roles=("patient", "admin"), kb=("kb_drug_manual",)) -> AgentConfig:
    return AgentConfig(
        code=code,
        name={"drug_consult": "AI 药师", "order_after_sale": "订单售后"}.get(code, code),
        description=f"{code} 的说明",
        kb_codes=list(kb),
        allowed_roles=list(roles),
    )


DRUG = _agent("drug_consult")
ORDER = _agent("order_after_sale", kb=("kb_after_sale",))
REGISTRY = {agent.code: agent for agent in (DRUG, ORDER)}


async def test_explicit_mentions_never_call_llm():
    llm = FakeLLM(reply=json.dumps({"agents": [{"code": "drug_consult"}], "confidence": 0.9}))

    decision = await decide_route(
        message="@订单售后 这单能退吗",
        mentions=[{"agent_code": "order_after_sale", "name": "订单售后", "offset": 0}],
        role="patient",
        registry=REGISTRY,
        primary=DRUG,
        llm=llm,
    )

    assert decision.mode == "mention"
    assert [agent.code for agent in decision.agents] == ["order_after_sale"]
    assert llm.calls == []  # ← 核心断言


async def test_unknown_mention_is_403():
    with pytest.raises(RouteError) as exc:
        await decide_route(
            message="@不存在的 你好",
            mentions=[{"agent_code": "ghost_agent"}],
            role="patient",
            registry=REGISTRY,
            primary=DRUG,
            llm=None,
        )
    assert exc.value.code == "FORBIDDEN_AGENT"


async def test_mention_without_permission_is_403():
    with pytest.raises(RouteError) as exc:
        await decide_route(
            message="@订单售后 在吗",
            mentions=[{"agent_code": "order_after_sale"}],
            role="visitor",
            registry=REGISTRY,
            primary=DRUG,
            llm=None,
        )
    assert exc.value.code == "FORBIDDEN_AGENT"


def test_mentions_are_deduped_and_capped():
    agents = resolve_mentions(
        [{"agent_code": "drug_consult"}, {"agent_code": "drug_consult"}],
        registry=REGISTRY,
        role="patient",
    )
    assert len(agents) == 1


async def test_supervisor_picks_agent_from_json():
    llm = FakeLLM(
        reply="```json\n" + json.dumps(
            {"agents": [{"code": "order_after_sale", "confidence": 0.88}],
             "confidence": 0.88, "rationale": "问的是订单退款"}
        ) + "\n```"
    )
    decision = await decide_route(
        message="我刚买的那单能退吗",
        mentions=[],
        role="patient",
        registry=REGISTRY,
        primary=DRUG,
        llm=llm,
    )

    assert decision.mode == "supervisor"
    assert [agent.code for agent in decision.agents] == ["order_after_sale"]
    assert decision.confidence == pytest.approx(0.88)


async def test_supervisor_low_confidence_asks_for_clarification():
    llm = FakeLLM(reply='{"agents":[{"code":"drug_consult"}],"confidence":0.2,"rationale":"不确定"}')
    decision = await decide_route(
        message="嗯",
        mentions=[],
        role="patient",
        registry=REGISTRY,
        primary=DRUG,
        llm=llm,
    )
    assert decision.mode == "clarify"


async def test_supervisor_garbage_falls_back_to_primary():
    llm = FakeLLM(reply="我觉得应该问药师吧")
    decision = await decide_route(
        message="这个药怎么吃",
        mentions=[],
        role="patient",
        registry=REGISTRY,
        primary=DRUG,
        llm=llm,
    )
    assert decision.mode == "supervisor"
    assert [agent.code for agent in decision.agents] == ["drug_consult"]
    assert decision.confidence == 0.0


async def test_supervisor_ignores_hallucinated_agent_code():
    llm = FakeLLM(reply='{"agents":[{"code":"ghost"}],"confidence":0.9}')
    decision = await decide_route(
        message="你好",
        mentions=[],
        role="patient",
        registry=REGISTRY,
        primary=DRUG,
        llm=llm,
    )
    # 编造的 code 被忽略；没剩下合法目标 → 澄清（而不是 403 用户）
    assert decision.mode == "clarify"


def test_parse_decision_tolerates_noise():
    data = parse_decision('好的，结果如下：\n{"agents": [], "confidence": 0}\n以上。')
    assert data["confidence"] == 0


def test_supervisor_prompt_lists_candidate_codes():
    prompt = build_supervisor_prompt("能退吗", list(REGISTRY.values()))
    assert "order_after_sale" in prompt
    assert "drug_consult" in prompt
    assert "只输出 JSON" in prompt
