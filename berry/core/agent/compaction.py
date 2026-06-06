"""四层上下文压缩管线 — 便宜的先跑，贵的后跑。

对齐 s08 / claw-code compact.ts 设计:
  L3: tool_result_budget  — 大结果落盘（0 API）
  L1: snip_compact        — 裁掉无关旧对话（0 API）
  L2: micro_compact       — 旧工具结果占位（0 API）
  L4: compact_history     — LLM 全量摘要（1 API）

执行顺序 budget → snip → micro 不能换:
budget 必须在 micro 替换旧结果之前把完整内容落盘。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from berry.core.llm.types import (
    LlmMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from berry.observability.logging import get_logger

logger = get_logger(__name__)

# ─── 常量 ─────────────────────────────────────────────────────────────────

DEFAULT_MAX_MESSAGES = 50
DEFAULT_KEEP_HEAD = 3
DEFAULT_KEEP_RECENT_TOOL_RESULTS = 3
DEFAULT_TOOL_RESULT_BUDGET_BYTES = 200_000
DEFAULT_AUTO_COMPACT_TOKENS = 100_000
DEFAULT_PRESERVE_RECENT = 4
MAX_COMPACT_FAILURES = 3

_CONTINUATION_PREAMBLE = (
    "This session is being continued from a previous conversation that was "
    "compacted to save context space. The summary below covers the earlier "
    "portion of the conversation.\n\n"
)
_DIRECT_RESUME = (
    "Continue the conversation from where it left off. "
    "Do not acknowledge the summary or recap what was happening."
)


# ─── 数据结构 ──────────────────────────────────────────────────────────────


@dataclass
class CompactionConfig:
    max_messages: int = DEFAULT_MAX_MESSAGES
    keep_head: int = DEFAULT_KEEP_HEAD
    keep_recent_tool_results: int = DEFAULT_KEEP_RECENT_TOOL_RESULTS
    tool_result_budget_bytes: int = DEFAULT_TOOL_RESULT_BUDGET_BYTES
    auto_compact_threshold: int = DEFAULT_AUTO_COMPACT_TOKENS
    preserve_recent: int = DEFAULT_PRESERVE_RECENT
    persist_dir: Path | None = None


@dataclass
class CompactionResult:
    messages: list[LlmMessage]
    removed_count: int = 0
    layer_applied: str = ""


# ─── Token 估算 ────────────────────────────────────────────────────────────


def estimate_tokens(messages: list[LlmMessage]) -> int:
    """粗估 token 数。len/4 + 1 per block。"""
    total = 0
    for msg in messages:
        for block in msg.content:
            if isinstance(block, TextBlock):
                total += len(block.text) // 4 + 1
            elif isinstance(block, ToolUseBlock):
                total += (len(block.name) + len(str(block.input))) // 4 + 1
            elif isinstance(block, ToolResultBlock):
                total += len(block.output) // 4 + 1
            else:
                total += 1
    return total


# ─── L3: tool_result_budget — 大结果落盘 ───────────────────────────────────


def tool_result_budget(
    messages: list[LlmMessage],
    max_bytes: int = DEFAULT_TOOL_RESULT_BUDGET_BYTES,
    persist_dir: Path | None = None,
) -> list[LlmMessage]:
    """最后一条 user 消息中所有 tool_result 总大小超限 → 从最大开始落盘。

    落盘后上下文只留前 2000 字符预览 + 标记。
    """
    if not messages:
        return messages

    last = messages[-1]
    if last.role != "user":
        return messages

    # 找出所有 ToolResultBlock
    result_indices: list[tuple[int, ToolResultBlock]] = []
    for i, block in enumerate(last.content):
        if isinstance(block, ToolResultBlock):
            result_indices.append((i, block))

    if not result_indices:
        return messages

    total = sum(len(b.output) for _, b in result_indices)
    if total <= max_bytes:
        return messages

    # 按大小降序，从最大的开始落盘
    ranked = sorted(result_indices, key=lambda p: len(p[1].output), reverse=True)
    persisted = 0

    for idx, block in ranked:
        if total <= max_bytes:
            break
        original_size = len(block.output)
        persisted_output = _persist_and_replace(block, persist_dir)
        block.output = persisted_output
        total -= original_size - len(persisted_output)
        persisted += 1

    if persisted:
        logger.info("compaction_l3_budget", persisted=persisted)

    return messages


def _persist_and_replace(block: ToolResultBlock, persist_dir: Path | None) -> str:
    """把大 tool_result 写到磁盘，返回占位文本。"""
    if persist_dir is None:
        persist_dir = Path.cwd() / ".berry" / "tool_outputs"

    persist_dir.mkdir(parents=True, exist_ok=True)
    out_path = persist_dir / f"{block.tool_use_id}.txt"

    try:
        out_path.write_text(block.output, encoding="utf-8")
    except OSError as exc:
        logger.warning("compaction_l3_persist_failed", error=str(exc))
        # 落盘失败 → 截断保留前 2000 字符
        return block.output[:2000] + f"\n[... truncated, full output was {len(block.output)} chars]"

    preview = block.output[:2000]
    return (
        f"{preview}\n\n"
        f"[Full output persisted to {out_path} ({len(block.output)} chars). "
        f"Read the file if you need the complete content.]"
    )


# ─── L1: snip_compact — 裁掉无关旧对话 ────────────────────────────────────


def snip_compact(
    messages: list[LlmMessage],
    max_messages: int = DEFAULT_MAX_MESSAGES,
    keep_head: int = DEFAULT_KEEP_HEAD,
) -> list[LlmMessage]:
    """消息数超限 → 保留头部 + 尾部，中间裁掉。"""
    if len(messages) <= max_messages:
        return messages

    keep_tail = max_messages - keep_head - 1  # -1 for placeholder
    snipped = len(messages) - keep_head - keep_tail

    placeholder = LlmMessage(
        role="user",
        content=[TextBlock(text=f"[snipped {snipped} messages from conversation middle]")],
    )

    logger.info("compaction_l1_snip", snipped=snipped, remaining=max_messages)
    return messages[:keep_head] + [placeholder] + messages[-keep_tail:]


# ─── L2: micro_compact — 旧工具结果占位 ────────────────────────────────────


def micro_compact(
    messages: list[LlmMessage],
    keep_recent: int = DEFAULT_KEEP_RECENT_TOOL_RESULTS,
) -> list[LlmMessage]:
    """只保留最近 N 条 tool_result 完整内容，更旧的替换为占位符。"""
    # 收集所有 ToolResultBlock 及其位置
    all_results: list[tuple[int, int, ToolResultBlock]] = []
    for msg_idx, msg in enumerate(messages):
        for blk_idx, block in enumerate(msg.content):
            if isinstance(block, ToolResultBlock):
                all_results.append((msg_idx, blk_idx, block))

    if len(all_results) <= keep_recent:
        return messages

    to_compact = all_results[:-keep_recent]
    compacted = 0

    for _, _, block in to_compact:
        if len(block.output) > 120:
            block.output = "[Earlier tool result compacted. Re-run if needed.]"
            compacted += 1

    if compacted:
        logger.info("compaction_l2_micro", compacted=compacted)

    return messages


# ─── L4: compact_history — LLM 全量摘要 ────────────────────────────────────


def compact_history(
    messages: list[LlmMessage],
    preserve_recent: int = DEFAULT_PRESERVE_RECENT,
    persist_dir: Path | None = None,
) -> CompactionResult:
    """前三层跑完仍超阈值 → 生成摘要替换旧消息。

    当前实现:纯文本提取（无 LLM 调用），对齐 berry 原有 compact_session。
    V1+ 可接入 LLM 生成更高质量摘要。
    """
    if len(messages) <= preserve_recent:
        return CompactionResult(messages=messages)

    # 保存 transcript
    _save_transcript(messages, persist_dir)

    # 分离旧消息和保留消息
    keep_from = max(0, len(messages) - preserve_recent)
    keep_from = _adjust_boundary_for_tool_pairs(messages, keep_from)

    old_messages = messages[:keep_from]
    preserved = messages[keep_from:]

    if not old_messages:
        return CompactionResult(messages=messages)

    # 生成摘要
    summary = _build_summary(old_messages)
    continuation = LlmMessage(
        role="user",
        content=[TextBlock(text=f"{_CONTINUATION_PREAMBLE}{summary}\n\n{_DIRECT_RESUME}")],
    )

    compacted = [continuation] + preserved

    logger.info(
        "compaction_l4_history",
        removed=len(old_messages),
        preserved=len(preserved),
    )

    return CompactionResult(
        messages=compacted,
        removed_count=len(old_messages),
        layer_applied="l4_history",
    )


# ─── 应急: reactive_compact ────────────────────────────────────────────────


def reactive_compact(
    messages: list[LlmMessage],
    preserve_recent: int = 5,
    persist_dir: Path | None = None,
) -> CompactionResult:
    """API 返回 prompt_too_long 时的应急压缩。比 L4 更激进。"""
    _save_transcript(messages, persist_dir)

    summary = _build_summary(messages[:-preserve_recent] if len(messages) > preserve_recent else messages)
    tail = messages[-preserve_recent:] if len(messages) > preserve_recent else messages

    continuation = LlmMessage(
        role="user",
        content=[TextBlock(text=f"[Reactive compact]\n\n{summary}\n\n{_DIRECT_RESUME}")],
    )

    logger.warning("compaction_reactive", original=len(messages), kept=len(tail))

    return CompactionResult(
        messages=[continuation] + tail,
        removed_count=len(messages) - len(tail),
        layer_applied="reactive",
    )


# ─── 管线入口 ──────────────────────────────────────────────────────────────


def apply_compaction_pipeline(
    messages: list[LlmMessage],
    config: CompactionConfig | None = None,
) -> tuple[list[LlmMessage], bool]:
    """运行四层压缩管线。返回 (处理后消息, 是否触发了 L4)。

    顺序: L3(budget) → L1(snip) → L2(micro) → L4(auto)
    """
    if config is None:
        config = CompactionConfig()

    # L3: 大结果落盘
    msgs = tool_result_budget(messages, config.tool_result_budget_bytes, config.persist_dir)

    # L1: 裁中间
    msgs = snip_compact(msgs, config.max_messages, config.keep_head)

    # L2: 旧结果占位
    msgs = micro_compact(msgs, config.keep_recent_tool_results)

    # L4: 阈值检查 → LLM 摘要
    triggered_l4 = False
    estimated = estimate_tokens(msgs)
    if estimated > config.auto_compact_threshold:
        result = compact_history(msgs, config.preserve_recent, config.persist_dir)
        msgs = result.messages
        triggered_l4 = True

    return msgs, triggered_l4


# ─── 内部工具函数 ──────────────────────────────────────────────────────────


def _adjust_boundary_for_tool_pairs(
    messages: list[LlmMessage], keep_from: int,
) -> int:
    """避免拆散 tool_use / tool_result 配对。"""
    k = keep_from
    while k > 0 and k < len(messages):
        first = messages[k]
        if not first.content or not isinstance(first.content[0], ToolResultBlock):
            break
        if k - 1 >= 0:
            prev = messages[k - 1]
            if any(isinstance(b, ToolUseBlock) for b in prev.content):
                k -= 1
                break
        k -= 1
    return k


def _build_summary(messages: list[LlmMessage]) -> str:
    """纯文本提取摘要（无 LLM 调用）。"""
    user_count = sum(1 for m in messages if m.role == "user")
    asst_count = sum(1 for m in messages if m.role == "assistant")

    tool_names: set[str] = set()
    for msg in messages:
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                tool_names.add(block.name)

    lines = [
        "<summary>",
        f"Compacted {len(messages)} messages (user={user_count}, assistant={asst_count}).",
    ]
    if tool_names:
        lines.append(f"Tools used: {', '.join(sorted(tool_names))}.")

    # 最近用户请求
    recent_user: list[str] = []
    for msg in reversed(messages):
        if msg.role == "user" and len(recent_user) < 3:
            text = _first_text(msg)
            if text:
                recent_user.append(_truncate(text, 160))
    if recent_user:
        recent_user.reverse()
        lines.append("Recent user requests:")
        for req in recent_user:
            lines.append(f"  - {req}")

    lines.append("</summary>")
    return "\n".join(lines)


def _save_transcript(messages: list[LlmMessage], persist_dir: Path | None) -> None:
    """保存完整对话 transcript 到磁盘。"""
    if persist_dir is None:
        persist_dir = Path.cwd() / ".berry" / "transcripts"
    persist_dir.mkdir(parents=True, exist_ok=True)

    import time
    ts = int(time.time())
    path = persist_dir / f"transcript_{ts}.jsonl"

    try:
        with path.open("w", encoding="utf-8") as f:
            for msg in messages:
                entry = {
                    "role": msg.role,
                    "content": [
                        {"type": type(b).__name__, "text": getattr(b, "text", getattr(b, "output", str(b)))[:500]}
                        for b in msg.content
                    ],
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("compaction_transcript_saved", path=str(path))
    except OSError as exc:
        logger.warning("compaction_transcript_failed", error=str(exc))


def _first_text(msg: LlmMessage) -> str | None:
    for block in msg.content:
        if isinstance(block, TextBlock) and block.text.strip():
            return block.text.strip()
    return None


def _truncate(text: str, max_chars: int) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= max_chars else clean[:max_chars] + "…"
