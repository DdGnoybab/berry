"""LLM Gateway smoke 测试。

用法:
    uv run python scripts/llm_smoke.py                      # 非流式
    uv run python scripts/llm_smoke.py --stream             # 流式
    uv run python scripts/llm_smoke.py --model classify     # 换模型 / 别名
    uv run python scripts/llm_smoke.py --prompt "你是谁?"

验证目标:
- ModelRegistry 能加载 yaml
- ModelGateway 能路由到 OpenAICompletionsAdapter
- 真实调到 DeepSeek 拿到回复
- 流式 token 实时输出
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 让脚本直接 python scripts/xx.py 也能 import berry
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from berry.core.llm.adapters.anthropic_messages import AnthropicMessagesAdapter  # noqa: E402
from berry.core.llm.adapters.openai_completions import OpenAICompletionsAdapter  # noqa: E402
from berry.core.llm.enums import KnownApi  # noqa: E402
from berry.core.llm.gateway import ModelGateway  # noqa: E402
from berry.core.llm.registry import ModelRegistry  # noqa: E402
from berry.core.llm.types import (  # noqa: E402
    LlmMessage,
    LlmRequest,
    LlmTool,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


CONFIG_PATH = ROOT / "config" / "models.yaml"


def build_gateway() -> ModelGateway:
    """加载配置 + 注册所有 adapter。"""
    registry = ModelRegistry(CONFIG_PATH)
    registry.load()
    adapters = {
        KnownApi.OPENAI_COMPLETIONS.value: OpenAICompletionsAdapter(),
        KnownApi.ANTHROPIC_MESSAGES.value: AnthropicMessagesAdapter(),
    }
    return ModelGateway(registry, adapters)


async def run_invoke(gw: ModelGateway, model: str, prompt: str) -> None:
    print(f"\n=== invoke (model={model}) ===")
    req = LlmRequest(
        model=model,
        messages=[LlmMessage.user(prompt)],
        max_tokens=256,
    )
    resp = await gw.invoke(model, req)
    print(f"id        : {resp.id}")
    print(f"model     : {resp.model}")
    print(f"stop      : {resp.stop_reason}")
    print(f"usage     : in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
    print(f"text      : {resp.content[0].text}")  # type: ignore[union-attr]


async def run_stream(gw: ModelGateway, model: str, prompt: str) -> None:
    print(f"\n=== stream (model={model}) ===")
    req = LlmRequest(
        model=model,
        messages=[LlmMessage.user(prompt)],
        max_tokens=256,
        stream=True,
    )
    print("text     : ", end="", flush=True)
    async for ev in gw.stream(model, req):
        if ev.type == "text_delta":
            print(ev.text, end="", flush=True)
        elif ev.type == "message_start":
            pass
        elif ev.type == "message_stop":
            print(f"\nstop     : {ev.stop_reason}")
        elif ev.type == "usage":
            print(f"usage    : in={ev.usage.input_tokens} out={ev.usage.output_tokens}")
        elif ev.type == "error":
            print(f"\nERROR    : {ev.error_type}: {ev.message}")


async def run_tools_demo(gw: ModelGateway, model: str) -> None:
    """演示 tool_use 来回:
    1. 给 LLM 一个 get_weather 工具
    2. 让它对「北京天气怎么样?」做工具调用
    3. 我们模拟工具结果,回传
    4. 让它根据结果给最终答案
    """
    print(f"\n=== tools (model={model}) ===")

    weather_tool = LlmTool(
        name="get_weather",
        description="查询某个城市的当前天气",
        input_schema={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名,如『北京』"}
            },
            "required": ["city"],
        },
    )

    # ─── Round 1:让 LLM 决定调用工具 ───
    req1 = LlmRequest(
        model=model,
        messages=[LlmMessage.user("帮我查下北京今天的天气怎么样?")],
        tools=[weather_tool],
        max_tokens=512,
    )
    resp1 = await gw.invoke(model, req1)
    print(f"Round 1 stop : {resp1.stop_reason}")
    for b in resp1.content:
        if isinstance(b, TextBlock):
            print(f"   text     : {b.text}")
        elif isinstance(b, ToolUseBlock):
            print(f"   tool_use : {b.name}({b.input}) [id={b.id}]")

    # 找到 tool_use 块
    tool_calls = [b for b in resp1.content if isinstance(b, ToolUseBlock)]
    if not tool_calls:
        print("   ⚠️  LLM 没调用工具,跳过 Round 2")
        return

    tc = tool_calls[0]

    # ─── Round 2:回传工具结果 ───
    fake_weather = "北京今天晴,28°C,东北风 3 级。"
    print(f"\n   [模拟工具执行] {fake_weather}")

    req2 = LlmRequest(
        model=model,
        messages=[
            LlmMessage.user("帮我查下北京今天的天气怎么样?"),
            LlmMessage(role="assistant", content=resp1.content),
            LlmMessage(
                role="user",
                content=[ToolResultBlock(tool_use_id=tc.id, output=fake_weather)],
            ),
        ],
        tools=[weather_tool],
        max_tokens=512,
    )
    resp2 = await gw.invoke(model, req2)
    print(f"\nRound 2 stop : {resp2.stop_reason}")
    for b in resp2.content:
        if isinstance(b, TextBlock):
            print(f"   text     : {b.text}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="classify", help="logical id or alias")
    parser.add_argument("--prompt", default="用一句话介绍 Python", help="user prompt")
    parser.add_argument("--stream", action="store_true", help="stream mode")
    parser.add_argument("--tools", action="store_true", help="tools demo")
    args = parser.parse_args()

    gw = build_gateway()

    if args.tools:
        await run_tools_demo(gw, args.model)
    elif args.stream:
        await run_stream(gw, args.model, args.prompt)
    else:
        await run_invoke(gw, args.model, args.prompt)


if __name__ == "__main__":
    # 把 .env 写入 os.environ(让 yaml 里 ${DEEPSEEK_KEY} 能从 env 读到)
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    asyncio.run(main())
