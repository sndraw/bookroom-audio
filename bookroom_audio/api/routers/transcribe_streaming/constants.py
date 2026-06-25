"""
流式语音识别相关常量定义
所有字符串、数值常量集中管理，避免散落在代码中
"""

from enum import Enum


# ==================== 引擎相关常量 ====================

class StreamingASREngine(str, Enum):
    """流式 ASR 引擎类型枚举"""
    FUNASR_SERVER = "funasr-server"
    FUNASR_LOCAL = "funasr-local"
    SENSE_VOICE_LOCAL = "sensevoice-local"


class FunASRMode(str, Enum):
    """FunASR 识别模式枚举"""
    ONLINE = "online"
    OFFLINE = "offline"
    TWO_PASS = "2pass"


class AudioFormat(str, Enum):
    """客户端音频输入格式枚举"""
    PCM = "pcm"
    WAV = "wav"
    MP3 = "mp3"
    OPUS = "opus"
    SPEEX = "speex"
    AAC = "aac"
    AMR = "amr"


# ==================== WebSocket 协议相关常量 ====================

class ClientMessageType(str, Enum):
    """客户端 → 服务端 消息类型"""
    START = "start"
    AUDIO = "audio"
    STOP = "stop"


class ServerMessageType(str, Enum):
    """服务端 → 客户端 消息类型"""
    STARTED = "started"
    PARTIAL = "partial"
    FINAL = "final"
    ERROR = "error"
    CLOSED = "closed"


class ErrorCode(str, Enum):
    """错误码枚举"""
    AUTH_FAILED = "auth_failed"
    INVALID_CONFIG = "invalid_config"
    UNSUPPORTED_ENGINE = "unsupported_engine"
    UNSUPPORTED_FORMAT = "unsupported_format"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    AUDIO_DECODE_FAILED = "audio_decode_failed"
    INTERNAL_ERROR = "internal_error"
    SESSION_NOT_FOUND = "session_not_found"


# ==================== 音频处理常量 ====================

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
DEFAULT_CHANNELS = 1  # mono
DEFAULT_CHUNK_MS = 600  # FunASR 推荐 600ms
DEFAULT_VAD_SILENCE_MS = 1300  # VAD 静音断句阈值

# PCM 每毫秒字节数（16kHz / 16bit / mono）
PCM_BYTES_PER_MS = DEFAULT_SAMPLE_RATE * DEFAULT_SAMPLE_WIDTH * DEFAULT_CHANNELS // 1000

# FunASR 默认 chunk_size 配置 [左回溯, 当前, 右前瞻]
# [5, 10, 5] = 600ms 音频块，300ms 前瞻
DEFAULT_CHUNK_SIZE = [5, 10, 5]
DEFAULT_ENCODER_CHUNK_LOOK_BACK = 4
DEFAULT_DECODER_CHUNK_LOOK_BACK = 1

# WebSocket 接收缓冲区大小
WS_RECEIVE_BUFFER_BYTES = 1024 * 1024  # 1MB
WS_SEND_QUEUE_MAXSIZE = 100
WS_IDLE_TIMEOUT_SECONDS = 300  # 5分钟无活动断开

# 会话清理间隔
SESSION_CLEANUP_INTERVAL_SECONDS = 60


# ==================== 默认模型名称 ====================

class DefaultModel(str, Enum):
    """默认模型名称枚举

    使用官方推荐的简写别名（funasr 内部自动映射到 ModelScope 仓库并按需下载）。
    官方文档参考：https://modelscope.github.io/FunASR/tutorial.html

    注意：
    - 流式 ASR（paraformer-zh-streaming）按官方示例单独加载，
      不需要同时加载 vad_model/punc_model（chunk_size 自身控制流式）
    - SenseVoice 使用完整 ModelScope ID "iic/SenseVoiceSmall"
    """
    FUNASR_STREAMING = "paraformer-zh-streaming"
    FUNASR_VAD = "fsmn-vad"
    FUNASR_PUNC = "ct-punc"
    SENSE_VOICE = "iic/SenseVoiceSmall"


# ==================== FunASR 服务端消息字段 ====================

class FunASRMessageField(str, Enum):
    """FunASR 协议字段名"""
    MODE = "mode"
    CHUNK_SIZE = "chunk_size"
    WAV_NAME = "wav_name"
    IS_SPEAKING = "is_speaking"
    HOTWORDS = "hotwords"
    ITN = "itn"
    AUDIO_FS = "audio_fs"
    TEXT = "text"
    IS_FINAL = "is_final"
    TIMESTAMP = "timestamp"
    STAMP_SENTS = "stamp_sents"


class FunASRResponseMode(str, Enum):
    """FunASR 服务端响应的 mode 值"""
    TWO_PASS_ONLINE = "2pass-online"
    TWO_PASS_OFFLINE = "2pass-offline"
    ONLINE = "online"
    OFFLINE = "offline"
