"""Tests for the trailing-question nag detector."""

from __future__ import annotations

from berry.core.agent.reminders import trailing_question_nag


def test_no_match_when_ask_user_question_was_called() -> None:
    text = "好的,我来出题。下一个 atom?"
    nag = trailing_question_nag.detect(
        text, tools_called={"ask_user_question"}
    )
    assert nag.triggered is False


def test_match_real_drift_case_zh() -> None:
    """Reproduces the wire 16177497d5a5 drift in production:
    LLM ended a SUGGEST turn with '下一个 atom?' but skipped the tool.
    """
    text = (
        "**完全正确!** 就是这个意思。\n\n"
        "整条链路:\n"
        "1. 抢到锁\n"
        "2. 发现条件不满足\n\n"
        "你现在的理解已经到位了。下一个 atom?"
    )
    nag = trailing_question_nag.detect(text, tools_called=set())
    assert nag.triggered is True
    assert "下一个 atom" in nag.sample


def test_match_chinese_choice_with_huan_shi() -> None:
    text = "继续讲细节,还是直接出题?"
    nag = trailing_question_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_match_yao_bu_yao() -> None:
    text = "讲完了。要不要再深入讲一下?"
    nag = trailing_question_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_match_english_whats_next() -> None:
    text = "That covers it. What's next?"
    nag = trailing_question_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_no_match_when_no_question_mark() -> None:
    text = "好的,我们继续下一个 atom。"
    nag = trailing_question_nag.detect(text, tools_called=set())
    assert nag.triggered is False


def test_no_match_when_question_lacks_choice_vocab() -> None:
    """A teaching question (quiz) ends in ? but isn't a SUGGEST.
    We don't want to fire on this — it would nag every quiz turn.
    """
    text = "Q1. 什么是 SDS?"
    nag = trailing_question_nag.detect(text, tools_called=set())
    assert nag.triggered is False


def test_no_match_on_rhetorical_mid_text() -> None:
    """? in the middle of text but the last line doesn't end in ?."""
    text = "你想知道 wait() 怎么工作? 我来讲一下。\n锁释放后,线程进入 WAITING。"
    nag = trailing_question_nag.detect(text, tools_called=set())
    assert nag.triggered is False


def test_strips_blockquote_and_list_markers() -> None:
    """The choice question may be wrapped in '>' or '-'."""
    text = "讲完了。\n\n> 下一个 atom 还是再深入?"
    nag = trailing_question_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_other_tools_do_not_block_detection() -> None:
    text = "好,继续吗?"
    nag = trailing_question_nag.detect(
        text, tools_called={"read_file", "edit_file"}
    )
    assert nag.triggered is True


def test_render_reminder_includes_sample() -> None:
    nag = trailing_question_nag.TrailingQuestionNag(
        triggered=True, sample="下一个 atom?"
    )
    rendered = trailing_question_nag.render_reminder(nag)
    assert "<system-reminder>" in rendered
    assert "下一个 atom?" in rendered
    assert "ask_user_question" in rendered


def test_empty_text_does_not_match() -> None:
    nag = trailing_question_nag.detect("", tools_called=set())
    assert nag.triggered is False


def test_fullwidth_question_mark_works() -> None:
    text = "嗯,下一步要不要继续?"
    nag = trailing_question_nag.detect(text, tools_called=set())
    assert nag.triggered is True
