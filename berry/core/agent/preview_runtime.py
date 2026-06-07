"""PreviewRuntime — a sandboxed ConversationRuntime for plan preview.

Used by the new-project flow's "Step 2 preview". The user has typed a
topic + goal; we want the LLM to research it and propose a learning
plan, but we MUST NOT let it write any files (the project hasn't been
committed yet — files would land in the wrong place / leak between
users).

Design (ADR-0010 follow-up):
  - Same ``ConversationRuntime`` class, just a smaller ``ToolRegistry``.
  - Only ``WebSearchTool`` + ``WebFetchTool`` registered.
  - No file-write tools, no skill tool, no todo, no ask_user_question.
  - Result: LLM physically cannot mutate disk; even if a buggy prompt
    asks it to, the tool isn't there to call.

Why physical isolation rather than prompt-level "please don't write":
  - Prompt-level ~95% reliable; disk corruption from the 5% failure
    case is unacceptable (wrong cwd → polluted user data).
  - Physical isolation: 100% reliable, zero ambiguity, easier to audit.

Output contract:
  System prompt instructs the LLM to return the final assistant message
  as a single fenced JSON block matching ``PlanResult`` (see
  ``berry.protocol.methods_core``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from berry.config import settings
from berry.core.agent.approval import ApprovalChannel, ApprovalPolicy
from berry.core.agent.runtime import ConversationRuntime
from berry.core.agent.tool_registry import ToolRegistry
from berry.core.db.session import async_session_factory
from berry.core.llm.adapters.anthropic_messages import AnthropicMessagesAdapter
from berry.core.llm.adapters.base import Adapter
from berry.core.llm.adapters.openai_completions import OpenAICompletionsAdapter
from berry.core.llm.enums import KnownApi
from berry.core.llm.gateway import ModelGateway
from berry.core.llm.registry import ModelRegistry
from berry.core.tools.base import ToolContext
from berry.core.tools.web.fetch import WebFetchTool
from berry.core.tools.web.registry import SearchProviderRegistry
from berry.core.tools.web.search import WebSearchTool
from berry.security.permissions import LayeredPolicy


# ─── A trivial approval channel that auto-allows
# (preview never asks for sensitive ops; LayeredPolicy will only
# REQUIRE_APPROVAL on actually-dangerous tools, which we don't even register)


class _AutoAllowApproval:
    """Approval channel that auto-allows — fine here because the only
    tools registered are read-only web ops."""

    async def ask(  # noqa: D401
        self,
        tool_name: str,
        args: dict,
        ctx: ToolContext,
        reason: str | None = None,
    ) -> bool:
        return True


_PREVIEW_SYSTEM_PROMPT = """\
You are generating a LEARNING PLAN PREVIEW for a programming-interview-focused
learning assistant. The user has typed a topic and goal. Your job:

1. Use `web_search` 1-3 times to find high-frequency interview questions /
   the canonical learning structure for this topic. Use `web_fetch` only if
   you need to expand a specific authoritative source.
2. Synthesize into a learning plan: 5-8 modules, 3-6 atoms each. Module
   names match real-world structure of the topic. Atom names are concrete
   and testable (not vague like "Misc").
3. Emit the FINAL assistant message as a single fenced JSON block exactly
   matching this shape:

   ```json
   {
     "modules": [
       {
         "id": "01-overview",
         "name": "概述与场景",
         "atoms": [
           {"id": "a1", "name": "Redis 是什么、解决了什么问题"},
           {"id": "a2", "name": "vs Memcached 的关键差异"}
         ]
       }
     ],
     "interview_md": "# Redis 高频面试题\\n\\n## 01 概述\\n- ...\\n"
   }
   ```

# CRITICAL OUTPUT CONTRACT — read carefully

Your FINAL assistant message in this turn MUST be a single fenced JSON
block (`​`​`​`json ... `​`​`​`) and NOTHING ELSE.

Failure modes you must avoid:
  - "Let me search for more...". → No. After WebSearch tools, your next
    text output MUST be the JSON block.
  - "Now I have enough info to build the plan. Here it is:" → No prose
    preamble. Start the message with `​`​`​`json on its own line.
  - "I added X module per your feedback" → No commentary. Just the JSON.
  - Plain text describing the modules → INVALID. Must be JSON.

This applies on EVERY call, including adjustment / re-generation calls
where the user gave feedback. Re-emit the WHOLE updated plan as JSON,
not a description of changes.

# Other hard rules

  - DO NOT write files. You don't have file tools — that's intentional.
    The system will create files later, after the user confirms.
  - DO NOT call any tool you weren't given.
  - Module IDs: use ``NN-slug`` (e.g. ``01-overview``, ``02-data-structures``).
    Atom IDs: ``a1`` / ``a2`` / etc.
  - ``interview_md`` should be a tight, deduped question pool covering all
    modules — markdown bullets grouped by module heading.
  - Goal-aware:
      * "interview" → focus on common interview questions; skip esoteric internals
      * "deep" → include design tradeoffs, source-level structure, history
      * "easy" → surface-level only; use analogies; skip implementation details
"""


class _NoOpHookRunner:
    """Hook runner stub — preview doesn't need user-defined hooks."""

    async def run(  # noqa: D401
        self, tool_name: str, args: dict, ctx: ToolContext
    ):
        from berry.core.agent.hook import HookVerdict, HookVerdictAction

        return HookVerdict(action=HookVerdictAction.DEFER, reason=None)


def build_preview_runtime() -> tuple[ConversationRuntime, str]:
    """Construct a sandboxed ConversationRuntime for plan preview.

    Returns ``(runtime, system_prompt)``. Runtime has only WebSearch +
    WebFetch tools registered.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    models_path = repo_root / "config" / "models.yaml"
    model_registry = ModelRegistry(models_path)
    model_registry.load()

    adapters: dict[str, Adapter] = {
        KnownApi.OPENAI_COMPLETIONS.value: OpenAICompletionsAdapter(),
        KnownApi.ANTHROPIC_MESSAGES.value: AnthropicMessagesAdapter(),
    }
    gateway = ModelGateway(model_registry, adapters)

    search_path = repo_root / "config" / "search.yaml"
    search_registry = SearchProviderRegistry(search_path)
    search_registry.load()

    # ★ THE WHOLE POINT: no write tools. No skill/todo/ask_user_question
    # either — preview doesn't interact with the user, it's a one-shot.
    tool_registry = ToolRegistry(
        [
            WebSearchTool(search_registry),
            WebFetchTool(),
        ]
    )

    policy: ApprovalPolicy = LayeredPolicy()
    approval: ApprovalChannel = _AutoAllowApproval()  # type: ignore[assignment]

    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=tool_registry,
        approval_policy=policy,
        approval_channel=approval,
        db_session_factory=async_session_factory,
        model_id="main",
        max_inner_loops=8,
        # No memory loading for preview — preview is stateless.
        # cwd_resolver omitted: irrelevant since no file tools exist.
    )

    return runtime, _PREVIEW_SYSTEM_PROMPT
