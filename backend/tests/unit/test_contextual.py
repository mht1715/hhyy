"""指代消解（M3 上下文修复）的纯函数测试。"""

from app.agent.contextual import (
    build_rewrite_prompt,
    needs_contextualize,
    rewrite_query,
)

HISTORY = [
    {"role": "user", "content": "跌打扭伤怎么办"},
    {"role": "assistant", "content": "可以考虑花红消肿止痛酊。"},
]


def test_short_followup_with_pronoun_needs_context():
    assert needs_contextualize("这个药怎么购买", HISTORY) is True
    assert needs_contextualize("它有什么禁忌", HISTORY) is True
    assert needs_contextualize("刚才说的那个能退吗", HISTORY) is True


def test_self_contained_or_first_turn_does_not():
    assert needs_contextualize("花红片怎么吃", HISTORY) is False
    assert needs_contextualize("这个药怎么购买", []) is False
    # 长句子通常自带主语，不值得再花一次模型调用
    assert needs_contextualize("这个药" + "能" * 60, HISTORY) is False


def test_prompt_contains_dialogue_and_original_question():
    prompt = build_rewrite_prompt("这个药怎么购买", HISTORY)
    assert "跌打扭伤怎么办" in prompt
    assert "这个药怎么购买" in prompt
    assert "只输出改写后的那一句话" in prompt


class _LLM:
    def __init__(self, content: str) -> None:
        self.content = content

    async def ainvoke(self, messages, **kwargs):  # noqa: ANN001, ANN003 —— 测试替身
        class _Msg:
            content = self.content

        return _Msg()


async def test_rewrite_strips_quotes_and_prefixes():
    llm = _LLM("「花红消肿止痛酊怎么购买」")
    assert await rewrite_query("这个药怎么购买", HISTORY, llm) == "花红消肿止痛酊怎么购买"


async def test_rewrite_falls_back_to_empty_on_same_or_broken_output():
    assert await rewrite_query("这个药怎么购买", HISTORY, _LLM("这个药怎么购买")) == ""
    assert await rewrite_query("这个药怎么购买", HISTORY, _LLM("   ")) == ""

    class _Boom:
        async def ainvoke(self, messages, **kwargs):  # noqa: ANN001, ANN003
            raise RuntimeError("model down")

    assert await rewrite_query("这个药怎么购买", HISTORY, _Boom()) == ""
