"""路由（M2-04）：显式 ``@`` 直连 + supervisor 决策。

两条路径的取舍写在 PRD FR1.4：

- **有 mentions 就一定走显式路由**，一次模型调用都不花。这不是优化，是可靠性：
  「用户明确 @ 了谁」是结构化事实，让模型再猜一遍只会引入不确定性。
- **无 mentions 才让模型决策**，并要求输出 JSON（agents / confidence / rationale）。
  解析失败不是错误——退化成「主 Agent 直接答」比抛 500 合理得多。

``RouteDecision.mode == "clarify"`` 表示置信度太低：与其硬猜，不如先问一句或给转人工。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.agent.registry import AgentConfig
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_TARGETS = 2
_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


class RouteError(RuntimeError):
    """路由阶段的可预期失败（伪造 agent_code、无权使用）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class RouteDecision:
    mode: str  # mention | supervisor | clarify
    agents: list[AgentConfig] = field(default_factory=list)
    confidence: float = 1.0
    rationale: str = ""

    def as_event_data(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "agents": [
                {"code": agent.code, "name": agent.name, "role": "contributor"}
                for agent in self.agents
            ],
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
        }


def _dedupe(codes: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for code in codes:
        if code and code not in seen:
            seen.append(code)
    return seen


def resolve_mentions(
    mentions: Sequence[Mapping[str, Any]],
    *,
    registry: Mapping[str, AgentConfig],
    role: str,
) -> list[AgentConfig]:
    """把结构化 mentions 变成 Agent 列表（不存在 / 无权 / 停用 一律 403）。

    注意这里**不看文本**：``@`` 的名字里有空格、用户手打 ``@``、模型自我提及，
    都不该影响路由结果。
    """
    codes = _dedupe([str(item.get("agent_code") or item.get("code") or "") for item in mentions])
    if not codes:
        return []

    resolved: list[AgentConfig] = []
    for code in codes:
        agent = registry.get(code)
        if agent is None or not agent.is_active:
            raise RouteError("FORBIDDEN_AGENT", f"未知或已下线的 Agent：{code}")
        if not agent.allows(role):
            raise RouteError("FORBIDDEN_AGENT", f"当前身份无权使用 {agent.name}")
        resolved.append(agent)
    return resolved[:MAX_TARGETS]


def build_supervisor_prompt(
    message: str,
    candidates: Sequence[AgentConfig],
    history: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    catalogue = "\n".join(
        f"- {agent.code}：{agent.name} —— {agent.description or '（无描述）'}" for agent in candidates
    )
    # 只带最近几轮、只截前 120 字：路由是「选谁」，不是「答题」，
    # 给太多历史反而让模型把上下文当问题本身
    recent = ""
    if history:
        lines = []
        for item in list(history)[-6:]:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            who = "用户" if item.get("role") == "user" else "助手"
            lines.append(f"{who}：{content[:120]}")
        if lines:
            recent = (
                "【最近对话】（用来理解「这个药 / 它 / 刚才那个」这类指代）\n"
                + "\n".join(lines)
                + "\n\n"
            )
    return (
        "你是「花红药业」在线客服系统的路由。根据用户的问题，从候选 Agent 中挑 1~2 个最合适的。\n"
        "判断依据：问题涉及药品用法/禁忌 → 药品类 Agent；涉及订单/退款/物流 → 订单类 Agent；"
        "涉及公司信息或客服流程 → 对应 Agent。\n"
        "如果用户这句话里有指代（这个药、它、刚才说的…），结合【最近对话】判断指的是什么，"
        "**不要因为句子本身短、指代不清就降低置信度**；只有连最近对话也判断不出时才给低分。\n"
        "只输出 JSON，不要解释，不要 markdown 代码块：\n"
        '{"agents":[{"code":"<候选里出现的 code>","confidence":0.0}],"confidence":0.0,"rationale":"一句话"}\n'
        "confidence 取 0~1：完全不确定就给低分，不要为了「显得有用」而乱选。\n\n"
        f"候选 Agent：\n{catalogue}\n\n{recent}用户问题：{message}"
    )


def parse_decision(text: str) -> dict[str, Any]:
    """从模型输出里抠出 JSON（容忍 ```json 围栏、前后解释文字）。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("空输出")
    fenced = raw
    if "```" in raw:
        fenced = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw.strip(), flags=re.M)
    match = _JSON_BLOCK.search(fenced)
    if not match:
        raise ValueError("没有 JSON")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("JSON 不是对象")
    return data


async def decide_route(
    *,
    message: str,
    mentions: Sequence[Mapping[str, Any]],
    role: str,
    registry: Mapping[str, AgentConfig],
    primary: AgentConfig,
    llm: Any | None = None,
    confidence_floor: float | None = None,
    history: Sequence[Mapping[str, Any]] | None = None,
) -> RouteDecision:
    """路由入口。``llm`` 为空时一律走显式路由/主 Agent（测试与降级用）。"""
    if mentions:
        agents = resolve_mentions(mentions, registry=registry, role=role)
        if agents:
            return RouteDecision(
                mode="mention",
                agents=agents,
                confidence=1.0,
                rationale=f"用户显式 @ 了 {len(agents)} 个 Agent",
            )

    candidates = [
        agent for agent in registry.values() if agent.is_active and agent.allows(role)
    ]
    if not candidates:
        raise RouteError("FORBIDDEN_AGENT", "当前身份没有可用的 Agent")

    if llm is None:
        return RouteDecision(
            mode="supervisor",
            agents=[primary] if primary.allows(role) else [candidates[0]],
            confidence=1.0,
            rationale="未启用模型路由，直连主 Agent",
        )

    floor = settings.supervisor_confidence_floor if confidence_floor is None else confidence_floor
    try:
        response = await llm.ainvoke(build_supervisor_prompt(message, candidates, history))
        decision = parse_decision(str(getattr(response, "content", "") or ""))
    except Exception as exc:  # noqa: BLE001 —— 路由失败不该让整轮对话失败
        logger.warning("supervisor 路由解析失败，回退主 Agent：%s", exc)
        return RouteDecision(
            mode="supervisor",
            agents=[primary] if primary.allows(role) else [candidates[0]],
            confidence=0.0,
            rationale="路由解析失败，已回退主 Agent",
        )

    by_code = {agent.code: agent for agent in candidates}
    picked: list[AgentConfig] = []
    for item in decision.get("agents") or []:
        code = str(item.get("code") or "") if isinstance(item, dict) else str(item)
        agent = by_code.get(code)
        if agent is None:  # 模型编了一个不存在的 code：忽略，不要 403 用户
            logger.info("supervisor 选中了不存在的 Agent：%s", code)
            continue
        if agent not in picked:
            picked.append(agent)

    confidence = float(decision.get("confidence") or 0.0)
    rationale = str(decision.get("rationale") or "")[:200]
    picked = picked[:MAX_TARGETS]

    if not picked or confidence < floor:
        return RouteDecision(
            mode="clarify",
            # 澄清时把「可选助手」都列出来，用户才知道能 @ 谁；这不是派发目标
            agents=picked or candidates[:3],
            confidence=confidence,
            rationale=rationale or "问题指向不明确",
        )
    return RouteDecision(mode="supervisor", agents=picked, confidence=confidence, rationale=rationale)
