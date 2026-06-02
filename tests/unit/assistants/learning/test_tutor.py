"""Unit tests for GoalTutor.

GoalTutor is a thin TurnRunner adapter:
- Holds a pre-built system prompt string (computed at session start).
- Delegates run_turn to ConversationRuntime, injecting that prompt.

End-to-end LLM verification lives in CLI smoke tests (Step 8 cache check).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from berry.assistants.learning.prompts import SYSTEM_PROMPT_DYNAMIC_BOUNDARY
from berry.assistants.learning.tutor import GoalTutor
from berry.core.agent import events as agent_events
from berry.core.agent.session import AgentSession
from berry.domain.enums import Channel, SessionStatus


def _make_session() -> AgentSession:
    return AgentSession(
        id="20260601T120000-test",
        user_id=uuid4(),
        channel=Channel.CLI,
        status=SessionStatus.ACTIVE,
        title=None,
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_goal_tutor_passes_provided_system_prompt_to_runtime() -> None:
    runtime = MagicMock()
    captured: dict[str, str] = {}

    async def fake_run_turn(
        *, session: AgentSession, user_text: str, system_prompt: str
    ) -> AsyncIterator[agent_events.AgentEvent]:
        captured["system_prompt"] = system_prompt
        captured["user_text"] = user_text
        yield agent_events.TurnStart(session_id=session.id)
        yield agent_events.TurnEnd(stop_reason="end_turn")

    runtime.run_turn = fake_run_turn

    tutor = GoalTutor(runtime=runtime, system_prompt="custom prompt")
    session = _make_session()

    events = []
    async for ev in tutor.run_turn(session=session, user_text="hi"):
        events.append(ev)

    assert captured["system_prompt"] == "custom prompt"
    assert captured["user_text"] == "hi"
    assert len(events) == 2
    assert isinstance(events[0], agent_events.TurnStart)
    assert isinstance(events[1], agent_events.TurnEnd)


@pytest.mark.asyncio
async def test_from_settings_assembles_real_system_prompt(tmp_path: Path) -> None:
    """The from_settings classmethod runs full discovery + builder pipeline."""
    runtime = MagicMock()

    tutor = GoalTutor.from_settings(
        runtime=runtime,
        settings={"language": "zh-CN", "notes_dir": "notes"},
        cwd=tmp_path,
    )

    prompt = tutor.system_prompt
    assert prompt.startswith("You are Berry,")
    assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in prompt
    assert "# Environment context" in prompt
    assert "# Learning project context" in prompt
    assert "# Runtime config" in prompt
    assert '"language": "zh-CN"' in prompt


@pytest.mark.asyncio
async def test_from_settings_picks_up_berry_md(tmp_path: Path) -> None:
    """from_settings discovers BERRY.md in cwd."""
    (tmp_path / "BERRY.md").write_text("Project rule: prefer Python examples.")

    runtime = MagicMock()
    tutor = GoalTutor.from_settings(
        runtime=runtime,
        settings={"notes_dir": "notes"},
        cwd=tmp_path,
    )

    assert "# Berry instructions" in tutor.system_prompt
    assert "prefer Python examples" in tutor.system_prompt


@pytest.mark.asyncio
async def test_system_prompt_is_session_snapshot(tmp_path: Path) -> None:
    """System prompt is computed once at construction; later filesystem
    changes are not reflected (matches spec § 7 snapshot behavior)."""
    runtime = MagicMock()
    tutor = GoalTutor.from_settings(
        runtime=runtime,
        settings={"notes_dir": "notes"},
        cwd=tmp_path,
    )

    initial = tutor.system_prompt
    # User adds a note mid-session — should NOT be reflected
    notes = tmp_path / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "new-note.md").write_text("brand new content")

    assert tutor.system_prompt == initial
    assert "new-note.md" not in tutor.system_prompt
