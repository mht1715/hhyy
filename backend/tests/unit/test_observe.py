"""看板聚合的纯函数部分（M4-04）单测。

DB 查询用接口冒烟覆盖（`/api/admin/observe/overview`）；这里只钉住
「百分位怎么算、比率怎么取整、成本怎么估」——这些口径最容易在看板与文档之间漂移。
"""

from app.api.admin_observe import _cost, _percentile, _ratio


def test_percentile_matches_linear_interpolation():
    values = [100, 200, 300, 400, 500]
    assert _percentile(values, 0.50) == 300
    # (5-1)*0.95 = 3.8 → 400*0.2 + 500*0.8 = 480
    assert _percentile(values, 0.95) == 480
    assert _percentile([], 0.95) == 0
    assert _percentile([42], 0.95) == 42


def test_ratio_rounds_and_guards_zero():
    assert _ratio(1, 4) == 0.25
    assert _ratio(0, 0) == 0.0
    assert _ratio(2, 3) == 0.6667


def test_cost_uses_configured_prices():
    from app.core.config import settings

    usage = {"input_tokens": 1000, "output_tokens": 1000}
    expected = settings.llm_price_input_per_1k + settings.llm_price_output_per_1k
    assert abs(_cost(usage) - expected) < 1e-9
    assert _cost({}) == 0.0
