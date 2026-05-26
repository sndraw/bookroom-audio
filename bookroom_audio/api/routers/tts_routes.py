"""
TTS routes - API endpoints for text-to-speech functionality.
"""

import asyncio
import io
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from bookroom_audio.utils.utils_api import (
    get_api_key_dependency,
    logger,
)

# 导入拆分后的模块
from bookroom_audio.api.routers.tts.schemas import TTSRequest
from bookroom_audio.api.routers.tts.constants import (
    CHATTTS_VOICES,
    CHATTTS_EMOTIONS,
    EDGE_TTS_VOICES,
)
from bookroom_audio.api.routers.tts.utils import select_engine
from bookroom_audio.api.routers.tts.engines import (
    _check_chattss_available,
    _get_chattss_status,
    _get_chattss_model,
    generate_audio_chatt,
    generate_audio_edge_tts,
    generate_audio_pyttsx3,
    EDGE_TTS_AVAILABLE,
    PYTTSX3_AVAILABLE,
)


router = APIRouter(prefix="/v1/tts", tags=["tts"])


def create_tts_routes(args: Any, api_key: Optional[str] = None):
    """
    创建TTS路由。
    
    Args:
        args: 命令行参数
        api_key: API密钥
        
    Returns:
        APIRouter 实例
    """
    optional_api_key = get_api_key_dependency(api_key)

    @router.post(
        "/generate",
        response_class=StreamingResponse,
        dependencies=[Depends(optional_api_key)],
        summary="Generate speech from text",
        description="Converts the provided text into speech audio. "
                    "Supports multiple TTS engines including ChatTTS, Edge TTS, and pyttsx3. "
                    "Returns WAV format audio stream.",
        operation_id="generate_tts",
    )
    async def generate_tts(request: TTSRequest):
        if not request.text or not request.text.strip():
            raise HTTPException(
                status_code=400, detail="No text provided for speech generation"
            )

        try:
            selected_engine = select_engine(request.engine, request.text)

            if selected_engine == "chattts":
                if not _check_chattss_available():
                    raise HTTPException(status_code=500, detail="ChatTTS not available")

                voice = request.voice or request.voice_id
                emotion = request.emotion.lower()

                if emotion not in CHATTTS_EMOTIONS:
                    emotion = "neutral"

                audio_data = await asyncio.to_thread(
                    generate_audio_chatt,
                    text=request.text,
                    voice=voice,
                    emotion=emotion,
                    target_sample_rate=request.sample_rate,
                )
            elif selected_engine == "edge-tts":
                if not EDGE_TTS_AVAILABLE:
                    raise HTTPException(status_code=500, detail="Edge TTS not available")

                voice = request.voice or request.voice_id
                from bookroom_audio.api.routers.tts.utils import parse_rate, parse_volume
                
                rate = parse_rate(request.rate)
                volume = parse_volume(request.volume)

                audio_data = await generate_audio_edge_tts(
                    text=request.text,
                    voice=voice,
                    rate=rate,
                    volume=volume,
                    target_sample_rate=request.sample_rate,
                )
            elif selected_engine == "pyttsx3":
                if not PYTTSX3_AVAILABLE:
                    raise HTTPException(status_code=500, detail="pyttsx3 not available")

                voice_id = request.voice_id or request.voice
                rate = int(request.rate) if isinstance(request.rate, (int, float)) else 200
                volume = float(request.volume) if isinstance(request.volume, (int, float)) else 1.0

                audio_data = await asyncio.to_thread(
                    generate_audio_pyttsx3,
                    text=request.text,
                    voice_id=voice_id,
                    rate=rate,
                    volume=volume,
                    target_sample_rate=request.sample_rate,
                )
            else:
                raise HTTPException(status_code=400, detail=f"Unknown engine: {selected_engine}")

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
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error during speech generation: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Speech generation failed: {str(e)}"
            )

    @router.get(
        "/voices",
        dependencies=[Depends(optional_api_key)],
        summary="List available voices",
        description="Returns a list of available voices for TTS.",
        operation_id="list_voices",
    )
    async def list_voices():
        result = {
            "available_engines": [],
        }

        chattss_status = _get_chattss_status()
        if chattss_status["available"]:
            result["chattts"] = {
                "voices": CHATTTS_VOICES,
                "emotions": CHATTTS_EMOTIONS,
                "description": chattss_status["description"],
                "features": chattss_status["features"],
                "model_loaded": chattss_status["model_loaded"],
            }
            result["available_engines"].append("chattts")

        if EDGE_TTS_AVAILABLE:
            result["edge-tts"] = {
                "voices": EDGE_TTS_VOICES,
                "description": "Edge TTS - 基于Microsoft Azure的在线TTS服务",
                "features": [
                    "支持中文和英文语音合成",
                    "支持多种音色选择",
                    "需要网络连接",
                ],
            }
            result["available_engines"].append("edge-tts")

        if PYTTSX3_AVAILABLE:
            result["pyttsx3"] = {
                "description": "pyttsx3 - 本地离线TTS引擎",
                "features": [
                    "支持多平台本地语音合成",
                    "离线运行，无需网络",
                    "依赖系统语音引擎",
                ],
            }
            result["available_engines"].append("pyttsx3")

        return result

    @router.post(
        "/load",
        dependencies=[Depends(optional_api_key)],
        summary="Load ChatTTS model",
        description="Manually trigger loading of the ChatTTS model. Useful if the model failed to load on startup.",
        operation_id="load_chattss_model",
    )
    async def load_chattss_model():
        try:
            logger.info("Manual loading of ChatTTS model requested")
            model = await asyncio.to_thread(_get_chattss_model)
            
            if model is not None:
                status = _get_chattss_status()
                return {
                    "success": True,
                    "message": "ChatTTS model loaded successfully",
                    "status": status,
                }
            else:
                status = _get_chattss_status()
                return {
                    "success": False,
                    "message": "Failed to load ChatTTS model",
                    "status": status,
                }
        except Exception as e:
            logger.error(f"Error loading ChatTTS model: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Error loading model: {str(e)}",
            }

    return router