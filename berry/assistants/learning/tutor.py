"""GoalTutor — learning-domain TurnRunner implementation.

Wraps ConversationRuntime, holds the assembled system prompt for the session.

Per spec § 7, the system prompt is a **session-start snapshot**: discovery
(BERRY.md walk, notes index) runs once when the GoalTutor is built and the
joined string is reused for every turn in the session. This keeps Anthropic
prompt cache hot and matches claw-code's behavior.

Rebuilding the prompt mid-session (e.g. after the user adds a new BERRY.md)
requires creating a fresh GoalTutor — the spec lists `/refresh` as a future
TODO, not a feature here.
"""

from __future__ import annotations

import platform
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from berry.assistants.learning.prompts.builder import (
    ModelFamilyIdentity,
    load_system_prompt,
)
from berry.core.agent import events as agent_events
from berry.core.agent.runtime import ConversationRuntime
from berry.core.agent.session import AgentSession


class GoalTutor:
    """Learning-domain TurnRunner.

    Usage:
        tutor = GoalTutor.from_settings(runtime=conv_runtime, settings=...)
        async for ev in tutor.run_turn(session=s, user_text="..."):
            channel.render(ev)

    The system prompt is computed once at construction time and reused across
    all turns in this session.
    """

    def __init__(
        self,
        *,
        runtime: ConversationRuntime,
        system_prompt: str,
    ) -> None:
        self._runtime = runtime
        self._system_prompt = system_prompt

    @classmethod
    def from_settings(
        cls,
        *,
        runtime: ConversationRuntime,
        settings: dict[str, Any],
        cwd: Path | None = None,
        model_family: ModelFamilyIdentity = ModelFamilyIdentity.CLAUDE,
    ) -> "GoalTutor":
        """Build a tutor with the system prompt assembled from current env."""
        prompt_sections = load_system_prompt(
            cwd=cwd if cwd is not None else Path.cwd(),
            current_date=datetime.now(UTC).date().isoformat(),
            os_name=platform.system().lower(),
            os_version=platform.release(),
            model_family=model_family,
            settings=settings,
            berry_version=_berry_version(),
            berry_source_path=str(_berry_source_path()),
        )
        return cls(runtime=runtime, system_prompt="\n\n".join(prompt_sections))

    @property
    def system_prompt(self) -> str:
        """Read-only — exposed for snapshot tests / debugging."""
        return self._system_prompt

    def run_turn(
        self,
        session: AgentSession,
        user_text: str,
    ) -> AsyncIterator[agent_events.AgentEvent]:
        """Implement TurnRunner — delegate to ConversationRuntime."""
        return self._runtime.run_turn(
            session=session,
            user_text=user_text,
            system_prompt=self._system_prompt,
        )


def _berry_version() -> str:
    """Best-effort package version lookup; falls back gracefully."""
    try:
        return version("berry")
    except PackageNotFoundError:
        return "unknown"


def _berry_source_path() -> Path:
    """Absolute path to the berry repo (so the LLM can show the user
    the exact ``uv run --project <here> ...`` command when switching
    workspaces).

    This file lives at <repo>/berry/assistants/learning/tutor.py, so
    ``parent.parent.parent.parent`` walks back up to <repo>.
    """
    return Path(__file__).resolve().parent.parent.parent.parent
