"""桥接飞书 channel 与 ConversationRuntime — non-streaming MVP。

对齐 openclaw runtime injection(plugin runtime),berry 这里直接以
依赖注入形式持有一个 `TurnRunner`,不走 module-level singleton。

职责:
- 给定 conversation_id + user_text,内部完成 load session → run_turn →
  drain 全部 AgentEvent → 把新消息 append 到 SessionStore → 返回 final
  assistant text。
- 错误兜底:LLM / 工具异常时不再 raise,返回一段简短错误提示文本,让
  上层用 send_text 兜底回个错误信息(不让用户在飞书侧空等)。

未来上 streaming card:把 `run_turn` 的 AgentEvent 喂给 reply dispatcher
(openclaw `reply-dispatcher.ts` 同款),不再 drain 完才送 — 接口扩一个
`run_turn_streaming` 方法,本类保留 `run_turn` 作为兼容入口。
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from berry.channels.feishu.session_file import load_or_create_session
from berry.core.agent.events import TextDelta, ToolResult, TurnEnd
from berry.core.agent.turn_runner import TurnRunner
from berry.core.llm.types import LlmMessage, TextBlock
from berry.observability.logging import get_logger

logger = get_logger(__name__)


class FeishuRuntimeAdapter:
    """非流式 turn 桥接。

    Args:
        runner: 任意 TurnRunner 实现(MVP 装的是包了 ConversationRuntime
            的 thin wrapper)。
        state_dir: 飞书 channel 状态根目录,session 文件落在这里。
        default_user_id: 把所有飞书消息 attribute 给这个 user — MVP
            不做飞书 user → berry user 的真映射(单用户场景)。
    """

    def __init__(
        self,
        *,
        runner: TurnRunner,
        state_dir: Path,
        default_user_id: UUID,
    ) -> None:
        self._runner = runner
        self._state_dir = state_dir
        self._default_user_id = default_user_id
        # session_id → (chat_id, sender_open_id, trigger_message_id) — populated
        # for the duration of one ``run_turn`` so that ``FeishuApprovalChannel``
        # can look up which chat to send the approval card to *and* reply
        # the card under the original trigger message in group chats.
        # Cleared in the finally block so a stale entry never leaks into
        # another turn.
        self._chat_context: dict[str, tuple[str, str, str]] = {}

    def chat_resolver(
        self, session_id: str,
    ) -> tuple[str | None, str | None, str | None]:
        """``session_id -> (chat_id, expected_user_open_id, trigger_message_id)``.

        Returns ``(None, None, None)`` if the session is not currently in a
        Feishu turn (e.g. CLI-only session).

        ``trigger_message_id`` is the message_id of the user message that
        kicked this turn off; ``FeishuApprovalChannel`` uses it to reply
        the approval card under the trigger in group chats. DM also uses
        it (cards reply to the trigger DM); harmless either way.
        """
        return self._chat_context.get(session_id, (None, None, None))

    async def run_turn(
        self,
        conversation_id: str,
        user_text: str,
        *,
        chat_id: str,
        user_open_id: str,
        trigger_message_id: str,
    ) -> str:
        """跑一轮,返回最终给用户看的文本。

        Args:
            chat_id: Feishu chat that initiated this turn — passed through to
                ``FeishuApprovalChannel.ask`` via ``chat_resolver`` so the
                approval card lands in the same chat.
            user_open_id: the sender's open_id; used to pin the approval card's
                expected operator (only this user's clicks count).
            trigger_message_id: 触发本轮的用户消息 ID,审批卡片 reply 到它,
                让卡片紧跟触发消息(群聊关键,DM 也安全)。

        Returns:
            assistant 的 final text(已合并所有 TextDelta)。出错时返回一段
            错误提示文本,绝不 raise。
        """
        session, store = load_or_create_session(
            state_dir=self._state_dir,
            conversation_id=conversation_id,
            user_id=self._default_user_id,
        )
        pre_count = len(session.messages)
        self._chat_context[session.id] = (chat_id, user_open_id, trigger_message_id)

        text_buffer: list[str] = []
        try:
            try:
                async for ev in self._runner.run_turn(session=session, user_text=user_text):
                    if isinstance(ev, TextDelta):
                        text_buffer.append(ev.text)
                    elif isinstance(ev, ToolResult):
                        # 工具结果不直接进飞书 — runtime 已经把它放进消息历史 / 下一轮上下文。
                        # MVP 只从最终 assistant text 提取给用户看的内容。
                        pass
                    elif isinstance(ev, TurnEnd):
                        pass
                    # TurnStart / ApprovalAsked / ToolCallStart 在 MVP 不渲染 — 后续接
                    # streaming card / approval 卡片再用。
            except Exception as exc:
                logger.error(
                    "feishu_turn_failed",
                    conversation_id=conversation_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    exc_info=True,
                )
                # 兜底持久化:即便出错,也把已写入 session.messages 的内容落盘
                self._persist_new(session, store, pre_count)
                return f"berry 出错了:{type(exc).__name__}: {exc}"

            # 把这轮新增的所有消息 append 到磁盘(参考 gateway/methods/turn.py 同款套路)
            self._persist_new(session, store, pre_count)

            # 把 buffer 里的 TextDelta 合起来作为返回值。
            # 如果 buffer 为空(LLM 一句没说就 stop_reason),回退到 session 末尾
            # 那条 assistant 消息的 text。
            if text_buffer:
                return _strip_or_fallback("".join(text_buffer))
            return _extract_last_assistant_text(session) or "(berry 没有回复内容)"
        finally:
            # Always clear chat_context so a later approval click can't bind
            # to a stale (chat_id, user_open_id) from a finished turn.
            self._chat_context.pop(session.id, None)

    @staticmethod
    def _persist_new(
        session: object,
        store: object,
        pre_count: int,
    ) -> None:
        new_messages = session.messages[pre_count:]  # type: ignore[attr-defined]
        for msg in new_messages:
            store.append_message(msg)  # type: ignore[attr-defined]


def _strip_or_fallback(text: str) -> str:
    s = text.strip()
    return s or "(berry 没有回复内容)"


def _extract_last_assistant_text(session: object) -> str | None:
    msgs = list(getattr(session, "messages", []))
    for msg in reversed(msgs):
        if not isinstance(msg, LlmMessage) or msg.role != "assistant":
            continue
        parts = [b.text for b in msg.content if isinstance(b, TextBlock) and b.text]
        if parts:
            return "".join(parts).strip() or None
    return None
