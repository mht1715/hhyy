"""分块器（M1-04）：``structured`` 优先，``recursive`` 兜底。

三条硬约束（PRD FR3.2），都能被单测直接验证：

1. **单 chunk ≤ 800 字**。超了就按句子边界继续切，句子还超就硬切。
2. **「禁忌」这类小节独立成块并带上 ``section`` 元数据**。检索「孕妇能吃吗」时才会
   精准命中「禁忌」，而不是命中整篇说明书。
3. **切分不丢字**。每块显式记录 ``overlap``（与上一块重复的字数），
   把所有块按 ``content[overlap:]`` 拼起来必须逐字节等于原文；
   ``reassemble()`` 提供了这个校验，索引流水线入库后会跑一次。

为什么不用 LangChain 的 ``RecursiveCharacterTextSplitter``：它把重叠藏在内部，
无法从结果反推「哪几个字是重复的」，于是「还原校验」只能靠肉眼。这里 40 行自己实现，
换来一个可断言的性质——对一个「喂给大模型的上下文是否正确」的系统来说，这笔交易划算。
"""

from __future__ import annotations

import re

from app.rag.parser import ParsedDoc, Section

DEFAULT_MAX_CHARS = 800
DEFAULT_MIN_CHARS = 50
DEFAULT_OVERLAP = 64

# 句子边界：中文句号/问号/感叹号/分号，以及段落换行
_SENTENCE_RE = re.compile(r"(?<=[。！？；])|(?<=\n)")
# 表格行 / 列表行：这些块尽量保持完整，不跨块切
_TABLE_LINE_RE = re.compile(r"^\s*[|｜]")
_LIST_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)、]|[（(]\d+[）)])\s+")


class Chunk:
    """一个待入库的分块。``overlap`` = 与上一块重复的前缀长度。"""

    __slots__ = ("index", "content", "section", "page", "overlap", "token_count")

    def __init__(
        self,
        index: int,
        content: str,
        *,
        section: str | None = None,
        page: int | None = None,
        overlap: int = 0,
        token_count: int = 0,
    ) -> None:
        self.index = index
        self.content = content
        self.section = section
        self.page = page
        self.overlap = overlap
        self.token_count = token_count

    @property
    def char_count(self) -> int:
        return len(self.content)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Chunk(index={self.index}, section={self.section!r}, chars={self.char_count})"


def estimate_tokens(text: str) -> int:
    """粗估 token：中文按 1 字 1 token，其余按 4 字符 1 token。

    只用来看趋势和做上下文预算，不追求精确——精确计数要找 tokenizer，
    而不同模型的 tokenizer 还不一样，估出来的数字反而会骗人。
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + other // 4


def _hard_split(text: str, max_chars: int) -> list[str]:
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def _atomic_units(text: str, max_chars: int) -> list[str]:
    """把文本切成「尽量不被切开」的最小单元：表格块 / 列表项 / 句子 / 硬切片。"""
    units: list[str] = []
    buffer: list[str] = []
    in_table = False

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        block = "".join(buffer)
        buffer = []
        if len(block) <= max_chars:
            units.append(block)
        else:
            for sentence in _SENTENCE_RE.split(block):
                if not sentence:
                    continue
                units.extend(_hard_split(sentence, max_chars) if len(sentence) > max_chars else [sentence])

    for line in text.splitlines(keepends=True):
        if _TABLE_LINE_RE.match(line):
            # 表格整块吃进去，尽量不在行间断开
            if not in_table:
                flush_buffer()
                in_table = True
            buffer.append(line)
            continue
        if in_table:
            # 表格结束：整块作为一个原子单元
            block = "".join(buffer)
            buffer = []
            in_table = False
            if len(block) <= max_chars:
                units.append(block)
            else:
                units.extend(_hard_split(block, max_chars))
            continue
        if _LIST_LINE_RE.match(line):
            flush_buffer()
            units.extend(_hard_split(line, max_chars) if len(line) > max_chars else [line])
            continue
        buffer.append(line)

    if in_table:
        block = "".join(buffer)
        buffer = []
        units.extend(_hard_split(block, max_chars) if len(block) > max_chars else [block])
    flush_buffer()
    return units


def _pack(
    text: str,
    *,
    max_chars: int,
    overlap: int,
    base_overlap: int = 0,
) -> list[tuple[str, int]]:
    """贪心装箱：返回 ``[(content, overlap_with_prev), ...]``。"""
    units = _atomic_units(text, max_chars)
    if not units:
        return []

    out: list[tuple[str, int]] = []
    current = ""
    current_overlap = base_overlap

    for unit in units:
        if current and len(current) + len(unit) > max_chars:
            out.append((current, current_overlap))
            # 重叠长度不能大于「本块留给正文的余量」，否则合并后会超上限
            room = max(0, max_chars - len(unit))
            tail_len = min(overlap, room, len(current))
            current = current[-tail_len:] if tail_len else ""
            current_overlap = tail_len
        current += unit

    if current:
        out.append((current, current_overlap))
    return out


def _merge_short(
    pieces: list[tuple[str, int, str | None, int | None]],
    *,
    min_chars: int,
    max_chars: int,
) -> list[tuple[str, int, str | None, int | None]]:
    """把过短的块与后一块合并（同小节内），合并后仍 ≤ max_chars。"""
    merged: list[tuple[str, int, str | None, int | None]] = []
    for content, overlap, section, page in pieces:
        if not merged:
            merged.append((content, overlap, section, page))
            continue
        prev_content, prev_overlap, prev_section, prev_page = merged[-1]
        prev_body = len(prev_content) - prev_overlap
        can_merge = (
            prev_body < min_chars
            and prev_section == section
            and prev_body + len(content) - overlap <= max_chars
        )
        if can_merge:
            # 合并等价于「去掉本块的前缀重叠后接上去」，重建时仍然逐字节可还原
            merged[-1] = (
                prev_content + content[overlap:],
                prev_overlap,
                prev_section,
                prev_page,
            )
        else:
            merged.append((content, overlap, section, page))
    return merged


def chunk_document(
    parsed: ParsedDoc,
    *,
    strategy: str = "structured",
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """把解析结果切成分块。

    :param strategy: ``structured`` 按小节切（每块带 section）；``recursive``
        忽略小节信息，整篇递归切分——适合没有小标题的客服话术。
    """
    if max_chars <= 0:
        raise ValueError("max_chars 必须为正数")
    if overlap >= max_chars:
        raise ValueError("overlap 必须小于 max_chars")

    pieces: list[tuple[str, int, str | None, int | None]] = []

    if strategy == "recursive" or not parsed.sections:
        for content, overlap_len in _pack(
            parsed.text, max_chars=max_chars, overlap=overlap
        ):
            pieces.append((content, overlap_len, None, None))
    else:
        sections: list[Section] = parsed.sections
        for section in sections:
            section_title = section.title or None
            for content, overlap_len in _pack(
                section.text,
                max_chars=max_chars,
                overlap=overlap,
                # 小节之间的重合没有意义（语义已断），只在本节非首块时才会有重叠
                base_overlap=0,
            ):
                pieces.append((content, overlap_len, section_title, section.page))

    pieces = _merge_short(pieces, min_chars=min_chars, max_chars=max_chars)

    chunks: list[Chunk] = []
    for index, (content, overlap_len, section_title, page) in enumerate(pieces):
        chunks.append(
            Chunk(
                index=index,
                content=content,
                section=section_title,
                page=page,
                overlap=overlap_len,
                token_count=estimate_tokens(content),
            )
        )
    return chunks


def reassemble(chunks: list[Chunk]) -> str:
    """按 ``overlap`` 去重后拼回原文，用于校验切分没丢字。"""
    return "".join(chunk.content[chunk.overlap:] for chunk in chunks)
