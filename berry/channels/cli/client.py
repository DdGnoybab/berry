"""CLI REPL main loop.

Read a line from stdin, hand it to a TurnRunner, render the streaming
events back to stdout. Very thin — no business logic, no system prompt
ownership. Any object that satisfies ``TurnRunner`` plugs in here unchanged.

Lifecycle:
    user runs `python -m berry.entrypoints.cli`
    → entrypoint creates user + session, builds a TurnRunner
    → loads AgentSession via persistence.load_agent_session
    → calls run_repl(turn_runner, agent_session)
    → loops on stdin until /quit, EOF, or Ctrl-C
"""

from __future__ import annotations

from berry.channels.cli.renderer import render
from berry.core.agent.session import AgentSession
from berry.core.agent.turn_runner import TurnRunner

_GREETING = (
    "berry CLI — 多轮对话模式\n"
    "输入消息后回车发送。/quit 或 Ctrl-D 退出。\n"
)


async def run_repl(
    turn_runner: TurnRunner,
    session: AgentSession,
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
            async for event in turn_runner.run_turn(session, user_text):
                render(event)
        except Exception as exc:
            # Surface the error inline rather than killing the REPL — the
            # session row stays open, the user can keep typing.
            print(f"\n[runtime error] {type(exc).__name__}: {exc}\n", flush=True)
