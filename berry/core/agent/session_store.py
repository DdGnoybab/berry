"""Session file persistence: meta.json + messages.jsonl (rotated).

claw-code session.rs equivalent rotation:
  - Single file exceeds ROTATE_AFTER_BYTES -> rename messages.jsonl ->
    messages.1.jsonl, .1 -> .2, .2 -> .3, old .3 deleted
  - Load by reading all .jsonl files in reverse order (.3 .2 .1 current)
    to reconstruct full history

No concurrency concern: single user, single process, no simultaneous
writes to the same session.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from berry.core.llm.types import LlmMessage

# Match claw-code defaults
ROTATE_AFTER_BYTES = 256 * 1024
MAX_ROTATED_FILES = 3


# --- ID generation -----------------------------------------------------------


def generate_session_id() -> str:
    """Generate session_id: `<UTC ISO compact>-<4 hex>`.

    Example: `20260604T152300-a3d2`
    Readable + collision-resistant + sorts naturally with `ls`.
    """
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    suffix = secrets.token_hex(2)
    return f"{now}-{suffix}"


# --- meta.json model ---------------------------------------------------------


@dataclass
class SessionMetaData:
    """meta.json deserialized form.

    Deliberately a dataclass not pydantic -- this layer is just a JSON dict,
    no extra validation needed. Pydantic form lives in
    protocol.methods_core.SessionMeta (for method handler use).
    """

    schema_version: int
    id: str
    user_id: str
    project_id: str
    channel: str
    status: str           # "active" / "completed" / "abandoned"
    started_at: str       # ISO string
    ended_at: str | None
    title: str | None
    metadata: dict[str, Any]


# --- SessionStore ------------------------------------------------------------


class SessionStore:
    """Session file persistence entry point.

    All session file operations go through this class; business code does
    not touch the filesystem directly.
    """

    def __init__(self, session_dir: Path) -> None:
        """Args:
            session_dir: ProjectService.session_dir(project, sid).
                Directory may not exist yet (create will mkdir).
        """
        self._dir = session_dir

    @property
    def dir(self) -> Path:
        """Session directory path."""
        return self._dir

    @property
    def meta_path(self) -> Path:
        """Path to meta.json."""
        return self._dir / "meta.json"

    @property
    def messages_path(self) -> Path:
        """Path to current messages.jsonl."""
        return self._dir / "messages.jsonl"

    # -- create ---------------------------------------------------------------

    def create(
        self,
        *,
        session_id: str,
        user_id: UUID,
        project_id: UUID,
        channel: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMetaData:
        """Initialize session dir: mkdir + write meta.json + touch messages.jsonl.

        Args:
            session_id: Pre-generated session ID (use generate_session_id()).
            user_id: Owning user UUID.
            project_id: Owning project UUID.
            channel: Originating channel name (e.g. "feishu", "cli").
            metadata: Optional extra key/value pairs stored in meta.json.

        Returns:
            The freshly written SessionMetaData.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).isoformat()
        meta = SessionMetaData(
            schema_version=1,
            id=session_id,
            user_id=str(user_id),
            project_id=str(project_id),
            channel=channel,
            status="active",
            started_at=now,
            ended_at=None,
            title=None,
            metadata=metadata or {},
        )
        self._write_meta(meta)
        # Touch empty messages.jsonl so the file exists even before first message
        self.messages_path.touch(exist_ok=True)
        return meta

    # -- meta read/write ------------------------------------------------------

    def read_meta(self) -> SessionMetaData | None:
        """Read meta.json.

        Returns:
            SessionMetaData if the file exists, None otherwise.
        """
        if not self.meta_path.exists():
            return None
        data = json.loads(self.meta_path.read_text(encoding="utf-8"))
        return SessionMetaData(**data)

    def update_meta(self, **changes: Any) -> SessionMetaData:
        """Apply field updates to meta.json atomically.

        Args:
            **changes: Keyword arguments matching SessionMetaData field names.

        Returns:
            Updated SessionMetaData after writing.

        Raises:
            FileNotFoundError: If meta.json does not exist.
        """
        meta = self.read_meta()
        if meta is None:
            raise FileNotFoundError(f"no meta.json in {self._dir!r}")
        for k, v in changes.items():
            setattr(meta, k, v)
        self._write_meta(meta)
        return meta

    def _write_meta(self, meta: SessionMetaData) -> None:
        """Write meta atomically via a .tmp file + rename."""
        tmp = self.meta_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(meta.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.meta_path)

    # -- messages append + rotate ---------------------------------------------

    def append_message(
        self,
        message: LlmMessage,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append one message to messages.jsonl.

        Triggers rotation if adding this line would push the current file
        over ROTATE_AFTER_BYTES.

        Each line = one JSON object (UTF-8, no BOM).

        Args:
            message: The LlmMessage to persist.
            metadata: Optional extra key/value pairs stored alongside the
                message envelope (e.g. tool_call_id, latency_ms).
        """
        meta = dict(metadata) if metadata else {}
        # Auto-tag synthetic messages so the frontend can hide them when
        # rebuilding chat history. These messages are real LLM context
        # (priming requests, memory injections) but never typed by the
        # user — showing them on history reload looks like leakage.
        if "synthetic" not in meta:
            kind = _detect_synthetic_kind(message)
            if kind is not None:
                meta["synthetic"] = True
                meta["synthetic_kind"] = kind
        envelope = {
            "role": message.role,
            "content": [block.model_dump() for block in message.content],
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": meta,
        }
        # Sanitize surrogate halves (e.g. when an upstream SSE chunk splits a
        # multi-byte emoji and the SDK leaves lone surrogates in the str). UTF-8
        # encoding rejects them with surrogates_not_allowed; replace them so
        # we never lose a turn over an encoding edge case.
        line_bytes = (json.dumps(envelope, ensure_ascii=False) + "\n").encode(
            "utf-8", errors="replace"
        )
        line = line_bytes.decode("utf-8")

        # Check whether rotation is needed before writing
        if self.messages_path.exists():
            size = self.messages_path.stat().st_size
            if size + len(line_bytes) > ROTATE_AFTER_BYTES:
                self._rotate()

        # Append (mkdir in case this is called without create())
        self.messages_path.parent.mkdir(parents=True, exist_ok=True)
        with self.messages_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _rotate(self) -> None:
        """Rotate message files: messages.jsonl -> .1, .1 -> .2, .2 -> .3, .3 dropped."""
        # Drop oldest if it exists
        oldest = self._dir / f"messages.{MAX_ROTATED_FILES}.jsonl"
        if oldest.exists():
            oldest.unlink()

        # Rename in reverse order: .{N-1} -> .N
        for i in range(MAX_ROTATED_FILES - 1, 0, -1):
            src = self._dir / f"messages.{i}.jsonl"
            dst = self._dir / f"messages.{i + 1}.jsonl"
            if src.exists():
                src.rename(dst)

        # Current messages.jsonl -> .1
        if self.messages_path.exists():
            self.messages_path.rename(self._dir / "messages.1.jsonl")

    # -- read messages --------------------------------------------------------

    def list_message_files_oldest_first(self) -> list[Path]:
        """Return all message files from oldest to newest.

        Order: messages.3.jsonl -> messages.2.jsonl -> messages.1.jsonl ->
        messages.jsonl (current).

        Returns:
            List of Paths that exist, in oldest-to-newest order.
        """
        files: list[Path] = []
        for i in range(MAX_ROTATED_FILES, 0, -1):
            p = self._dir / f"messages.{i}.jsonl"
            if p.exists():
                files.append(p)
        if self.messages_path.exists():
            files.append(self.messages_path)
        return files

    # ─── synthetic detection (used by append_message above) ────────────

    def load_all_messages(self) -> list[dict[str, Any]]:
        """Return complete message envelope list (oldest to newest).

        Each envelope: {role, content, created_at, metadata}.
        Callers (e.g. persistence.py) convert envelopes to LlmMessage.

        Blank lines are skipped (safe against trailing newlines or manual
        edits).

        Returns:
            List of message envelope dicts in chronological order.
        """
        out: list[dict[str, Any]] = []
        for p in self.list_message_files_oldest_first():
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    out.append(json.loads(stripped))
        return out


# ─── synthetic-message detection ────────────────────────────────────────


_SYNTHETIC_PRIMING_PREFIXES = (
    "我刚选好了学习计划",   # learning.create_project priming
    "请按 SKILL.md",        # session.resume_create / generic priming
    "<<session-error>>",
    "<<plan-result>>",
)


def _detect_synthetic_kind(message: LlmMessage) -> str | None:
    """Identify messages that should not appear in user-visible chat history.

    Returns a kind label (e.g. ``"priming"``, ``"memory_injection"``,
    ``"reminder"``) or ``None`` if the message is genuine user/assistant
    content. Detection is content-based since the call sites don't tag
    these messages explicitly today.
    """
    if message.role != "user":
        return None

    text_parts: list[str] = []
    for block in message.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
    if not text_parts:
        return None
    blob = "".join(text_parts).lstrip()
    if not blob:
        return None

    if "<system-reminder>" in blob:
        # Memory injection / nag reminder / runtime tag — never user text.
        return "reminder"
    for prefix in _SYNTHETIC_PRIMING_PREFIXES:
        if blob.startswith(prefix):
            return "priming"
    return None
