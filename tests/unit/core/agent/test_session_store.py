"""Unit tests for SessionStore: create / append / rotate / load."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from berry.core.agent.session_store import (
    MAX_ROTATED_FILES,
    ROTATE_AFTER_BYTES,
    SessionStore,
    generate_session_id,
)
from berry.core.llm.types import LlmMessage, TextBlock

# --- generate_session_id -----------------------------------------------------


def test_generate_session_id_format() -> None:
    sid = generate_session_id()
    # like 20260604T152300-a3d2
    assert len(sid) == len("20260604T152300-a3d2")
    assert sid[8] == "T"
    assert sid[15] == "-"


def test_generate_session_id_unique_calls() -> None:
    ids = {generate_session_id() for _ in range(100)}
    # 99% probability all different (4 hex within same second)
    assert len(ids) >= 99


# --- create / read meta ------------------------------------------------------


def test_create_writes_meta_and_empty_messages(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    user_id = uuid4()
    project_id = uuid4()
    sid = "20260604T120000-aaaa"

    meta = store.create(
        session_id=sid,
        user_id=user_id,
        project_id=project_id,
        channel="cli",
    )

    assert store.dir.is_dir()
    assert store.meta_path.exists()
    assert store.messages_path.exists()
    assert store.messages_path.stat().st_size == 0

    assert meta.id == sid
    assert meta.user_id == str(user_id)
    assert meta.project_id == str(project_id)
    assert meta.channel == "cli"
    assert meta.status == "active"


def test_read_meta_after_create(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    sid = generate_session_id()
    store.create(
        session_id=sid,
        user_id=uuid4(),
        project_id=uuid4(),
        channel="web",
    )
    loaded = store.read_meta()
    assert loaded is not None
    assert loaded.id == sid
    assert loaded.channel == "web"


def test_read_meta_nonexistent(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    assert store.read_meta() is None


def test_update_meta(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    store.create(
        session_id=generate_session_id(),
        user_id=uuid4(),
        project_id=uuid4(),
        channel="cli",
    )
    store.update_meta(status="completed", title="test")
    meta = store.read_meta()
    assert meta is not None
    assert meta.status == "completed"
    assert meta.title == "test"


# --- append + load -----------------------------------------------------------


def test_append_and_load_messages(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    store.create(
        session_id=generate_session_id(),
        user_id=uuid4(),
        project_id=uuid4(),
        channel="cli",
    )

    msg1 = LlmMessage(role="user", content=[TextBlock(text="hello")])
    msg2 = LlmMessage(role="assistant", content=[TextBlock(text="hi there")])

    store.append_message(msg1)
    store.append_message(msg2)

    loaded = store.load_all_messages()
    assert len(loaded) == 2
    assert loaded[0]["role"] == "user"
    assert loaded[0]["content"][0]["text"] == "hello"
    assert loaded[1]["role"] == "assistant"
    assert loaded[1]["content"][0]["text"] == "hi there"


def test_append_preserves_unicode(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    store.create(
        session_id=generate_session_id(),
        user_id=uuid4(),
        project_id=uuid4(),
        channel="cli",
    )
    store.append_message(
        LlmMessage(role="user", content=[TextBlock(text="你好世界")])
    )
    loaded = store.load_all_messages()
    assert loaded[0]["content"][0]["text"] == "你好世界"


# --- rotation ----------------------------------------------------------------


def test_rotation_when_exceeding_threshold(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    store.create(
        session_id=generate_session_id(),
        user_id=uuid4(),
        project_id=uuid4(),
        channel="cli",
    )

    # Write a message close to the rotate threshold
    big_text = "x" * (ROTATE_AFTER_BYTES - 200)
    store.append_message(LlmMessage(role="user", content=[TextBlock(text=big_text)]))
    assert store.messages_path.stat().st_size > 0
    assert not (store.dir / "messages.1.jsonl").exists()

    # Write another -> triggers rotation
    store.append_message(LlmMessage(role="assistant", content=[TextBlock(text="y" * 1000)]))
    assert (store.dir / "messages.1.jsonl").exists()
    new_lines = (store.dir / "messages.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(new_lines) == 1


def test_load_all_includes_rotated_files(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    store.create(
        session_id=generate_session_id(),
        user_id=uuid4(),
        project_id=uuid4(),
        channel="cli",
    )

    big = "x" * (ROTATE_AFTER_BYTES - 200)
    store.append_message(LlmMessage(role="user", content=[TextBlock(text=big)]))
    store.append_message(LlmMessage(role="assistant", content=[TextBlock(text="middle")]))
    store.append_message(LlmMessage(role="user", content=[TextBlock(text=big)]))
    store.append_message(LlmMessage(role="assistant", content=[TextBlock(text="latest")]))

    loaded = store.load_all_messages()
    assert len(loaded) == 4
    texts = [m["content"][0]["text"] for m in loaded]
    assert texts[1] == "middle"
    assert texts[3] == "latest"


def test_oldest_rotated_dropped_after_max(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    store.create(
        session_id=generate_session_id(),
        user_id=uuid4(),
        project_id=uuid4(),
        channel="cli",
    )
    big = "x" * (ROTATE_AFTER_BYTES - 200)
    for i in range(MAX_ROTATED_FILES + 2):
        store.append_message(
            LlmMessage(role="user", content=[TextBlock(text=big)])
        )
        store.append_message(
            LlmMessage(role="assistant", content=[TextBlock(text=f"r{i}")])
        )

    for i in range(1, MAX_ROTATED_FILES + 1):
        assert (store.dir / f"messages.{i}.jsonl").exists(), (
            f"messages.{i}.jsonl missing"
        )
    assert not (store.dir / f"messages.{MAX_ROTATED_FILES + 1}.jsonl").exists()


# --- load robustness ---------------------------------------------------------


def test_load_skips_blank_lines(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sess")
    store.create(
        session_id=generate_session_id(),
        user_id=uuid4(),
        project_id=uuid4(),
        channel="cli",
    )
    store.messages_path.write_text(
        '{"role":"user","content":[{"type":"text","text":"hi"}],"created_at":"2026-06-04T00:00:00+00:00","metadata":{}}\n'
        "\n"
        "\n"
        '{"role":"assistant","content":[{"type":"text","text":"yo"}],"created_at":"2026-06-04T00:00:01+00:00","metadata":{}}\n',
        encoding="utf-8",
    )
    loaded = store.load_all_messages()
    assert len(loaded) == 2
