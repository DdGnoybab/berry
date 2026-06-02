"""Repository for `llm_call_logs`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import LlmCallLog
from berry.utils.unicode import strip_surrogates_deep as _strip_surrogates


class LlmLogRepo:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def append(
        self,
        *,
        user_id: UUID,
        project_id: UUID | None,
        session_id: str | None,
        model: str,
        request: dict[str, Any],
        response: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> LlmCallLog:
        row = LlmCallLog(
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            model=model,
            request=_strip_surrogates(request),
            response=_strip_surrogates(response),
            metadata_=_strip_surrogates(metadata or {}),
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row
