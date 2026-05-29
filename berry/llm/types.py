"""中立类型:LLM 请求 / 响应 / 流式事件。

设计原则:
- 不依赖任何 SDK 类型(Adapter 内部转换)
- 内容块用 discriminated union(`type` 字段)
- 语义靠拢 Anthropic Messages,转 OpenAI 是降级、反向是升级

Batch 1 只含纯文本块 + 流式事件;tool_use / thinking 在 Batch 2 加。
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from berry.llm.enums import StopReason

# ─── 角色 ───
Role = Literal["system", "user", "assistant", "tool"]


# ─── 内容块 ───
class TextBlock(BaseModel):
    """纯文本内容块。"""

    type: Literal["text"] = "text"
    text: str


class ThinkingBlock(BaseModel):
    """思考块(Anthropic extended thinking;OpenAI 不支持时丢弃)。"""

    type: Literal["thinking"] = "thinking"
    text: str


class ToolUseBlock(BaseModel):
    """LLM 想要调用某工具(出现在 assistant 消息里)。"""

    type: Literal["tool_use"] = "tool_use"
    id: str                            # tool_use_id,跟 ToolResultBlock 配对
    name: str
    input: dict[str, Any]


class ToolResultBlock(BaseModel):
    """工具执行结果(放在 user 消息里回传)。"""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    output: str                        # MVP:只支持文本结果(够用)
    is_error: bool = False


ContentBlock = Annotated[
    TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]


# ─── 消息 ───
class LlmMessage(BaseModel):
    """一条对话消息。"""

    role: Role
    content: list[ContentBlock]

    @classmethod
    def user(cls, text: str) -> "LlmMessage":
        """便捷构造:user 文本消息。"""
        return cls(role="user", content=[TextBlock(text=text)])

    @classmethod
    def assistant(cls, text: str) -> "LlmMessage":
        """便捷构造:assistant 文本消息。"""
        return cls(role="assistant", content=[TextBlock(text=text)])


# ─── 工具定义(Batch 2 实际使用)───
class LlmTool(BaseModel):
    """工具定义。Batch 1 不实际调用,但类型留好。"""

    name: str
    description: str
    input_schema: dict[str, Any]


# ─── Usage ───
class Usage(BaseModel):
    """LLM 调用的 token 用量。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


# ─── 请求 ───
class LlmRequest(BaseModel):
    """中立的 LLM 调用请求。

    `model` 是 logical id(catalog 里的 id),不是厂商 model name。
    """

    model: str
    messages: list[LlmMessage]
    system: str | None = None
    tools: list[LlmTool] | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


# ─── 响应(非流式)───
class LlmResponse(BaseModel):
    """中立的 LLM 调用响应。"""

    id: str                              # provider 返回的请求 id
    model: str                           # logical id(不是厂商 model name)
    content: list[ContentBlock]
    stop_reason: StopReason
    usage: Usage
    raw: dict[str, Any] | None = None    # 原始响应,debug 用,生产可关


# ─── 流式事件 ───
class MessageStart(BaseModel):
    """流开始,带初始元信息。"""

    type: Literal["message_start"] = "message_start"
    id: str
    model: str


class TextDelta(BaseModel):
    """文本增量。"""

    type: Literal["text_delta"] = "text_delta"
    text: str


class ThinkingDelta(BaseModel):
    """思考增量(Anthropic extended thinking)。"""

    type: Literal["thinking_delta"] = "thinking_delta"
    text: str


class ToolCallStart(BaseModel):
    """开始调用工具(流式)。"""

    type: Literal["tool_call_start"] = "tool_call_start"
    id: str                            # tool_use_id
    name: str


class ToolCallDelta(BaseModel):
    """工具调用参数增量(input JSON 的字符串增量)。"""

    type: Literal["tool_call_delta"] = "tool_call_delta"
    id: str                            # tool_use_id
    input_json_delta: str


class MessageStop(BaseModel):
    """流正常结束。"""

    type: Literal["message_stop"] = "message_stop"
    stop_reason: StopReason


class UsageEvent(BaseModel):
    """用量信息(通常在流末尾发一次)。"""

    type: Literal["usage"] = "usage"
    usage: Usage


class StreamError(BaseModel):
    """流中错误。"""

    type: Literal["error"] = "error"
    message: str
    error_type: str


StreamEvent = Annotated[
    MessageStart
    | TextDelta
    | ThinkingDelta
    | ToolCallStart
    | ToolCallDelta
    | MessageStop
    | UsageEvent
    | StreamError,
    Field(discriminator="type"),
]
