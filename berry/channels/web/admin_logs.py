"""Admin-only log viewer API.

Endpoints (all require role='admin'):
  GET /v1/admin/logs/files     — list rotated log files
  GET /v1/admin/logs/query     — paginated query with date/level/keyword filter
  GET /v1/admin/logs/stream    — SSE tail of the active berry.log
  GET /v1/admin/logs/download  — download a single day's file (gz or plain)

Storage model (writer side: berry/observability/logging.py):
  settings.log_dir/
    berry.log                   ← active, written line-by-line as JSON
    berry.log.2026-06-12.gz     ← rotated days, gzipped
    berry.log.2026-06-11.gz
    ...

Each line is one structlog JSON record. Bad lines (ill-formed JSON) get
surfaced with event="_unparsed" so the UI shows them rather than dropping.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from berry.channels.web.auth.deps import AdminUser, require_admin
from berry.config import settings
from berry.observability.logging import get_logger

router = APIRouter(prefix="/v1/admin/logs", tags=["admin", "logs"])
logger = get_logger(__name__)


# ─── helpers ───────────────────────────────────────────────────


_DATE_FROM_NAME = re.compile(r"^berry\.log\.(\d{4}-\d{2}-\d{2})\.gz$")


def _log_dir() -> Path:
    """Resolve log dir from settings, ensure it exists."""
    p = Path(settings.log_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _list_files() -> list[dict[str, Any]]:
    """List all log files, newest first."""
    out: list[dict[str, Any]] = []
    d = _log_dir()
    if not d.is_dir():
        return out
    for entry in d.iterdir():
        if not entry.is_file():
            continue
        if entry.name == "berry.log":
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            out.append(
                {
                    "name": entry.name,
                    "date": today,
                    "size": entry.stat().st_size,
                    "compressed": False,
                    "active": True,
                }
            )
            continue
        m = _DATE_FROM_NAME.match(entry.name)
        if not m:
            continue
        out.append(
            {
                "name": entry.name,
                "date": m.group(1),
                "size": entry.stat().st_size,
                "compressed": True,
                "active": False,
            }
        )
    # newest day first
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def _files_covering_range(date_from: datetime, date_to: datetime) -> list[Path]:
    """Pick the subset of log files whose date overlaps the given range.

    Returns paths newest-day-first so the caller can read newest → oldest
    and short-circuit on `limit`.
    """
    d = _log_dir()
    if not d.is_dir():
        return []

    today = datetime.now(UTC).date()
    from_d = date_from.date()
    to_d = date_to.date()

    picked: list[tuple[str, Path]] = []
    # active file represents today
    active = d / "berry.log"
    if active.exists() and from_d <= today <= to_d:
        picked.append((today.isoformat(), active))
    # rotated files
    for entry in d.iterdir():
        if not entry.is_file():
            continue
        m = _DATE_FROM_NAME.match(entry.name)
        if not m:
            continue
        date_str = m.group(1)
        try:
            ymd = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if from_d <= ymd <= to_d:
            picked.append((date_str, entry))
    picked.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in picked]


def _open_lines(path: Path) -> Iterable[str]:
    """Yield decoded lines from path, transparently handling .gz."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            yield from f
    else:
        with open(path, "rt", encoding="utf-8", errors="replace") as f:
            yield from f


def _parse_line(line: str) -> dict[str, Any] | None:
    """Parse one JSON line. Return None to drop, dict to keep.

    Bad JSON gets surfaced as event='_unparsed' (the UI displays raw text)
    so we never silently drop lines an admin came here to find.
    """
    line = line.rstrip("\n")
    if not line:
        return None
    try:
        obj = json.loads(line)
        if not isinstance(obj, dict):
            return {"event": "_unparsed", "level": "info", "raw_text": line}
        return obj
    except json.JSONDecodeError:
        return {"event": "_unparsed", "level": "info", "raw_text": line}


def _record_matches(
    rec: dict[str, Any],
    date_from: datetime,
    date_to: datetime,
    levels: set[str] | None,
    keyword: str | None,
) -> bool:
    """Apply level/keyword/time filters to one parsed record."""
    # level (case-insensitive)
    if levels:
        rec_lvl = str(rec.get("level", "")).upper()
        if rec_lvl not in levels:
            return False
    # time
    ts_str = rec.get("timestamp") or rec.get("ts")
    if ts_str:
        try:
            # structlog TimeStamper(fmt='iso', utc=True) → '2026-06-13T14:23:01.124000Z'
            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            if ts < date_from or ts > date_to:
                return False
        except (ValueError, TypeError):
            pass  # malformed ts → don't drop, let admin see it
    # keyword (substring, case-insensitive, against the whole JSON line)
    if keyword:
        # cheap match: serialize once, search once
        haystack = json.dumps(rec, ensure_ascii=False).lower()
        if keyword.lower() not in haystack:
            return False
    return True


# ─── routes ────────────────────────────────────────────────────


@router.get("/files")
async def list_log_files(
    admin: AdminUser = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List every log file currently on disk (active + rotated)."""
    return _list_files()


@router.get("/query")
async def query_logs(
    date_from: datetime = Query(..., description="ISO datetime, inclusive"),
    date_to: datetime = Query(..., description="ISO datetime, inclusive"),
    level: list[str] | None = Query(default=None, description="repeatable: level=ERROR&level=WARN"),
    q: str | None = Query(default=None, description="case-insensitive substring"),
    limit: int = Query(default=200, ge=1, le=1000),
    cursor: int = Query(default=0, ge=0, description="opaque, # of records already returned"),
    admin: AdminUser = Depends(require_admin),
) -> dict[str, Any]:
    """Filter + paginate logs.

    Implementation:
      1. Pick files overlapping [date_from, date_to], newest-day-first.
      2. Within each file, scan lines top-to-bottom.
      3. Apply filters; collect into a buffer.
      4. After scanning all candidate files, reverse-sort by ts descending,
         slice [cursor : cursor+limit].

    For our scale (≤ 7 days, single-server, ~MB-class files) this is
    fine — loading a day's file fully and sorting in memory is well under
    a second. If volume grows, swap to per-file streaming with a min-heap.
    """
    # normalize timezone (Query parses naive ISO as naive datetime)
    if date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=UTC)
    if date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=UTC)
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from > date_to")

    levels = {lv.upper() for lv in level} if level else None
    keyword = q.strip() if q else None

    files = _files_covering_range(date_from, date_to)
    matched: list[dict[str, Any]] = []
    scanned = 0

    for path in files:
        try:
            for line in _open_lines(path):
                scanned += 1
                rec = _parse_line(line)
                if rec is None:
                    continue
                if _record_matches(rec, date_from, date_to, levels, keyword):
                    matched.append(rec)
        except OSError as e:
            logger.warning("log_read_failed", path=str(path), error=str(e))
            continue

    # newest first by timestamp
    def _ts_key(r: dict[str, Any]) -> str:
        return str(r.get("timestamp") or r.get("ts") or "")

    matched.sort(key=_ts_key, reverse=True)

    page = matched[cursor : cursor + limit]
    next_cursor = cursor + len(page) if cursor + len(page) < len(matched) else None

    return {
        "lines": page,
        "next_cursor": next_cursor,
        "total_matched": len(matched),
        "total_scanned": scanned,
    }


@router.get("/stream")
async def stream_logs(
    request: Request,
    admin: AdminUser = Depends(require_admin),
) -> StreamingResponse:
    """SSE: tail the active berry.log.

    Behavior:
      - On connect, immediately send the last 200 lines as backfill so the
        page isn't empty before new events land.
      - Then poll the file for new bytes every 0.5s, emit each new line.
      - Heartbeat every 30s (`: keepalive\\n\\n`) to keep nginx / browsers happy.
      - If the file is rotated (inode change / size shrink), reopen.
      - Disconnect → task cancelled, file handle closed.
    """

    async def event_stream() -> AsyncIterator[bytes]:
        path = _log_dir() / "berry.log"

        # ── backfill: last 200 lines ──
        if path.exists():
            try:
                with open(path, "rt", encoding="utf-8", errors="replace") as backfill_f:
                    tail_lines = backfill_f.readlines()[-200:]
                for line in tail_lines:
                    rec = _parse_line(line)
                    if rec is not None:
                        yield f"data: {json.dumps(rec, ensure_ascii=False)}\n\n".encode()
            except OSError as e:
                logger.warning("log_stream_backfill_failed", error=str(e))

        # ── live tail ──
        last_inode = -1
        last_size = 0
        f: Any = None
        last_heartbeat = 0.0
        try:
            while True:
                if await request.is_disconnected():
                    break

                # (re)open if needed
                try:
                    st = path.stat()
                    inode = st.st_ino
                    size = st.st_size
                except FileNotFoundError:
                    await asyncio.sleep(1.0)
                    continue

                if f is None or inode != last_inode or size < last_size:
                    if f is not None:
                        f.close()
                    f = open(path, "rt", encoding="utf-8", errors="replace")
                    if last_inode == -1:
                        # first open: seek to end (we already backfilled)
                        f.seek(0, 2)
                    last_inode = inode
                    last_size = size

                # read whatever's new
                line = f.readline()
                if line:
                    if line.endswith("\n"):
                        rec = _parse_line(line)
                        if rec is not None:
                            yield f"data: {json.dumps(rec, ensure_ascii=False)}\n\n".encode()
                        last_size = f.tell()
                    else:
                        # incomplete (writer mid-line) — back off and retry
                        f.seek(f.tell() - len(line))
                        await asyncio.sleep(0.3)
                else:
                    # nothing new; heartbeat if idle long enough
                    now = asyncio.get_event_loop().time()
                    if now - last_heartbeat > 30.0:
                        yield b": keepalive\n\n"
                        last_heartbeat = now
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            if f is not None:
                f.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # belt + suspenders against nginx buffering
            "Connection": "keep-alive",
        },
    )


@router.get("/download")
async def download_log(
    date: str = Query(..., description="YYYY-MM-DD"),
    admin: AdminUser = Depends(require_admin),
) -> FileResponse:
    """Download a single day's log file.

    Today → active berry.log (uncompressed).
    Past day → berry.log.YYYY-MM-DD.gz.
    """
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="bad date format, want YYYY-MM-DD")

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    d = _log_dir()
    if date == today:
        path = d / "berry.log"
        filename = f"berry.log.{today}"
        media_type = "text/plain"
    else:
        path = d / f"berry.log.{date}.gz"
        filename = path.name
        media_type = "application/gzip"

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no log for {date}")

    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=filename,
    )
