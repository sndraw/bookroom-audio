"""
This module contains all TTS (Text-to-Speech) related routes.
"""

import io
import asyncio
import os
import tempfile
import threading
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import pyttsx3
from pydub import AudioSegment

from bookroom_audio.utils.utils_api import (
    get_api_key_dependency,
    logger,
)

router = APIRouter(prefix="/v1/tts", tags=["tts"])


class TTSRequest(BaseModel):
    """
    TTS 请求参数模型。

    Attributes:
        text: 需要转换的文本内容。
        voice_id: 可选的声音 ID 或名称。
        rate: 语速 (words per minute)。
        volume: 音量 (0.0 - 1.0)。
        sample_rate: 音频采样率 (Hz)，可选，默认为 16000。
    """

    text: str
    voice_id: Optional[str] = None
    rate: int = 200
    volume: float = 1.0
    sample_rate: int = 16000


# --- 线程局部存储用于管理 pyttsx3 引擎 ---
_local_engine_storage = threading.local()


def get_thread_local_engine():
    if not hasattr(_local_engine_storage, "engine"):
        _local_engine_storage.engine = pyttsx3.init()
    return _local_engine_storage.engine


def generate_audio_sync(
    text: str,
    voice_id: Optional[str] = None,
    rate: int = 200,
    volume: float = 1.0,
    target_sample_rate: int = 16000,
) -> bytes:

    engine = get_thread_local_engine()

    # 保存原始属性以恢复
    original_rate = engine.getProperty("rate")
    original_volume = engine.getProperty("volume")
    original_voice = engine.getProperty("voice")

    temp_path = None
    try:
        engine.setProperty("rate", rate)
        engine.setProperty("volume", volume)

        if voice_id:
            voices = engine.getProperty("voices")
            for voice in voices:
                if (
                    voice_id.lower() in voice.id.lower()
                    or voice_id.lower() in voice.name.lower()
                ):
                    engine.setProperty("voice", voice.id)
                    break

        fd, temp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        engine.save_to_file(text, temp_path)
        engine.runAndWait()

        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            raise Exception("TTS engine generated an empty file.")

        # 1. 加载生成的音频
        audio = AudioSegment.from_wav(temp_path)

        # 2. 设置目标采样率
        # 注意：如果目标采样率与原始一致，set_frame_rate 也会处理，但可能会有轻微开销
        audio = audio.set_frame_rate(target_sample_rate)

        # 3. 导出到字节流
        out_buf = io.BytesIO()
        # export 时指定 format 为 wav
        audio.export(out_buf, format="wav")

        # 4. 获取字节数据
        audio_data = out_buf.getvalue()

        return audio_data
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

        # 恢复属性
        try:
            engine.setProperty("rate", original_rate)
            engine.setProperty("volume", original_volume)
            if original_voice:
                engine.setProperty("voice", original_voice)
        except Exception:
            pass


def create_tts_routes(args: Any, api_key: Optional[str] = None):
    """
    创建 TTS 相关的路由。

    Args:
        args: 启动参数，包含默认配置等。
        api_key: 可选的 API Key，用于保护接口。

    Returns:
        router: 配置好的 FastAPI Router 对象。
    """
    optional_api_key = get_api_key_dependency(api_key)

    @router.post(
        "/generate",
        response_class=StreamingResponse,
        dependencies=[Depends(optional_api_key)],
        summary="Generate speech from text",
        description="Converts the provided text into speech audio using the system TTS engine.",
        operation_id="generate_tts",
    )
    async def generate_tts(request: TTSRequest):
        """
        将文本转换为语音音频。

        Args:
            request: 包含文本、声音 ID、语速和音量等信息的 TTSRequest 对象。

        Returns:
            StreamingResponse: 包含生成的语音音频的流。
        """
        if not request.text or not request.text.strip():
            raise HTTPException(
                status_code=400, detail="No text provided for speech generation"
            )

        try:
            audio_data = await asyncio.to_thread(
                generate_audio_sync,
                text=request.text,
                voice_id=request.voice_id,
                rate=request.rate,
                volume=request.volume,
                target_sample_rate=request.sample_rate,
            )

            if not audio_data:
                raise HTTPException(status_code=500, detail="Generated audio is empty")

            filename = f"speech_{hash(request.text) % 10000}.wav"

            return StreamingResponse(
                io.BytesIO(audio_data),
                media_type="audio/wav",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error during speech generation: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Speech generation failed: {str(e)}"
            )

    return router
