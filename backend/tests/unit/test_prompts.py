"""Prompt 灰度与版本解析（M4-05）单测。"""

from dataclasses import dataclass

from app.agent.prompts import resolve_prompt_rows, rollout_bucket, version_label


@dataclass
class Row:
    code: str = "drug_consult"
    version: int = 1
    status: str = "production"
    rollout: int = 100
    content: str = "prompt"


def test_rollout_bucket_is_stable_and_in_range():
    first = rollout_bucket("patient-1")
    assert first == rollout_bucket("patient-1")
    assert 0 <= first < 100
    # 不同用户不该全挤在同一个桶里（sha1 分发，样本 50 个应出现多个桶）
    assert len({rollout_bucket(f"user-{index}") for index in range(50)}) > 10


def test_production_is_used_when_no_canary():
    row, reason = resolve_prompt_rows([Row(version=2)], bucket=7)
    assert row is not None and row.version == 2
    assert "production" in reason


def test_canary_hits_when_bucket_below_rollout():
    rows = [Row(version=1), Row(version=3, status="testing", rollout=100)]
    row, reason = resolve_prompt_rows(rows, bucket=42)
    assert row.version == 3
    assert "灰度命中" in reason


def test_canary_misses_when_bucket_above_rollout():
    # bucket=90，rollout=20 → 不命中，回落 production
    rows = [Row(version=1), Row(version=3, status="testing", rollout=20)]
    row, reason = resolve_prompt_rows(rows, bucket=90)
    assert row.version == 1
    assert "production" in reason


def test_highest_canary_version_wins():
    rows = [
        Row(version=1),
        Row(version=2, status="testing", rollout=100),
        Row(version=3, status="testing", rollout=100),
    ]
    row, _reason = resolve_prompt_rows(rows, bucket=0)
    assert row.version == 3


def test_no_rows_means_builtin_template():
    row, reason = resolve_prompt_rows([], bucket=0)
    assert row is None
    assert "内置模板" in reason


def test_version_label_format():
    assert version_label(Row(version=4)) == "drug_consult@v4"
    assert version_label(None) == ""
