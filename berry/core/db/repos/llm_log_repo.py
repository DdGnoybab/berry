"""Repository for the `llm_call_logs` table.

Append-only audit log: every LLM call writes one row with the full
LlmRequest + LlmResponse as JSONB. Streaming responses are reassembled
into a non-streaming LlmResponse before being written (in Round 3).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import LlmCallLog
from berry.core.llm.types import LlmRequest, LlmResponse


class LlmLogRepo:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def append(
        self,
        session_id: UUID,
        request: LlmRequest,
        response: LlmResponse,
    ) -> LlmCallLog:
        row = LlmCallLog(
            session_id=session_id,
            request=request.model_dump(mode="json"),
            response=response.model_dump(mode="json"),
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row
