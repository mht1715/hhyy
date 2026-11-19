"""看板聚合的纯函数部分（M4-04 / M5）单测。

DB 查询用接口冒烟覆盖（`/api/admin/observe/overview`）；这里只钉住
「百分位怎么算、比率怎么取整、成本怎么估、趋势怎么补零」——这些口径最容易在
看板与文档之间漂移。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.api.admin_observe import _cost, _percentile, _ratio, _trend


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


def test_trend_fills_empty_days_and_counts_refusals():
    """趋势图不能因为某天没数据就少一根柱子（前端按数组画）。"""
    now = datetime.utcnow()
    answered = [
        SimpleNamespace(created_at=now, content="花红片一次 4 片，一日 3 次。"),
        SimpleNamespace(created_at=now, content="资料中没有相关记载，建议就医。"),
        SimpleNamespace(created_at=now - timedelta(days=2), content="可以饭后服用。"),
    ]
    today = now.date().isoformat()
    earlier = (now - timedelta(days=2)).date().isoformat()

    trend = _trend(3, answered, {today: 5}, {})

    assert len(trend) == 3
    assert [row["date"] for row in trend] == sorted(row["date"] for row in trend)
    assert trend[-1] == {
        "date": today,
        "turns": 2,
        "refusals": 1,
        "conversations": 5,
        "tickets": 0,
    }
    # 最早那天只有一轮，且没有会话数（缺省补 0，不是 None）
    assert trend[0]["date"] == earlier
    assert trend[0]["turns"] == 1
    assert trend[0]["conversations"] == 0


def test_trend_ignores_messages_outside_window():
    now = datetime.utcnow()
    too_old = SimpleNamespace(created_at=now - timedelta(days=10), content="老消息")
    trend = _trend(3, [too_old], {}, {})
    assert sum(row["turns"] for row in trend) == 0
