"""
流式语音识别 WebSocket 消息 Pydantic 模型
定义客户端与服务端交互的数据结构
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from bookroom_audio.api.routers.transcribe_streaming.constants import (
    AudioFormat,
    ClientMessageType,
    ServerMessageType,
    ErrorCode,
    StreamingASREngine,
)


# ==================== 客户端消息模型 ====================

class StreamingSessionConfig(BaseModel):
    """流式识别会话配置"""
    engine: Optional[StreamingASREngine] = Field(
        default=None,
        description="流式 ASR 引擎，未指定则使用配置默认值"
    )
    language: str = Field(
        default="zh",
        description="语言代码，如 zh/en/ja/ko/auto"
    )
    audio_format: AudioFormat = Field(
        default=AudioFormat.PCM,
        description="音频输入格式"
    )
    sample_rate: int = Field(
        default=16000,
        description="音频采样率"
    )
    enable_punctuation: bool = Field(
        default=True,
        description="是否启用标点恢复"
    )
    enable_vad: bool = Field(
        default=True,
        description="是否启用服务端 VAD 自动断句"
    )
    enable_itn: bool = Field(
        default=True,
        description="是否启用逆文本归一化（数字/日期等）"
    )
    enable_speaker_diarization: bool = Field(
        default=False,
        description="是否启用说话人分离"
    )
    enable_emotion: bool = Field(
        default=False,
        description="是否启用情感识别（仅 SenseVoice 支持）"
    )
    hotwords: Optional[Dict[str, int]] = Field(
        default=None,
        description="热词权重映射，如 {\"阿里巴巴\": 20}"
    )
    chunk_size: Optional[List[int]] = Field(
        default=None,
        description="流式分块配置 [左回溯, 当前, 右前瞻]，默认 [5,10,5]"
    )
    max_sentence_silence_ms: int = Field(
        default=1300,
        description="VAD 静音断句阈值（毫秒）",
        ge=200,
        le=6000
    )

    class Config:
        use_enum_values = True


class StartMessage(BaseModel):
    """客户端开始会话消息"""
    type: ClientMessageType = Field(default=ClientMessageType.START)
    config: StreamingSessionConfig = Field(default_factory=StreamingSessionConfig)


class StopMessage(BaseModel):
    """客户端停止会话消息"""
    type: ClientMessageType = Field(default=ClientMessageType.STOP)


# ==================== 服务端消息模型 ====================

class StartedMessage(BaseModel):
    """会话已建立消息"""
    type: ServerMessageType = Field(default=ServerMessageType.STARTED)
    session_id: str = Field(description="会话唯一 ID")
    engine: str = Field(description="实际使用的引擎")
    config: Dict[str, Any] = Field(description="生效的配置")

    class Config:
        use_enum_values = True


class WordInfo(BaseModel):
    """词级时间戳信息"""
    text: str = Field(description="词文本")
    start_ms: int = Field(description="开始时间（毫秒）")
    end_ms: int = Field(description="结束时间（毫秒）")
    punctuation: str = Field(default="", description="标点符号")


class PartialMessage(BaseModel):
    """中间识别结果（实时更新）"""
    type: ServerMessageType = Field(default=ServerMessageType.PARTIAL)
    session_id: str = Field(description="会话 ID")
    text: str = Field(description="中间识别文本（可能继续变化）")
    is_final: bool = Field(default=False, description="是否为该句最终结果")
    sentence_id: int = Field(default=0, description="句子序号")
    timestamp_ms: int = Field(default=0, description="已识别音频时长（毫秒）")

    class Config:
        use_enum_values = True


class FinalMessage(BaseModel):
    """VAD 断句后的最终结果"""
    type: ServerMessageType = Field(default=ServerMessageType.FINAL)
    session_id: str = Field(description="会话 ID")
    text: str = Field(description="最终识别文本（含标点）")
    is_final: bool = Field(default=True)
    sentence_id: int = Field(description="句子序号")
    start_ms: int = Field(description="句子开始时间（毫秒）")
    end_ms: int = Field(description="句子结束时间（毫秒）")
    speaker: Optional[int] = Field(default=None, description="说话人 ID")
    emotion: Optional[str] = Field(default=None, description="情感标签")
    words: List[WordInfo] = Field(default_factory=list, description="词级时间戳")

    class Config:
        use_enum_values = True


class ErrorMessage(BaseModel):
    """错误消息"""
    type: ServerMessageType = Field(default=ServerMessageType.ERROR)
    session_id: Optional[str] = Field(default=None, description="会话 ID")
    code: ErrorCode = Field(description="错误码")
    message: str = Field(description="错误详情")

    class Config:
        use_enum_values = True


class ClosedMessage(BaseModel):
    """会话关闭消息"""
    type: ServerMessageType = Field(default=ServerMessageType.CLOSED)
    session_id: str = Field(description="会话 ID")
    reason: str = Field(default="normal", description="关闭原因")

    class Config:
        use_enum_values = True


# ==================== 引擎结果模型 ====================

class ASRResult(BaseModel):
    """引擎统一识别结果"""
    text: str = Field(description="识别文本")
    is_final: bool = Field(default=False, description="是否为句子最终结果")
    sentence_id: int = Field(default=0, description="句子序号")
    start_ms: int = Field(default=0, description="开始时间")
    end_ms: int = Field(default=0, description="结束时间")
    speaker: Optional[int] = Field(default=None, description="说话人 ID")
    emotion: Optional[str] = Field(default=None, description="情感标签")
    words: List[WordInfo] = Field(default_factory=list, description="词级时间戳")
