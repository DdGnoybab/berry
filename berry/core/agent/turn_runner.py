"""TurnRunner — the contract a channel uses to drive a single user turn.

A channel (CLI REPL, feishu, ...) doesn't care what implementation it's
talking to — anything that satisfies this Protocol works. The channel
calls ``run_turn`` the same way regardless.

Why this lives in ``core/agent/`` rather than next to ``ConversationRuntime``:
- Channels import this Protocol; channels/* are not allowed to import
  business code (assistants/*) under ADR-0003. Putting the Protocol in
  ``core/agent`` lets any assistant implementation satisfy it without
  reaching across layers backwards.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from berry.core.agent.events import AgentEvent
from berry.core.agent.session import AgentSession


@runtime_checkable
class TurnRunner(Protocol):
    """Anything that can run one turn of a conversation.

    Implementations:
    - ``ConversationRuntime`` — generic loop; system prompt passed in.
    - Assistant wrappers — assemble their own prompt per turn.

    The channel calls ``run_turn(session, user_text)`` and renders whatever
    ``AgentEvent``s come out. If the implementation needs more context
    (e.g. a system prompt), it owns it internally — channels don't supply it.
    """

    def run_turn(
        self,
        session: AgentSession,
        user_text: str,
    ) -> AsyncIterator[AgentEvent]: ...
