"""Tests for phantom-buttons nag detector."""

from __future__ import annotations

from berry.core.agent.reminders import phantom_buttons_nag


def test_no_match_when_ask_user_question_called() -> None:
    text = "点上面的按钮选一个"
    nag = phantom_buttons_nag.detect(text, tools_called={"ask_user_question"})
    assert nag.triggered is False


def test_chinese_dian_shang_mian_de_anniu() -> None:
    text = "你好啊,点上面的按钮就行"
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_chinese_shang_mian_anniu() -> None:
    text = "你可以点一下上面 3 个按钮中的一个,我们就能正式开始学习啦"
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_chinese_gangcai_xuanxiang() -> None:
    text = "刚才那 3 个选项里你倾向哪个?"
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_chinese_wenti_hai_zai() -> None:
    text = "刚才我问的问题还在那呢"
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_english_click_above() -> None:
    text = "Just click one of the buttons above to continue."
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_english_the_three_options() -> None:
    text = "Pick one of the 3 options I gave you earlier."
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_normal_text_does_not_trigger() -> None:
    text = "好的,我们开始学习 Redis 的数据结构吧。"
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is False


def test_render_reminder_includes_sample_and_instructions() -> None:
    nag = phantom_buttons_nag.PhantomButtonsNag(triggered=True, sample="点上面的按钮")
    rendered = phantom_buttons_nag.render_reminder(nag)
    assert "<system-reminder>" in rendered
    assert "点上面的按钮" in rendered
    assert "ask_user_question NOW" in rendered


def test_chinese_xia_mian_anniu_also_triggers() -> None:
    """User feedback: '按钮一般在下面' — '下面/below' pointers should
    be flagged just like '上面/above'. Both are wrong."""
    text = "你点一下下面的按钮就行"
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_english_click_below_also_triggers() -> None:
    text = "Click one of the buttons below to continue."
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_chinese_dianji_zhe_li() -> None:
    text = "你可以点击这里的选项"
    nag = phantom_buttons_nag.detect(text, tools_called=set())
    assert nag.triggered is True
