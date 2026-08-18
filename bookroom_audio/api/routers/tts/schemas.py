"""
TTS schemas - Pydantic models for TTS requests and responses.
"""

from typing import Any, Optional
from pydantic import BaseModel, Field


class TTSRequest(BaseModel):
    """
    TTS 请求参数模型。
    
    Attributes:
        text: 需要转换的文本内容。
        voice_id: 可选的声音 ID 或名称（兼容旧版）。
        voice: 声音名称，支持中文和英文（新版）。
        rate: 语速，支持整数(WPM)或百分比格式。
        volume: 音量，支持0.0-1.0浮点数或百分比格式。
        sample_rate: 音频采样率 (Hz)，可选，默认为 16000。
        engine: TTS引擎选择，可选值: chattts, cosyvoice, cosyvoice3, kokoro, edge-tts, pyttsx3, auto。
        emotion: 情感类型（仅ChatTTS支持），可选: happy, sad, angry, neutral。
        reference_audio: （仅 cosyvoice3）参考音频 base64（WAV，3~10s 说话人样本），必填。
        reference_text: （仅 cosyvoice3）参考音频对应文本，可选；默认官方 system prompt。
    """

    text: str = Field(..., description="Text content to convert to speech")
    voice_id: Optional[str] = Field(None, description="Voice ID or name (legacy parameter, use voice instead)")
    voice: Optional[str] = Field(None, description="Voice name. For ChatTTS: use voice index (0-10). For CosyVoice 2: 中文女/中文男/英文女/英文男 等预置音色. For Edge TTS: zh-CN-XiaoxiaoNeural, zh-CN-YunxiNeural, etc.")
    rate: Any = Field(200, description="Speech rate. Integer (WPM) or percentage format (e.g., +10%, -20%)")
    volume: Any = Field(1.0, description="Volume level. Float between 0.0-1.0 or percentage format (e.g., 50%, 100%)")
    sample_rate: int = Field(16000, description="Audio sample rate in Hz. Common values: 16000, 22050, 44100")
    engine: str = Field("auto", description="TTS engine. Options: chattts, cosyvoice, cosyvoice3, kokoro, edge-tts, pyttsx3, auto. Auto selects based on text language")
    emotion: str = Field("neutral", description="Emotion type (ChatTTS only). Options: happy, sad, angry, neutral")
    reference_audio: Optional[str] = Field(None, description="(cosyvoice3 only) Reference audio as base64 WAV (3-10s speaker sample), required for zero-shot cloning")
    reference_text: Optional[str] = Field(None, description="(cosyvoice3 only) Text of the reference audio (prompt_text), optional; default official system prompt")


class VoiceInfo(BaseModel):
    """
    声音信息模型。
    """
    name: str
    language: str
    gender: Optional[str] = None
    description: Optional[str] = None


class EngineStatus(BaseModel):
    """
    TTS引擎状态模型。
    """
    name: str
    available: bool
    model_loaded: bool
    description: str
    features: list[str]