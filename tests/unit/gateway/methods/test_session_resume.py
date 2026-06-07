"""Tests for session.resume_create priming-message builder.

Validates that the LLM-facing priming message correctly:
  - degrades gracefully when no progress.json
  - branches per micro_state
  - cites the user's saved current_atom in option labels
  - mentions the next atom when one exists
"""

from __future__ import annotations

from berry.gateway.methods.session_resume import build_resume_priming


def _progress(
    *,
    micro: str,
    current_module: str = "02-data",
    current_atom: str = "a3",
    atom_name: str = "ziplist",
    next_atom: tuple[str, str] | None = ("a4", "quicklist"),
) -> dict:
    modules: dict = {
        "01-overview": {
            "name": "概述",
            "atoms": {"a1": {"name": "intro"}},
        },
        current_module: {
            "name": "数据结构",
            "atoms": {
                current_atom: {"name": atom_name},
            },
        },
    }
    if next_atom:
        modules[current_module]["atoms"][next_atom[0]] = {"name": next_atom[1]}
    return {
        "topic": "Redis",
        "current": {
            "module": current_module,
            "atom": current_atom,
            "micro_state": micro,
        },
        "modules": modules,
    }


def test_no_progress_returns_initialization_prompt() -> None:
    out = build_resume_priming(None)
    assert "先建学习计划" in out
    assert "ask_user_question" in out


def test_probing_options_mention_atom_label() -> None:
    out = build_resume_priming(_progress(micro="PROBING"))
    assert "PROBING" in out
    assert "接着答 a3 ziplist 的摸底题" in out
    assert "recommended=true" in out


def test_teaching_options() -> None:
    out = build_resume_priming(_progress(micro="TEACHING"))
    assert "接着讲 a3 ziplist" in out
    assert "我懂了,直接测 a3" in out


def test_assessing_options_include_next_atom() -> None:
    out = build_resume_priming(_progress(micro="ASSESSING"))
    assert "接着答完 a3 ziplist 的测试" in out
    assert "先复习 a3 ziplist" in out
    assert "跳到下一个 atom a4 quicklist" in out


def test_assessing_without_next_atom_omits_next() -> None:
    out = build_resume_priming(_progress(micro="ASSESSING", next_atom=None))
    assert "跳到下一个" not in out
    # but other 3 options still present
    assert "接着答完" in out
    assert "先复习" in out


def test_awaiting_user_branch() -> None:
    out = build_resume_priming(_progress(micro="AWAITING_USER"))
    assert "小测一下 a3 ziplist 复习" in out
    assert "接着学 a4 quicklist" in out
    assert "调整下学习计划" in out


def test_unknown_micro_falls_back_to_generic() -> None:
    out = build_resume_priming(_progress(micro="MODULE_INTRO"))
    assert "开始学 a4 quicklist" in out  # next_atom recommended
    assert "先小测一下复习" in out


def test_priming_includes_topic_and_skill_md_anchor() -> None:
    out = build_resume_priming(_progress(micro="PROBING"))
    assert "Redis" in out
    assert "SKILL.md §1bis" in out
    assert "ask_user_question" in out


def test_priming_includes_current_position_summary() -> None:
    out = build_resume_priming(_progress(micro="ASSESSING"))
    assert "上次到 02-data / a3 ziplist 的 ASSESSING 阶段" in out
