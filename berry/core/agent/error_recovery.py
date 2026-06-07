"""LLM 调用错误恢复 —— 退避函数 + 错误分类 + Retry-After 提取 + 重试状态机。

设计参考:
- learn-claude-code s11(教学版三种恢复模式中的「临时故障」一支)
- claw-code ``api/error.rs``(``is_retryable`` 分类思路)

本模块导出三层东西:

1. **常量**(``BASE_DELAY_MS`` / ``MAX_DELAY_MS`` / ``MAX_RETRIES`` ...)
2. **纯函数**(``retry_delay_seconds`` / ``is_retryable`` / ``extract_retry_after``)
3. **状态机类**(``RetryingStreamCall``)—— 把"流一次 LLM,失败就退避或切 fallback"
   这套循环抽成一个对象,方便 ``runtime.py`` 直接调用,也方便单测。

可重试错误集合见 ``RETRYABLE_ERRORS``;不在集合里的错误一律视作不可重试,
立刻抛给上层。
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Final, TypeAlias

from berry.core.llm.errors import (
    LlmRateLimitError,
    LlmServerError,
    LlmTimeoutError,
)
from berry.core.llm.gateway import ModelGateway
from berry.core.llm.types import LlmRequest, StreamEvent
from berry.observability.logging import get_logger

logger = get_logger(__name__)

Sleep: TypeAlias = Callable[[float], Awaitable[None]]
"""``asyncio.sleep`` 同形接口。测试可以传 fake sleep 不真等。"""

# ─── 算法常量 ─────────────────────────────────────────────────────────────

BASE_DELAY_MS: Final[int] = 500
"""指数退避的基础延迟(毫秒)。``min(BASE × 2^attempt, MAX)``。"""

MAX_DELAY_MS: Final[int] = 32_000
"""单次退避的延迟上限(毫秒)。封顶是为了避免长尾故障下用户感觉死掉。"""

MAX_RETRIES: Final[int] = 10
"""单次 LLM 流调用的最大重试次数(超过就走 fallback 链或抛)。"""

JITTER_RATIO: Final[float] = 0.25
"""抖动占基础延迟的比例(0~25%)。用来打散并发客户端的雷暴。"""


# ─── 错误分类 ─────────────────────────────────────────────────────────────

RETRYABLE_ERRORS: Final[tuple[type[Exception], ...]] = (
    LlmRateLimitError,   # 429
    LlmServerError,      # 5xx 含 529
    LlmTimeoutError,     # 超时
)
"""可进入退避通道的 LLM 错误集合。

不在此元组的错误(``LlmAuthError`` / ``LlmInvalidRequestError`` /
``LlmStreamError`` / 配置类错误等)一律不重试,立刻抛。
"""


def is_retryable(exc: BaseException) -> bool:
    """判断异常是否可重试。"""
    return isinstance(exc, RETRYABLE_ERRORS)


# ─── 退避算法 ─────────────────────────────────────────────────────────────


def retry_delay_seconds(
    attempt: int,
    retry_after_seconds: float | None = None,
) -> float:
    """计算下一次重试前应该等多久(秒)。

    优先级:服务器 ``Retry-After`` > 指数退避公式。

    Args:
        attempt: 已经失败的次数(从 0 开始)。第一次失败传 0。
        retry_after_seconds: 服务器 ``Retry-After`` header 解析值;无则 None。

    Returns:
        浮点秒数。永远 ≥ 0。

    公式:
        ``delay = min(BASE × 2^attempt, MAX) + random(0, base × JITTER)``

    示例(单位 ms,不含抖动):

        attempt=0  →  500
        attempt=1  → 1000
        attempt=4  → 8000
        attempt=6  → 32000(被 MAX 卡住)
        attempt=10 → 32000(同上)
    """
    if retry_after_seconds is not None and retry_after_seconds > 0:
        return retry_after_seconds

    base_ms: int = min(BASE_DELAY_MS * (2 ** attempt), MAX_DELAY_MS)
    jitter_ms: float = random.uniform(0, base_ms * JITTER_RATIO)
    delay_seconds: float = (base_ms + jitter_ms) / 1000.0
    return delay_seconds


# ─── Retry-After 提取 ─────────────────────────────────────────────────────


def extract_retry_after(exc: BaseException) -> float | None:
    """从 SDK 异常里尝试挖出 ``Retry-After`` header 的秒数。

    Anthropic / OpenAI Python SDK 的异常都把原始 ``httpx.Response`` 挂在
    ``response`` 属性上;header 名称大小写不敏感(httpx 已经处理)。

    拿不到 / 解析失败一律返回 ``None``,调用方退化到指数退避公式。

    Returns:
        秒数(float),或 None。永远不会抛异常。
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    # SDK 异常的 headers 形状不可预知:httpx.Headers / dict / 极少数实现
    # 可能挂个 str。任何属性访问失败都视为「拿不到」,退回指数退避。
    try:
        # httpx.Headers 是 case-insensitive;普通 dict 不是,两个名都试
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    if not raw:
        return None

    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        # Retry-After 也可以是 HTTP-date 格式;MVP 不解析,直接放弃
        return None

    if seconds < 0:
        return None
    return seconds


# ─── 重试状态机 ───────────────────────────────────────────────────────────


class RetryingStreamCall:
    """把"流一次 LLM,失败就退避或切 fallback"这套循环包成一个对象。

    用法(``runtime.py`` 主循环里):

        call = RetryingStreamCall(
            gateway=gateway, request=request,
            initial_model=current_model, fallback_chain=fallback_chain,
            sleep=asyncio.sleep, max_retries=MAX_RETRIES,
        )
        async for stream_ev in call.run():
            # 转发 / 累加 stream_ev
        # call.model_used 是真正成功这一次用的 model id
        # call.attempts_used 是发起的总尝试次数(重试 + 切 fallback 内部都计)

    错误处理规则:

    - **可重试**(``RETRYABLE_ERRORS``): 退避;到上限切 fallback 链下一个;
      链耗尽抛
    - **不可重试**: 立刻抛
    - **流已 yield 过事件后才出错**: 不重试,直接抛(避免对 channel
      产生拼接文本)

    每个事件的打点(structlog)字段:
    ``agent_retry_backoff`` / ``agent_retry_aborted_stream_started`` /
    ``agent_fallback_switched`` / ``agent_fallback_chain_exhausted``。

    每次构造一个新实例只用一次 —— 状态机在 ``run()`` 退出后不要复用。
    """

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        request: LlmRequest,
        initial_model: str,
        fallback_chain: list[str],
        sleep: Sleep | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._gateway = gateway
        self._request = request
        self._fallback_chain = list(fallback_chain)  # 拷贝,避免污染调用方
        self._sleep: Sleep = sleep if sleep is not None else asyncio.sleep
        self._max_retries = max_retries

        # mutated during run()
        self._current_model = initial_model
        self._attempts_used = 0  # 跨 model 累计

    @property
    def model_used(self) -> str:
        """run() 退出时,实际跑通的那次用的 model id(若 run 抛了,这里是
        最后一次尝试时的 model id,可用于打点)。"""
        return self._current_model

    @property
    def attempts_used(self) -> int:
        """从开始到 run() 退出共发起的尝试次数(成功的那次也计在内)。"""
        return self._attempts_used

    @property
    def remaining_chain(self) -> list[str]:
        """run() 退出时,fallback 链里剩下还没用到的 model id 序列。

        如果 fallback 切换发生过,前 N 个 entry 已经被消耗;调用方在同一
        turn 后续 inner loop 应该用这个剩余链,不要再从头尝试已经挂掉的模型。
        """
        return list(self._fallback_chain)

    async def run(self) -> AsyncIterator[StreamEvent]:
        """跑流;按规则重试 / 切 fallback。yield 出 stream events 给调用方。"""
        attempt_on_current_model = 0
        while True:
            message_started = False
            self._attempts_used += 1
            try:
                async for stream_ev in self._gateway.stream(
                    self._current_model, self._request
                ):
                    message_started = True
                    yield stream_ev
                return  # stream 正常结束
            except RETRYABLE_ERRORS as exc:
                if message_started:
                    logger.warning(
                        "agent_retry_aborted_stream_started",
                        error_type=type(exc).__name__,
                        model=self._current_model,
                        exc_info=True,
                    )
                    raise

                if attempt_on_current_model < self._max_retries:
                    delay = retry_delay_seconds(
                        attempt_on_current_model, extract_retry_after(exc)
                    )
                    logger.info(
                        "agent_retry_backoff",
                        attempt=attempt_on_current_model,
                        delay_s=delay,
                        error_type=type(exc).__name__,
                        model=self._current_model,
                    )
                    await self._sleep(delay)
                    attempt_on_current_model += 1
                    continue

                # Retries exhausted — try fallback chain
                if self._fallback_chain:
                    next_model = self._fallback_chain.pop(0)
                    # TODO(V1): emit prometheus counter
                    # agent_fallback_switched_total{from,to,reason}
                    logger.warning(
                        "agent_fallback_switched",
                        from_model=self._current_model,
                        to_model=next_model,
                        reason=type(exc).__name__,
                        attempt_count=attempt_on_current_model,
                    )
                    self._current_model = next_model
                    attempt_on_current_model = 0
                    continue

                logger.error(
                    "agent_fallback_chain_exhausted",
                    model=self._current_model,
                    error_type=type(exc).__name__,
                    exc_info=True,
                )
                raise


