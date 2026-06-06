"""ApprovalRegistry - in-process asyncio.Future bridge for in-flight approvals.

Flow:
  1. ConversationRuntime detects tool needs approval -> calls register(approval_id) to get Future
  2. ConversationRuntime triggers ApprovalChannel.ask() -> channel renders approval UI
     (CLI: stdin Y/n; Feishu: card buttons; Web: yields ApprovalAsked event in stream)
  3. Channel attaches metadata (e.g. message_id, tool_name, args) so the UI's
     callback handler can later read these to render the resolved card without
     keeping its own state.
  4. User responds -> channel handler calls resolve(approval_id, decision) -> Future completes
  5. ConversationRuntime awaits Future -> gets decision, continues / rejects tool
  6. Channel's ``ask`` finally-block calls ``cleanup(approval_id)`` to release
     both the future and the metadata. Note: ``resolve`` does NOT delete
     metadata, because the UI callback handler may still need to read it
     between resolve and cleanup.

Single-process scope: MVP works with direct Future. Multi-process needs Redis pub/sub.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from typing import Any


class ApprovalAlreadyResolvedError(Exception):
    """Same approval_id resolved twice."""


class ApprovalNotFoundError(Exception):
    """approval_id does not exist or has expired."""


@dataclass
class ApprovalDecision:
    """Result delivered to ApprovalRegistry waiter."""

    approved: bool
    reason: str | None = None


class ApprovalRegistry:
    """In-process in-flight approvals registry.

    Singleton-style usage: one per process. CallContext does not hold it,
    because cross-channel scenarios (CLI triggers, Web user responds)
    need both sides to find the same registry.
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[ApprovalDecision]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def generate_id(self) -> str:
        """Generate a new approval_id."""
        return f"appr_{secrets.token_hex(8)}"

    def register(
        self, approval_id: str | None = None
    ) -> tuple[str, asyncio.Future[ApprovalDecision]]:
        """Register a new approval, return (approval_id, future).

        Caller awaits future for the result. If approval_id not given, generates one.
        """
        aid = approval_id or self.generate_id()
        if aid in self._pending:
            raise ApprovalAlreadyResolvedError(
                f"approval_id {aid!r} already pending"
            )
        future: asyncio.Future[ApprovalDecision] = (
            asyncio.get_event_loop().create_future()
        )
        self._pending[aid] = future
        self._metadata[aid] = {}
        return aid, future

    def attach_metadata(self, approval_id: str, data: dict[str, Any]) -> None:
        """Merge ``data`` into this approval's metadata dict.

        Channels stash ``message_id`` / ``tool_name`` / ``args`` here so the
        card_action handler can read them when the user clicks a button.

        Raises:
            ApprovalNotFoundError: approval_id never registered or already cleaned up
        """
        if approval_id not in self._metadata:
            raise ApprovalNotFoundError(approval_id)
        self._metadata[approval_id].update(data)

    def get_metadata(self, approval_id: str) -> dict[str, Any]:
        """Return a *copy* of the metadata dict (safe to mutate by caller).

        Returns ``{}`` if unknown — callers tolerate missing metadata
        (e.g. handler fires after cleanup race).
        """
        return dict(self._metadata.get(approval_id, {}))

    def resolve(
        self,
        approval_id: str,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> None:
        """User decision unblocks the waiter.

        Note: only the future is deleted; metadata is preserved so the UI
        callback handler (running just after resolve) can read it. Caller is
        responsible for ``cleanup`` once the metadata is no longer needed.

        Raises:
            ApprovalNotFoundError: approval_id does not exist
            ApprovalAlreadyResolvedError: already resolved
        """
        future = self._pending.get(approval_id)
        if future is None:
            raise ApprovalNotFoundError(
                f"unknown approval_id {approval_id!r}"
            )
        if future.done():
            raise ApprovalAlreadyResolvedError(
                f"approval {approval_id!r} already resolved"
            )
        future.set_result(ApprovalDecision(approved=approved, reason=reason))
        del self._pending[approval_id]

    async def wait(
        self, approval_id: str, timeout_seconds: float = 90.0
    ) -> ApprovalDecision:
        """After register, wait for result. Wraps register + await with timeout."""
        future = self._pending.get(approval_id)
        if future is None:
            raise ApprovalNotFoundError(approval_id)
        try:
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError:
            self._pending.pop(approval_id, None)
            return ApprovalDecision(approved=False, reason="approval timeout")

    def cleanup(self, approval_id: str) -> None:
        """Release both pending future and metadata. Idempotent."""
        self._pending.pop(approval_id, None)
        self._metadata.pop(approval_id, None)


# ─── Process-level singleton ────────────────────────────────


_global_registry: ApprovalRegistry | None = None


def get_approval_registry() -> ApprovalRegistry:
    """Process-level singleton.

    Main code (turn handler / approval handler) gets registry through this.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ApprovalRegistry()
    return _global_registry
