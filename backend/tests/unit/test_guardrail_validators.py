"""输出校验链（M4-06 ①②④⑤）单测。"""

from app.guardrail.citations import DISCLAIMER, finalize
from app.guardrail.validators import (
    check_approval_numbers,
    check_citation_indices,
    check_disclaimer,
    parse_json_output,
    validate_json_output,
    validate_json_schema,
    validate_output,
)

CITATIONS = [
    {"index": 1, "doc_title": "花红片说明书"},
    {"index": 2, "doc_title": "说明书用药常见问答"},
]


# --------------------------------------------------------------------------- JSON
def test_json_schema_happy_path():
    schema = {
        "type": "object",
        "required": ["name", "price"],
        "properties": {
            "name": {"type": "string"},
            "price": {"type": "number", "minimum": 0},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }
    violations = validate_json_schema({"name": "花红片", "price": 12.5, "tags": ["otc"]}, schema)
    assert violations == []


def test_json_schema_reports_missing_field_and_bad_type():
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    violations = validate_json_schema({"price": 1}, schema)
    assert any(item.kind == "schema.required" for item in violations)
    violations = validate_json_schema({"name": 3}, schema)
    assert any(item.kind == "schema.type" for item in violations)


def test_json_output_strips_code_fence_and_blocks_on_bad_json():
    data, report = validate_json_output('```json\n{"name": "花红片"}\n```', {"type": "object"})
    assert data == {"name": "花红片"}
    assert report.passed

    data, report = validate_json_output("这不是 JSON", {"type": "object"})
    assert data is None
    assert not report.passed
    assert report.violations[0].kind == "json.parse"


def test_parse_json_output_tolerates_leading_text():
    data, error = parse_json_output('结果是：{"ok": true} 以上')
    assert data == {"ok": True} and error == ""


# --------------------------------------------------------------------------- 业务规则
def test_approval_number_format_is_checked():
    assert check_approval_numbers("批准文号 国药准字Z45021234") == []
    bad = check_approval_numbers("批准文号 国药准字1234")
    assert bad and bad[0].kind == "business.approval_number"


# --------------------------------------------------------------------------- 引用 / 免责
def test_citation_indices_must_exist():
    assert check_citation_indices("一次 4 片[1]，孕妇禁用[2]。", CITATIONS) == []
    violations = check_citation_indices("一次 4 片[9]。", CITATIONS)
    assert violations and violations[0].kind == "citation.missing"
    assert "[9]" in violations[0].detail


def test_disclaimer_required_for_drug_answers():
    assert check_disclaimer("随便说点什么", required=False) == []
    assert check_disclaimer("随便说点什么", required=True)
    assert check_disclaimer(f"结论。\n\n> {DISCLAIMER}", required=True) == []


def test_validate_output_combines_checks():
    report = validate_output("结论[1]。", citations=CITATIONS, need_disclaimer=False)
    assert report.passed and report.flags == []

    report = validate_output("结论[9]。", citations=CITATIONS, need_disclaimer=True)
    assert not report.passed
    assert {"citation.missing", "compliance.disclaimer"} <= set(report.flags)


def test_finalize_injects_disclaimer_with_flag():
    outcome = finalize("花红片一次 4 片。[1]", CITATIONS, need_disclaimer=True)
    assert DISCLAIMER in outcome.text
    assert "disclaimer_injected" in outcome.flags
    # 正文里出现的 [1] 保留，未被引用的 [2] 被裁掉
    assert [item["index"] for item in outcome.citations] == [1]
