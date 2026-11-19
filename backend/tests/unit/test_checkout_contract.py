"""结算链路的契约回归（M5 修复）。

这里盯的是三个「界面正常、钱算错」的坑：

1. ``CartUpdate`` 在 cart.py 里被定义了两次，后一个没有 ``ge=1``，
   把前面带校验的版本覆盖掉了——`PUT /api/cart/{id}` 能写入 0 件甚至负数，
   再到结算就是 0 元订单（库存还会被「减 0」）。
2. ``OrderItemCreate.quantity`` 没有下界：``{"quantity": 0}`` 同样能造出 0 元订单。
3. 勾选结算必须带 ``from_cart``：只传 items 时后端不清购物车，
   下单后车里还在，演示时看起来像「重复下单」。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api import cart as cart_api
from app.api import order as order_api


def test_cart_update_rejects_zero_quantity():
    """cart.py 里只能有一个 CartUpdate，且必须带 ge=1。"""
    with pytest.raises(ValidationError):
        cart_api.CartUpdate(quantity=0)
    with pytest.raises(ValidationError):
        cart_api.CartUpdate(quantity=-3)
    assert cart_api.CartUpdate(quantity=2).quantity == 2


def test_order_item_quantity_must_be_positive():
    product_id = "63a315e3-1fc9-4ed3-b917-5acf38a5a1ee"
    with pytest.raises(ValidationError):
        order_api.OrderItemCreate(product_id=product_id, quantity=0)
    with pytest.raises(ValidationError):
        order_api.OrderItemCreate(product_id=product_id, quantity=-1)
    assert order_api.OrderItemCreate(product_id=product_id, quantity=1).quantity == 1


def test_order_create_from_cart_defaults_to_false():
    """默认必须关闭：立即购买不应该顺手清掉购物车里的同款。"""
    assert order_api.OrderCreate().from_cart is False
    assert order_api.OrderCreate(items=[]).from_cart is False
    payload = order_api.OrderCreate(
        items=[{"product_id": "63a315e3-1fc9-4ed3-b917-5acf38a5a1ee", "quantity": 2}],
        from_cart=True,
    )
    assert payload.from_cart is True
    assert payload.items[0].quantity == 2
