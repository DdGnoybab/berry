"""Tests for the progress overview card."""

from __future__ import annotations

import json

from berry.assistants.learning.cards.progress_overview_card import (
    build_progress_overview_card,
)


def _redis_sample() -> dict[str, object]:
    return {
        "01-overview": {
            "name": "Redis 概述与基础",
            "status": "done",
            "score": 88.0,
            "atoms": {
                "a1": {"name": "什么是 Redis", "status": "done", "score": 8.5, "attempts": 1},
                "a2": {"name": "vs Memcached", "status": "done", "score": 9.0, "attempts": 1},
                "a3": {"name": "单线程模型", "status": "done", "score": 7.0, "attempts": 2,
                       "needs_review": True},
                "a4": {"name": "安装与命令", "status": "done", "score": 10.0, "attempts": 1},
            },
        },
        "02-data-structures": {
            "name": "数据结构与底层实现",
            "status": "in_progress",
            "atoms": {
                "a1": {"name": "SDS 设计", "status": "done", "score": 8.8, "attempts": 1},
                "a2": {"name": "ziplist 演进", "status": "done", "score": 8.0, "attempts": 1},
                "a3": {
                    "name": "quicklist",
                    "status": "in_progress",
                    "micro_state": "ASSESSING",
                },
                "a4": {"name": "dict 渐进式 rehash", "status": "pending"},
                "a5": {"name": "intset", "status": "pending"},
                "a6": {"name": "zset 跳表 + dict", "status": "pending"},
            },
        },
        "03-persistence": {
            "name": "持久化与过期淘汰",
            "status": "pending",
            "atoms_total": 4,
            "atoms": {},
        },
    }


def test_overview_card_v2_blue_header_with_progress_count() -> None:
    raw = build_progress_overview_card(
        topic="redis",
        goal="interview",
        modules=_redis_sample(),
        current_module="02-data-structures",
        current_atom="a3",
    )
    card = json.loads(raw)
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    title = card["header"]["title"]["content"]
    assert "redis" in title
    assert "准备面试" in title
    assert "1/3" in title  # 1 module done out of 3
    # 4 done a-atoms in 01 + 2 in 02 = 6 done out of (4+6+0)=10
    assert "6/10" in title


def test_overview_card_current_module_is_expanded_others_collapsed() -> None:
    raw = build_progress_overview_card(
        topic="redis",
        goal="interview",
        modules=_redis_sample(),
        current_module="02-data-structures",
        current_atom="a3",
    )
    card = json.loads(raw)
    body_md = card["body"]["elements"][0]["content"]
    # Current module's atoms should appear
    assert "SDS 设计" in body_md
    assert "ziplist 演进" in body_md
    assert "quicklist" in body_md
    # Current atom marker
    assert "← 当前" in body_md
    assert "ASSESSING" in body_md
    # Other modules should NOT show their atoms
    assert "什么是 Redis" not in body_md
    assert "vs Memcached" not in body_md
    # Other module headers still present
    assert "Redis 概述与基础" in body_md
    assert "持久化与过期淘汰" in body_md


def test_overview_card_done_module_shows_score() -> None:
    raw = build_progress_overview_card(
        topic="redis",
        goal="interview",
        modules=_redis_sample(),
        current_module="02-data-structures",
        current_atom="a3",
    )
    card = json.loads(raw)
    body_md = card["body"]["elements"][0]["content"]
    assert "✅ 01-overview" in body_md
    assert "88 分" in body_md


def test_overview_card_atom_done_marker_for_needs_review() -> None:
    raw = build_progress_overview_card(
        topic="redis",
        goal="interview",
        modules=_redis_sample(),
        current_module="01-overview",
        current_atom=None,
    )
    card = json.loads(raw)
    body_md = card["body"]["elements"][0]["content"]
    # a3 has needs_review=True, attempts=2
    assert "review" in body_md
    assert "(2)" in body_md  # attempts > 1 shown


def test_overview_card_footer_shown_when_telemetry_provided() -> None:
    raw = build_progress_overview_card(
        topic="redis",
        goal="interview",
        modules=_redis_sample(),
        current_module="02-data-structures",
        current_atom="a3",
        started_at="2026-06-04T09:00:00+08:00",
        last_active_at="2026-06-06T18:30:00+08:00",
        total_active_minutes=180,
    )
    card = json.loads(raw)
    elements = card["body"]["elements"]
    # Should be: markdown body, hr, markdown footer
    assert len(elements) == 3
    assert elements[1]["tag"] == "hr"
    footer = elements[2]["content"]
    assert "180" in footer
    assert "2026-06-04" in footer
    assert "2026-06-06 18:30" in footer


def test_overview_card_handles_no_goal() -> None:
    raw = build_progress_overview_card(
        topic="redis",
        goal=None,
        modules=_redis_sample(),
        current_module="02-data-structures",
        current_atom="a3",
    )
    card = json.loads(raw)
    title = card["header"]["title"]["content"]
    # No goal label injected
    assert "准备面试" not in title
    assert "redis" in title
