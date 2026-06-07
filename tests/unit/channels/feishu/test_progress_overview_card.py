"""Tests for the progress overview card.

Note: this card is currently unused at runtime (no caller after the
progress_watcher removal) but the rendering logic itself stays correct.
"""

from __future__ import annotations

import json

from berry.channels.feishu.cards.progress_overview_card import (
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
                "a3": {
                    "name": "单线程模型",
                    "status": "done",
                    "score": 7.0,
                    "attempts": 2,
                    "needs_review": True,
                },
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
    assert "1/3" in title
    assert "6/10" in title


def test_overview_card_current_module_expanded_others_collapsed() -> None:
    raw = build_progress_overview_card(
        topic="redis",
        goal="interview",
        modules=_redis_sample(),
        current_module="02-data-structures",
        current_atom="a3",
    )
    card = json.loads(raw)
    body_md = card["body"]["elements"][0]["content"]
    assert "SDS 设计" in body_md
    assert "← 当前" in body_md
    assert "什么是 Redis" not in body_md
    assert "Redis 概述与基础" in body_md


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
    assert "准备面试" not in title
    assert "redis" in title
