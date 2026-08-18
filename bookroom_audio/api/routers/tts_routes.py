"""
TTS routes - API endpoints for text-to-speech functionality.
"""

import asyncio
import base64
import io
import json
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
    COSYVOICE_VOICES,
    EDGE_TTS_VOICES,
)
from bookroom_audio.api.routers.tts.utils import select_engine
from bookroom_audio.api.routers.tts.engines import (
    _check_chattss_available,
    _get_chattss_status,
    _get_chattss_model,
    _check_cosyvoice_available,
    _get_cosyvoice_status,
    _get_cosyvoice_model,
    _check_cosyvoice3_available,
    _get_cosyvoice3_status,
    _check_kokoro_available,
    _kokoro_status,
    generate_audio_chatt,
    generate_audio_cosyvoice,
    generate_audio_cosyvoice3,
    generate_audio_edge_tts,
    generate_audio_kokoro,
    generate_audio_pyttsx3,
    stream_tts_edge_with_words,
    EDGE_TTS_AVAILABLE,
    PYTTSX3_AVAILABLE,
)


def create_tts_routes(args: Any, api_key: Optional[str] = None):
    router = APIRouter(prefix="/v1/tts", tags=["tts"])
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
            elif selected_engine == "cosyvoice":
                if not _check_cosyvoice_available():
                    raise HTTPException(status_code=500, detail="CosyVoice2 not available. 请安装：pip install git+https://github.com/FunAudioLLM/CosyVoice.git")

                voice = request.voice or request.voice_id or "中文女"

                audio_data = await asyncio.to_thread(
                    generate_audio_cosyvoice,
                    text=request.text,
                    voice=voice,
                    target_sample_rate=request.sample_rate,
                )
            elif selected_engine == "cosyvoice3":
                # CosyVoice3 仅 zero_shot 模式（无预置音色），必须携带参考音频。
                # 缺少参考音频 → generate_audio_cosyvoice3 抛 ValueError → 400 显式报错，
                # 绝不静默回退到其它引擎/模型（避免产出错误语音）。
                if not _check_cosyvoice3_available():
                    raise HTTPException(
                        status_code=500,
                        detail="CosyVoice3 not available. 请确认已下载 Fun-CosyVoice3-0.5B-2512 并配置 COSYVOICE3_MODEL_DIR",
                    )

                audio_data = await asyncio.to_thread(
                    generate_audio_cosyvoice3,
                    text=request.text,
                    reference_audio=request.reference_audio,
                    reference_text=request.reference_text,
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
            elif selected_engine == "kokoro":
                # Kokoro-82M（Apache 2.0 可商用）：text-only 预置音色，替代 ChatTTS。
                # 失败显式报错（500），绝不静默回退到其它引擎。
                if not _check_kokoro_available():
                    raise HTTPException(status_code=500, detail="Kokoro not available. 请安装：pip install kokoro")

                voice = request.voice or request.voice_id or "zf_001"

                audio_data = await asyncio.to_thread(
                    generate_audio_kokoro,
                    text=request.text,
                    voice=voice,
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

        cosyvoice_status = _get_cosyvoice_status()
        if cosyvoice_status["available"]:
            result["cosyvoice"] = {
                "voices": COSYVOICE_VOICES,
                "description": cosyvoice_status["description"],
                "features": cosyvoice_status["features"],
                "model_loaded": cosyvoice_status["model_loaded"],
                "model_exists": cosyvoice_status["model_exists"],
                "model_dir": cosyvoice_status["model_dir"],
            }
            result["available_engines"].append("cosyvoice")

        cosyvoice3_status = _get_cosyvoice3_status()
        if cosyvoice3_status["available"]:
            result["cosyvoice3"] = {
                "voices": [],  # 无预置音色：zero_shot 音色克隆需携带参考音频
                "description": cosyvoice3_status["description"],
                "features": cosyvoice3_status["features"],
                "model_loaded": cosyvoice3_status["model_loaded"],
                "model_exists": cosyvoice3_status["model_exists"],
                "model_dir": cosyvoice3_status["model_dir"],
                "requires_reference_audio": cosyvoice3_status["requires_reference_audio"],
            }
            result["available_engines"].append("cosyvoice3")

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

        kokoro_status = _kokoro_status()
        if kokoro_status["available"]:
            from bookroom_audio.api.routers.tts.constants import KOKORO_VOICES
            result["kokoro"] = {
                "voices": KOKORO_VOICES,
                "description": kokoro_status["description"],
                "features": kokoro_status["features"],
                "model_loaded": kokoro_status["model_loaded"],
                "weights_home": kokoro_status["weights_home"],
            }
            result["available_engines"].append("kokoro")

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

    @router.post(
        "/stream",
        response_class=StreamingResponse,
        dependencies=[Depends(optional_api_key)],
        summary="Stream speech with word boundaries",
        description="Edge TTS 流式生成，SSE 输出：先 words（词边界时间戳，viseme 口型驱动用），再 audio chunk（WAV base64）。",
        operation_id="stream_tts_with_words",
    )
    async def stream_tts(request: TTSRequest):
        if not request.text or not request.text.strip():
            raise HTTPException(status_code=400, detail="No text provided")
        if not EDGE_TTS_AVAILABLE:
            raise HTTPException(status_code=500, detail="Edge TTS not available")

        from bookroom_audio.api.routers.tts.utils import parse_rate, parse_volume

        rate = parse_rate(request.rate)
        volume = parse_volume(request.volume)
        voice = request.voice or request.voice_id

        def sse_gen():
            try:
                wav, words = asyncio.run(
                    stream_tts_edge_with_words(
                        text=request.text,
                        voice=voice,
                        rate=rate,
                        volume=volume,
                        target_sample_rate=request.sample_rate,
                    )
                )
            except Exception as e:  # noqa: BLE001
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'words', 'words': words})}\n\n"
            chunk_size = 4096
            for i in range(0, len(wav), chunk_size):
                chunk = base64.b64encode(wav[i : i + chunk_size]).decode()
                yield f"data: {json.dumps({'type': 'audio', 'chunk': chunk})}\n\n"
            yield 'data: {"type": "end"}\n\n'

        return StreamingResponse(
            sse_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router