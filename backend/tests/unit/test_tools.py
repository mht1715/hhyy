"""工具层测试（M2-02）。

重点验证三件事：
1. 工具级权限（``required_roles``）由 ``call_tool`` 统一挡；
2. ``order_lookup`` 查他人订单返回 ``FORBIDDEN``，而不是「查无此单」；
3. 工具挂掉被收敛成 ``ToolResult(ok=False)``，不会把整条回答链路炸掉。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest

from app.models.order import Order
from app.models.product import Product
from app.rag.base import RetrievedChunk
from app.testing.fakes import FakeRetrievalService
from app.tools.base import ToolContext, ToolSpec, call_tool, register_tool
from app.tools.builtin import product_lookup


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """只认识本文件用到的两种查询：知识库 code→id、prompt 模板。"""

    def __init__(self, kb_rows: list[tuple[uuid.UUID, str]] | None = None) -> None:
        self.kb_rows = kb_rows or []
        self.commits = 0

    async def execute(self, statement):  # noqa: ANN001
        sql = str(statement).lower()
        if "knowledge_bases" in sql:
            return _Result(self.kb_rows)
        return _Result([])

    async def get(self, model, pk):  # noqa: ANN001
        return None

    async def commit(self) -> None:
        self.commits += 1


def _order(user_id: uuid.UUID, order_id: uuid.UUID | None = None) -> Order:
    order = Order(
        id=order_id or uuid.uuid4(),
        user_id=user_id,
        total_amount=99.0,
        status="paid",
    )
    order.items = []
    return order


def _ctx(db: Any, *, role: str = "patient", user_id: uuid.UUID | None = None, **kwargs: Any) -> ToolContext:
    return ToolContext(db=db, role=role, user_id=user_id, **kwargs)


async def test_order_lookup_forbids_other_users_order():
    owner = uuid.uuid4()
    stranger = uuid.uuid4()
    order = _order(owner)

    class OrderDB(FakeDB):
        async def execute(self, statement):  # noqa: ANN001
            return _Result([order])

    result = await call_tool("order_lookup", _ctx(OrderDB(), user_id=stranger), order_id=str(order.id))

    assert result.ok is False
    assert result.code == "FORBIDDEN"


async def test_order_lookup_support_can_view_others():
    owner = uuid.uuid4()
    order = _order(owner)

    class OrderDB(FakeDB):
        async def execute(self, statement):  # noqa: ANN001
            return _Result([order])

    result = await call_tool(
        "order_lookup",
        _ctx(OrderDB(), role="support", user_id=str(uuid.uuid4())),
        order_id=str(order.id),
    )

    assert result.ok is True
    assert result.data["orders"][0]["order_id"] == str(order.id)


async def test_order_lookup_requires_login():
    # 游客连工具层都进不去（required_roles 里有 order_lookup 的登录保护）
    result = await call_tool("order_lookup", _ctx(FakeDB(), role="visitor"))
    assert result.ok is False
    assert result.code in {"AUTH_REQUIRED", "FORBIDDEN"}


async def test_tool_role_gate_blocks_visitor():
    result = await call_tool("order_lookup", _ctx(FakeDB(), role="visitor"))
    assert result.code in {"AUTH_REQUIRED", "FORBIDDEN"}


async def test_unknown_tool_is_converted_not_raised():
    result = await call_tool("no_such_tool", _ctx(FakeDB()))
    assert result.ok is False
    assert result.code == "UNKNOWN_TOOL"


async def test_kb_search_passes_acl_scope_to_retrieval():
    kb_id = uuid.uuid4()
    chunk = RetrievedChunk(
        id="c1",
        content="孕妇及哺乳期妇女禁用。",
        score=0.93,
        kb_id=str(kb_id),
        doc_id="doc1",
        doc_title="花红片说明书",
        section="禁忌",
    )
    retrieval = FakeRetrievalService([chunk])
    ctx = ToolContext(
        db=FakeDB([(kb_id, "kb_drug_manual")]),
        role="patient",
        kb_codes=("kb_drug_manual",),
        retrieval=retrieval,
    )

    result = await call_tool("kb_search", ctx, query="哺乳期能吃吗")

    assert result.ok is True
    assert result.data["hits"][0]["doc_title"] == "花红片说明书"
    # 工具只能检索 Agent 绑定的库，且传下去的是库 id（不是 code）
    assert retrieval.calls[0]["kb_ids"] == [str(kb_id)]
    assert result.data["chunks"][0].section == "禁忌"


async def test_kb_search_refuses_unbound_kb():
    """工具只能检索 Agent 绑定的库：显式要一个没绑定的库 → 直接 FORBIDDEN。"""
    ctx = ToolContext(
        db=FakeDB([(uuid.uuid4(), "kb_after_sale")]),
        role="patient",
        kb_codes=("kb_drug_manual",),
        retrieval=FakeRetrievalService([]),
    )
    result = await call_tool("kb_search", ctx, query="退货", kb_codes=["kb_after_sale"])
    assert result.ok is False
    assert result.code == "FORBIDDEN"


async def test_tool_timeout_becomes_result(monkeypatch):
    name = f"slow_test_tool_{uuid.uuid4().hex[:6]}"

    @register_tool(ToolSpec(name=name, description="测试用", timeout_seconds=0.05))
    async def slow_test_tool(ctx: ToolContext) -> dict[str, Any]:
        import asyncio

        await asyncio.sleep(0.5)
        return {"never": True}

    started = time.perf_counter()
    result = await call_tool(name, _ctx(FakeDB()))
    assert result.ok is False
    assert result.code == "TIMEOUT"
    assert time.perf_counter() - started < 0.5


async def test_product_lookup_requires_some_argument():
    result = await call_tool("product_lookup", _ctx(FakeDB()))
    assert result.ok is False
    assert result.code == "BAD_ARGS"


async def test_product_lookup_not_found():
    from app.tools.base import ToolError

    class EmptyDB(FakeDB):
        async def execute(self, statement):  # noqa: ANN001
            return _Result([])

    with pytest.raises(ToolError):
        await product_lookup(ToolContext(db=EmptyDB(), role="patient"), name="不存在的药")


@pytest.mark.parametrize("role", ["patient", "doctor", "support", "admin"])
def test_order_tool_declares_login_roles(role: str):
    from app.tools.base import get_tool

    assert get_tool("order_lookup").spec.allowed_for(role)


def test_product_model_has_expected_fields():
    # 防止有人改字段名而工具静默返回空
    assert {"name", "generic_name", "price", "spec", "manufacturer"} <= set(Product.__table__.columns.keys())
