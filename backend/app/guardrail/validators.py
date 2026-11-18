"""输出校验链（M4-06，PRD FR8.4 ①②④⑤）。

流式回答走的是「边流边改」的闸门（``compliance.ComplianceStreamFilter`` +
``citations.CitationStreamFilter``），因为已经发出去的 token 收不回；
这里这一层负责**非流式 / 结构化**的两类输出：

1. **JSON Schema 子集校验**：药品入库 Agent、路由决策这类「必须有结构」的输出。
   失败时调用方可以带错误信息重试（self-heal），最多 2 次（PRD FR8.4）。
2. **业务规则**：批准文号（``国药准字A12345678``）格式、价格区间。
3. **引用存在性**：正文里的 ``[n]`` 必须能在 citations 里找到，否则视为幻觉引用。
4. **免责声明存在性**：药品类回答必带（``citations.append_disclaimer`` 负责注入，
   这里只做「事后审计」——注入逻辑和校验逻辑分开，才能互相兜底）。

所有函数都是纯函数，返回 ``Violation`` 列表，方便单测逐条断言。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.guardrail.citations import DISCLAIMER

APPROVAL_NUMBER = re.compile(r"国药准字[A-Z]\d{8}")
CITATION_MARK = re.compile(r"\[(\d{1,2})\]")
# 允许的 Schema 关键字子集：够用即可，不做完整 JSON Schema 实现
_ALLOWED_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}

SEVERITY_BLOCK = "block"
SEVERITY_FLAG = "flag"


@dataclass(slots=True)
class Violation:
    kind: str
    detail: str
    severity: str = SEVERITY_FLAG

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "detail": self.detail, "severity": self.severity}


@dataclass(slots=True)
class GuardrailReport:
    passed: bool
    flags: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    data: Any = None

    def as_guardrail(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "flags": list(self.flags),
            "violations": [item.as_dict() for item in self.violations],
        }


# --------------------------------------------------------------------------- JSON
def parse_json_output(text: str) -> tuple[Any, str]:
    """从模型输出里抠 JSON（容忍 ```json 围栏与前后解释文字）。"""
    raw = (text or "").strip()
    if not raw:
        return None, "空输出"
    fenced = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw.strip(), flags=re.M).strip()
    start, end = fenced.find("{"), fenced.rfind("}")
    if start == -1 or end <= start:
        start, end = fenced.find("["), fenced.rfind("]")
    if start == -1 or end <= start:
        return None, "没有 JSON 结构"
    try:
        return json.loads(fenced[start : end + 1]), ""
    except (TypeError, ValueError) as exc:
        return None, f"JSON 解析失败：{exc}"


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    # number / integer：bool 是 int 的子类，要排除
    if isinstance(value, bool):
        return False
    if expected == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if expected == "number":
        return isinstance(value, (int, float))
    return False


def validate_json_schema(
    value: Any, schema: Mapping[str, Any], *, path: str = "$"
) -> list[Violation]:
    """JSON Schema 子集校验：type / required / properties / items / enum / minimum / maximum。"""
    violations: list[Violation] = []
    if not isinstance(schema, Mapping):
        return violations

    expected = schema.get("type")
    if expected:
        if not isinstance(expected, str) or expected not in _ALLOWED_TYPES:
            violations.append(Violation("schema.unknown_type", f"{path}: 未知类型 {expected!r}"))
            return violations
        if not _type_matches(value, expected):
            violations.append(
                Violation(
                    "schema.type",
                    f"{path}: 期望 {expected}，实际 {type(value).__name__}",
                    SEVERITY_BLOCK,
                )
            )
            return violations

    if "enum" in schema and value not in (schema.get("enum") or []):
        violations.append(Violation("schema.enum", f"{path}: 不在枚举范围内", SEVERITY_BLOCK))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            violations.append(Violation("schema.minimum", f"{path}: 小于最小值", SEVERITY_BLOCK))
        if "maximum" in schema and value > schema["maximum"]:
            violations.append(Violation("schema.maximum", f"{path}: 大于最大值", SEVERITY_BLOCK))

    if isinstance(value, dict):
        for key in schema.get("required") or []:
            if key not in value:
                violations.append(
                    Violation("schema.required", f"{path}: 缺少必填字段 {key}", SEVERITY_BLOCK)
                )
        properties = schema.get("properties") or {}
        for key, sub_schema in properties.items():
            if key in value:
                violations.extend(
                    validate_json_schema(value[key], sub_schema, path=f"{path}.{key}")
                )

    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for index, item in enumerate(value):
            violations.extend(
                validate_json_schema(item, schema["items"], path=f"{path}[{index}]")
            )

    return violations


def validate_json_output(
    text: str, schema: Mapping[str, Any]
) -> tuple[Any, GuardrailReport]:
    data, error = parse_json_output(text)
    if error:
        return None, GuardrailReport(
            passed=False,
            flags=["json_invalid"],
            violations=[Violation("json.parse", error, SEVERITY_BLOCK)],
        )
    violations = validate_json_schema(data, schema)
    blocked = any(item.severity == SEVERITY_BLOCK for item in violations)
    return data, GuardrailReport(
        passed=not blocked,
        flags=["json_invalid"] if blocked else [],
        violations=violations,
        data=data,
    )


# --------------------------------------------------------------------------- 业务规则
def check_approval_numbers(text: str) -> list[Violation]:
    """批准文号格式审计：出现「国药准字」但不是标准格式 → 提示人工核对。

    只做「格式」不做「真伪」：真伪要查药监局库，作品里只承诺格式与留痕。
    """
    value = text or ""
    violations: list[Violation] = []
    for match in re.finditer(r"国药准字[^\s，。；,;]*", value):
        token = match.group(0)
        if not APPROVAL_NUMBER.fullmatch(token):
            violations.append(
                Violation("business.approval_number", f"批准文号格式可疑：{token}")
            )
    return violations


# --------------------------------------------------------------------------- 引用 / 免责
def check_citation_indices(
    text: str, citations: Sequence[Mapping[str, Any]]
) -> list[Violation]:
    """正文引用必须都在 citations 里（流式闸门负责丢弃，这里做终检）。"""
    known = {item.get("index") for item in citations or []}
    unknown = sorted({int(n) for n in CITATION_MARK.findall(text or "")} - known)
    if not unknown:
        return []
    return [
        Violation(
            "citation.missing",
            f"正文引用了不存在的来源：{[f'[{n}]' for n in unknown]}",
            SEVERITY_BLOCK,
        )
    ]


def check_disclaimer(text: str, *, required: bool) -> list[Violation]:
    if not required:
        return []
    if DISCLAIMER in (text or ""):
        return []
    return [Violation("compliance.disclaimer", "药品类回答缺少免责声明", SEVERITY_BLOCK)]


# --------------------------------------------------------------------------- 总入口
def validate_output(
    text: str,
    *,
    citations: Sequence[Mapping[str, Any]] = (),
    need_disclaimer: bool = False,
) -> GuardrailReport:
    """对一段最终文本跑完 ②④⑤ 三层，返回可直接进 ``guardrail`` 事件的报告。"""
    violations: list[Violation] = []
    violations.extend(check_citation_indices(text, citations))
    violations.extend(check_approval_numbers(text))
    violations.extend(check_disclaimer(text, required=need_disclaimer))
    blocked = any(item.severity == SEVERITY_BLOCK for item in violations)
    flags = sorted({item.kind for item in violations})
    return GuardrailReport(passed=not blocked, flags=flags, violations=violations)


__all__ = [
    "APPROVAL_NUMBER",
    "GuardrailReport",
    "Violation",
    "check_approval_numbers",
    "check_citation_indices",
    "check_disclaimer",
    "parse_json_output",
    "validate_json_output",
    "validate_json_schema",
    "validate_output",
]
