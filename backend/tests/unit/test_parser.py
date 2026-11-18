"""解析器单测：标题识别与网页正文抽取。"""

from __future__ import annotations

from app.rag.parser import detect_source_type, html_to_sections, split_sections


def test_bracket_heading_inline_and_standalone():
    text = "【成份】一点红、白花蛇舌草。\n【禁忌】\n孕妇禁用。"
    sections = split_sections(text)
    assert [section.title for section in sections] == ["成份", "禁忌"]
    # 标题行必须原样留在正文里，否则「拼回原文」就不成立了
    assert sections[1].text.startswith("【禁忌】")
    assert "孕妇禁用" in sections[1].text


def test_chinese_numeral_and_arabic_headings():
    text = "一、总则\n本政策自签收之日起生效。\n1.1 退货条件\n未拆封可退。"
    sections = split_sections(text)
    titles = [section.title for section in sections]
    assert "一、" in titles
    assert "1.1" in titles


def test_decimal_in_dosage_is_not_a_heading():
    """「1.5 毫克」是剂量不是标题，不能被切成小节。"""
    text = "【用法用量】\n每次 1.5 毫克。"
    sections = split_sections(text)
    assert [section.title for section in sections] == ["用法用量"]


def test_markdown_heading_stripped():
    sections = split_sections("## 配送范围\n全国大部分地区 3-5 天送达。")
    assert sections[0].title == "配送范围"
    assert sections[0].text.startswith("## 配送范围")


def test_plain_text_without_heading_returns_single_section():
    sections = split_sections("这是一段没有任何标题的正文。\n第二行。")
    assert len(sections) == 1
    assert sections[0].title == ""


def test_html_strips_nav_and_footer():
    html = """
    <html><body>
      <nav>首页 | 产品 | 关于我们</nav>
      <article>
        <h1>企业简介</h1>
        <p>花红药业是一家专注于妇科用药的企业。</p>
        <h2>质量理念</h2>
        <p>药材好，药才好。</p>
      </article>
      <footer>版权所有 2026 花红药业</footer>
      <script>var a = 1;</script>
    </body></html>
    """
    parsed = html_to_sections(html, source_url="https://example.com/about")
    assert "花红药业是一家" in parsed.text
    assert "版权所有" not in parsed.text
    assert "首页" not in parsed.text
    assert "var a" not in parsed.text
    titles = [section.title for section in parsed.sections]
    assert "企业简介" in titles
    assert "质量理念" in titles


def test_detect_source_type():
    assert detect_source_type("说明书.pdf") == "pdf"
    assert detect_source_type("政策.DOCX") == "docx"
    assert detect_source_type("note.md") == "md"
    assert detect_source_type("a.txt") == "txt"
    try:
        detect_source_type("a.png")
    except Exception as exc:
        assert "不支持" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("不支持的扩展名应当报错")
