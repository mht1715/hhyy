"""文档解析（M1-03）：pdf / docx / md / txt / url → ``ParsedDoc``。

设计要点

1. **保留标题原文**。每个 ``Section.text`` 的第一行就是标题行本身
   （``【禁忌】`` / ``## 用法`` / ``一、概述``），因此「所有 chunk 拼起来 == 原文」
   这条验收标准是可以真的验证的，而不是靠印象。
2. **解析与分块解耦**。解析只负责「把文件变成带层级和页码的段落」，
   怎么切 chunk 是 ``chunker.py`` 的事——两者的失败原因完全不同
   （编码/损坏 vs 切分策略），日志里能一眼分开。
3. **第三方库延迟导入**。``pypdf`` / ``python-docx`` / ``bs4`` 只在真正解析对应
   格式时才 import，这样跑单测、跑只处理 markdown 的流水线时不需要装全套依赖。
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ParseError(RuntimeError):
    """解析失败（文件损坏、编码不可识别、抓取失败等）。"""


# 标题行模式，按优先级排列。命中即认为新小节开始。
_HEADING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 【成份】 / 【禁忌】 —— 药品说明书的写法，标题可能和正文同一行
    ("bracket", re.compile(r"^【([^】\n]{1,20})】\s*(.*)$")),
    # 一、二、三、
    ("cn_num", re.compile(r"^([一二三四五六七八九十]{1,3})、\s*(.{0,40})$")),
    # 1. 1.1 1.1.1 （分隔符可以是点、顿号或空格，见 _match_heading 的单位词过滤）
    ("arabic", re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})(?:[.、]\s*|\s+)(.{1,40})$")),
    # markdown 标题
    ("md", re.compile(r"^(#{1,6})\s+(.{1,40})$")),
)

_MAX_HEADING_TITLE = 40
# 阿拉伯数字编号后面紧跟这些字才认为是标题，避免 "1.5 毫克" 之类误判
_ARABIC_TITLE_HINT = re.compile(r"[\u4e00-\u9fa5]")
# 以计量/单位开头的，一律当正文（"1.5 毫克"、"3 片"）
_UNIT_PREFIX = (
    "毫克", "克", "毫升", "升", "片", "粒", "袋", "支", "瓶", "次", "日", "天",
    "周", "月", "年", "元", "岁", "度", "%", "mg", "ml", "g", "kg",
)


@dataclass(slots=True)
class Section:
    """一个小节。``text`` 含标题行原文。"""

    title: str
    text: str
    page: int | None = None


@dataclass(slots=True)
class ParsedDoc:
    """解析结果。``text`` 是拼回去的全文，``sections`` 是层级切分。"""

    text: str
    sections: list[Section] = field(default_factory=list)
    page_map: dict[int, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.page_map)


def file_sha256(data: bytes) -> str:
    """文件指纹：同样的文件重复上传时用来去重。"""
    return hashlib.sha256(data).hexdigest()


def detect_source_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix in {"pdf"}:
        return "pdf"
    if suffix in {"doc", "docx"}:
        return "docx"
    if suffix in {"md", "markdown"}:
        return "md"
    if suffix in {"txt", "text"}:
        return "txt"
    raise ParseError(f"不支持的文件类型：.{suffix or '未知'}（支持 pdf/docx/md/txt）")


def _match_heading(line: str) -> tuple[str, str] | None:
    """返回 ``(title, 该行剩余内容)``；不是标题返回 None。"""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return None

    for kind, pattern in _HEADING_PATTERNS:
        match = pattern.match(stripped)
        if not match:
            continue
        if kind == "md":
            # "## 用法" —— 去掉 # 号
            return match.group(2).strip(), ""
        if kind == "bracket":
            title, rest = match.group(1).strip("：: "), match.group(2)
            return title, rest
        if kind == "cn_num":
            return match.group(1) + "、", match.group(2)
        # arabic：要求标题里含中文，且不能是「1.5 毫克」这种带计量单位的正文
        title, rest = match.group(1), match.group(2)
        if rest.startswith(_UNIT_PREFIX):
            return None
        if rest and not _ARABIC_TITLE_HINT.search(rest):
            return None
        return title, rest
    return None


def split_sections(text: str, *, page: int | None = None) -> list[Section]:
    """按标题行把纯文本切成小节，保留标题原文。

    没有命中任何标题时，整篇作为一个小节返回（``title=""``）。
    """
    lines = text.splitlines()
    sections: list[Section] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append(Section(title=current_title, text=body, page=page))

    for line in lines:
        heading = _match_heading(line)
        if heading is None:
            current_lines.append(line)
            continue
        title, rest = heading
        # 标题行本身原样留在正文里，保证可还原
        flush()
        current_title = title[:_MAX_HEADING_TITLE]
        current_lines = [line.rstrip()]
        if rest:
            current_lines.append(rest)

    flush()
    return sections


def parse_plain_text(text: str, *, source_type: str = "txt") -> ParsedDoc:
    """md / txt 走这里：只做小节切分。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    sections = split_sections(normalized)
    return ParsedDoc(
        text=normalized,
        sections=sections,
        metadata={"source_type": source_type, "section_count": len(sections)},
    )


def parse_pdf(data: bytes) -> ParsedDoc:
    """PDF：逐页抽文本，再按页内标题切小节；扫描件会给出明确提示。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 依赖缺失时才走到
        raise ParseError("缺少 pypdf，无法解析 PDF") from exc

    import io

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 —— pypdf 的异常类型不稳定
        raise ParseError(f"PDF 无法打开：{exc}") from exc

    page_map: dict[int, str] = {}
    sections: list[Section] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("PDF 第 %d 页抽取失败：%s", index, exc)
            text = ""
        text = text.strip()
        if not text:
            continue
        page_map[index] = text
        sections.extend(split_sections(text, page=index))

    if not page_map:
        raise ParseError("PDF 未抽取到文本，可能是扫描件（本期不支持 OCR）")

    full_text = "\n".join(page_map[page] for page in sorted(page_map))
    return ParsedDoc(
        text=full_text,
        sections=sections,
        page_map=page_map,
        metadata={"source_type": "pdf", "page_count": len(page_map)},
    )


def parse_docx(data: bytes) -> ParsedDoc:
    """DOCX：用 python-docx 按段落取文本，Heading 样式即标题。"""
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:  # pragma: no cover
        raise ParseError("缺少 python-docx，无法解析 DOCX") from exc

    import io

    try:
        document = DocxDocument(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"DOCX 无法打开：{exc}") from exc

    lines: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower()
        if style.startswith("heading") or style.startswith("标题"):
            # 转成 markdown 标题，复用同一套切分逻辑
            level = "".join(ch for ch in style if ch.isdigit()) or "2"
            lines.append("#" * min(int(level), 6) + " " + text)
        else:
            lines.append(text)

    # 表格也算正文：说明书里的用法用量经常是表格
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                lines.append(" | ".join(cells))

    merged = "\n".join(lines)
    if not merged.strip():
        raise ParseError("DOCX 未抽取到文本")
    sections = split_sections(merged)
    return ParsedDoc(
        text=merged,
        sections=sections,
        metadata={"source_type": "docx", "section_count": len(sections)},
    )


_BOILERPLATE_TAGS = ("nav", "footer", "header", "aside", "form", "script", "style", "noscript", "iframe")
_BOILERPLATE_PATTERN = re.compile(
    r"nav|footer|header|sidebar|breadcrumb|menu|banner|copyright|share|cookie", re.IGNORECASE
)


def html_to_sections(html: str, *, source_url: str = "") -> ParsedDoc:
    """HTML 正文抽取：优先 article/main，再退回 body，并清掉导航与页脚。"""
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        raise ParseError("缺少 beautifulsoup4，无法解析网页") from exc

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_BOILERPLATE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", [])) + " " + (tag.get("id") or "")
        if classes.strip() and _BOILERPLATE_PATTERN.search(classes):
            tag.decompose()

    def clean_text(node: Any) -> str:
        for br in node.find_all("br"):
            br.replace_with("\n")
        raw = node.get_text("\n")
        lines = [line.strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)

    container = soup.find("article") or soup.find("main") or soup.body
    if container is None:
        raise ParseError(f"网页没有可抽取的正文：{source_url}")

    # 把 h1-h3 转成 markdown 标题，交给统一的切分逻辑
    for level in (1, 2, 3):
        for tag in container.find_all(f"h{level}"):
            tag.string = "#" * level + " " + tag.get_text(strip=True)

    text = clean_text(container)
    if not text.strip():
        raise ParseError(f"网页正文为空：{source_url}")
    sections = split_sections(text)
    title = soup.title.get_text(strip=True) if soup.title else ""
    return ParsedDoc(
        text=text,
        sections=sections,
        metadata={"source_type": "url", "url": source_url, "title": title},
    )


async def parse_url(url: str) -> ParsedDoc:
    """抓取网页并解析正文。"""
    import httpx

    headers = {
        # 部分站点会按 UA 返回不同的 HTML（甚至直接 403）
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"抓取失败：{exc}") from exc

    # httpx 优先用响应头字符集；国内站点经常是 GBK
    if response.encoding is None or response.encoding.lower() == "iso-8859-1":
        response.encoding = "utf-8"
    return html_to_sections(response.text, source_url=url)
