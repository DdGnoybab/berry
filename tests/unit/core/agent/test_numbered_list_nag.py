"""Tests for the numbered-list nag detector."""

from __future__ import annotations

from berry.core.agent.reminders import numbered_list_nag


def test_no_match_when_ask_user_question_was_called() -> None:
    text = "1. Foo\n2. Bar\n3. Baz"
    nag = numbered_list_nag.detect(text, tools_called={"ask_user_question"})
    assert nag.triggered is False


def test_match_when_two_or_more_numbered_lines() -> None:
    text = "1. Foo option\n2. Bar option"
    nag = numbered_list_nag.detect(text, tools_called=set())
    assert nag.triggered is True
    assert "Foo" in nag.sample


def test_no_match_with_only_one_numbered_line() -> None:
    """Single 'Step 1. ...' is just enumerated prose, not an option list."""
    text = "Here's what to do: 1. Read the file."
    nag = numbered_list_nag.detect(text, tools_called=set())
    assert nag.triggered is False


def test_paren_form_also_matches() -> None:
    text = "1) Choose A\n2) Choose B"
    nag = numbered_list_nag.detect(text, tools_called=set())
    assert nag.triggered is True


def test_other_tools_do_not_block_detection() -> None:
    text = "1. A\n2. B"
    nag = numbered_list_nag.detect(text, tools_called={"read_file", "bash"})
    assert nag.triggered is True


def test_render_reminder_includes_sample() -> None:
    nag = numbered_list_nag.NumberedListNag(triggered=True, sample="1. fooo")
    rendered = numbered_list_nag.render_reminder(nag)
    assert "<system-reminder>" in rendered
    assert "1. fooo" in rendered
    assert "ask_user_question" in rendered
