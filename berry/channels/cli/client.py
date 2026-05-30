"""CLI REPL main loop.

Read a line from stdin, hand it to ConversationRuntime, render the streaming
events back to stdout. Very thin — no business logic. Works against any
ConversationRuntime instance (Round 2 wires up dummy tools; Round 4 will
swap in GoalTutor's tool set without touching this file).

Lifecycle:
    user runs `python -m berry.entrypoints.cli`
    → entrypoint creates a fresh user + session via SessionRepo.create_new
    → loads AgentSession via persistence.load_agent_session
    → calls run_repl(runtime, agent_session, system_prompt)
    → loops on stdin until /quit, EOF, or Ctrl-C
"""

from __future__ import annotations

from berry.channels.cli.renderer import render
from berry.core.agent.runtime import ConversationRuntime
from berry.core.agent.session import AgentSession

_GREETING = (
    "berry CLI — 多轮对话模式\n"
    "输入消息后回车发送。/quit 或 Ctrl-D 退出。\n"
)


async def run_repl(
    runtime: ConversationRuntime,
    session: AgentSession,
    system_prompt: str,
) -> None:
    """Drive the REPL until the user exits."""
    print(_GREETING, end="", flush=True)
    while True:
        try:
            user_text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return

        if not user_text:
            continue
        if user_text in {"/quit", "/q", "/exit"}:
            print("bye")
            return

        try:
            async for event in runtime.run_turn(
                session, user_text, system_prompt=system_prompt
            ):
                render(event)
        except Exception as exc:
            # Surface the error inline rather than killing the REPL — the
            # session row stays open, the user can keep typing.
            print(f"\n[runtime error] {type(exc).__name__}: {exc}\n", flush=True)
