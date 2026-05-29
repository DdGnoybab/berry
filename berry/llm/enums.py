"""LLM 相关枚举。"""

from enum import StrEnum


class KnownApi(StrEnum):
    """已知的协议类型。Adapter 按这个分。

    Batch 1 只实现 OPENAI_COMPLETIONS,其他在后续 batch 加。
    """

    ANTHROPIC_MESSAGES = "anthropic-messages"
    OPENAI_COMPLETIONS = "openai-completions"
    OPENAI_RESPONSES = "openai-responses"
    OPENAI_AUDIO_SPEECH = "openai-audio-speech"
    OPENAI_AUDIO_TRANSCRIBE = "openai-audio-transcribe"
    OPENAI_IMAGES = "openai-images"
    GOOGLE_GENERATIVE_AI = "google-generative-ai"


class ModelKind(StrEnum):
    """模型模态。catalog 用这个 tag 分类。"""

    TEXT = "text"
    IMAGE = "image"
    TTS = "tts"
    ASR = "asr"
    VIDEO = "video"
    MUSIC = "music"


class StopReason(StrEnum):
    """LLM 停止原因。"""

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    ERROR = "error"
