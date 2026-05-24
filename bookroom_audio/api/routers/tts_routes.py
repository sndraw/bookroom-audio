"""
This module contains all TTS (Text-to-Speech) related routes.
"""

import asyncio
import io
import os
import re
import tempfile
import threading
import wave
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pydub import AudioSegment

from bookroom_audio.utils.utils_api import (
    get_api_key_dependency,
    logger,
)

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False

# ChatTTS 延迟导入，避免启动时加载复杂依赖
CHATTTS_AVAILABLE = False

def _check_chattss_available() -> bool:
    """检查 ChatTTS 是否可用（延迟检查）"""
    global CHATTTS_AVAILABLE
    if not CHATTTS_AVAILABLE:
        try:
            import ChatTTS
            CHATTTS_AVAILABLE = True
        except ImportError:
            CHATTTS_AVAILABLE = False
    return CHATTTS_AVAILABLE


def _get_chattss_status() -> dict:
    """获取 ChatTTS 完整状态信息"""
    global _chattts_model
    
    model_status = _check_chattss_model_files()
    
    return {
        "available": _check_chattss_available(),
        "model_loaded": _chattts_model is not None,
        "model_files_complete": model_status["complete"],
        "existing_files": model_status["existing"],
        "missing_files": model_status["missing"],
        "download_url": model_status["download_url"],
        "download_command": model_status["download_method"],
        "description": "ChatTTS - 高质量中文离线TTS引擎，支持情感控制和多音色",
        "features": [
            "支持中文语音合成",
            "支持情感控制（happy, sad, angry, neutral）",
            "支持多音色选择（male, female）",
            "离线运行，无需网络",
        ]
    }

router = APIRouter(prefix="/v1/tts", tags=["tts"])


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
        engine: TTS引擎选择，可选值: chattts, edge-tts, pyttsx3, auto。
        emotion: 情感类型（仅ChatTTS支持），可选: happy, sad, angry, neutral。
    """

    text: str = Field(..., description="Text content to convert to speech")
    voice_id: Optional[str] = Field(None, description="Voice ID or name (legacy parameter, use voice instead)")
    voice: Optional[str] = Field(None, description="Voice name. For ChatTTS: use voice index (0-10). For Edge TTS: zh-CN-XiaoxiaoNeural, zh-CN-YunxiNeural, etc.")
    rate: Any = Field(200, description="Speech rate. Integer (WPM) or percentage format (e.g., +10%, -20%)")
    volume: Any = Field(1.0, description="Volume level. Float between 0.0-1.0 or percentage format (e.g., 50%, 100%)")
    sample_rate: int = Field(16000, description="Audio sample rate in Hz. Common values: 16000, 22050, 44100")
    engine: str = Field("auto", description="TTS engine. Options: chattts, edge-tts, pyttsx3, auto. Auto selects based on text language")
    emotion: str = Field("neutral", description="Emotion type (ChatTTS only). Options: happy, sad, angry, neutral")


CHINESE_VOICES = [
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunxiaNeural",
    "zh-CN-YunyangNeural",
    "zh-CN-LiaoningNeural",
    "zh-CN-ShandongNeural",
    "zh-CN-GuangxiNeural",
    "zh-CN-YunnanNeural",
]

ENGLISH_VOICES = [
    "en-US-AriaNeural",
    "en-US-DavidNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
]

EDGE_TTS_VOICES = CHINESE_VOICES + ENGLISH_VOICES

CHATTTS_VOICES = [
    "male",
    "female",
    "neutral",
]

CHATTTS_EMOTIONS = [
    "happy",
    "sad",
    "angry",
    "neutral",
]


def detect_language(text: str) -> str:
    chinese_char_pattern = re.compile(r'[\u4e00-\u9fff]+')
    if chinese_char_pattern.search(text):
        return "zh"
    return "en"


def get_default_edge_voice(text: str) -> str:
    lang = detect_language(text)
    if lang == "zh":
        return "zh-CN-XiaoxiaoNeural"
    return "en-US-AriaNeural"


def parse_rate(rate: Any) -> str:
    if isinstance(rate, str):
        if rate.endswith("%"):
            return rate
        try:
            wpm = int(rate)
            return f"{int((wpm - 200) / 2)}%"
        except ValueError:
            return "0%"
    elif isinstance(rate, int):
        return f"{int((rate - 200) / 2)}%"
    return "0%"


def parse_volume(volume: Any) -> str:
    if isinstance(volume, str):
        if volume.endswith("%"):
            return volume
        try:
            vol = float(volume)
            return f"{int((vol - 0.5) * 200)}%"
        except ValueError:
            return "0%"
    elif isinstance(volume, float):
        return f"{int((volume - 0.5) * 200)}%"
    return "0%"


async def generate_audio_edge_tts(
    text: str,
    voice: Optional[str] = None,
    rate: str = "0%",
    volume: str = "0%",
    target_sample_rate: int = 16000,
) -> bytes:
    if not voice:
        voice = get_default_edge_voice(text)

    if voice not in EDGE_TTS_VOICES:
        raise ValueError(f"Unsupported voice: {voice}. Available voices: {EDGE_TTS_VOICES}")

    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)

    audio_bytes = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes.write(chunk["data"])

    audio_bytes.seek(0)

    audio = AudioSegment.from_file(audio_bytes, format="mp3")
    audio = audio.set_frame_rate(target_sample_rate)

    out_buf = io.BytesIO()
    audio.export(out_buf, format="wav")

    return out_buf.getvalue()


_local_engine_storage = threading.local()


def get_thread_local_pyttsx3_engine():
    if not hasattr(_local_engine_storage, "engine"):
        _local_engine_storage.engine = pyttsx3.init()
    return _local_engine_storage.engine


def generate_audio_pyttsx3(
    text: str,
    voice_id: Optional[str] = None,
    rate: int = 200,
    volume: float = 1.0,
    target_sample_rate: int = 16000,
) -> bytes:
    engine = get_thread_local_pyttsx3_engine()

    original_rate = engine.getProperty("rate")
    original_volume = engine.getProperty("volume")
    original_voice = engine.getProperty("voice")

    temp_path = None
    try:
        engine.setProperty("rate", rate)
        engine.setProperty("volume", max(0.0, min(1.0, volume)))

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

        try:
            audio = AudioSegment.from_wav(temp_path)
            audio = audio.set_frame_rate(target_sample_rate)

            out_buf = io.BytesIO()
            audio.export(out_buf, format="wav")
            audio_data = out_buf.getvalue()
        except Exception as e:
            logger.warning(f"Failed to process audio with pydub: {e}. Using raw file.")
            with open(temp_path, "rb") as f:
                audio_data = f.read()

        return audio_data
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

        try:
            engine.setProperty("rate", original_rate)
            engine.setProperty("volume", original_volume)
            if original_voice:
                engine.setProperty("voice", original_voice)
        except Exception:
            pass


_chattts_model = None
_chattts_lock = threading.Lock()


def _check_chattss_model_files() -> dict:
    """检查 ChatTTS 模型文件是否完整"""
    from bookroom_audio.utils.config import get_config
    config = get_config()
    
    # 检查统一缓存目录中的 ChatTTS 模型
    chattts_cache_dir = os.path.join(config.cache.cache_dir, "models--2Noise--ChatTTS")
    
    required_files = {
        "snapshots/*/asset/DVAE.safetensors": "~57MB",
        "snapshots/*/asset/Decoder.safetensors": "~98MB",
        "snapshots/*/asset/Embed.safetensors": "~1GB",
        "snapshots/*/asset/Vocos.safetensors": "~1GB",
        "snapshots/*/asset/gpt/model.safetensors": "~813MB",
        "snapshots/*/asset/tokenizer/tokenizer.json": "小文件",
        "snapshots/*/asset/tokenizer/tokenizer_config.json": "小文件",
        "snapshots/*/asset/tokenizer/special_tokens_map.json": "小文件",
    }
    
    missing_files = []
    existing_files = []
    
    # 检查缓存目录是否存在
    if not os.path.exists(chattts_cache_dir):
        return {
            "complete": False,
            "missing": ["整个 ChatTTS 模型目录"],
            "existing": [],
            "cache_dir": chattts_cache_dir,
            "download_url": "https://hf-mirror.com/2Noise/ChatTTS",
            "download_method": "HF_ENDPOINT=https://hf-mirror.com huggingface-cli download 2Noise/ChatTTS"
        }
    
    # 检查模型文件完整性
    import glob
    for file_pattern, size in required_files.items():
        # 使用 glob 匹配文件（支持 * 通配符）
        matched_files = glob.glob(os.path.join(chattts_cache_dir, file_pattern))
        if matched_files:
            existing_files.append(f"{file_pattern} ({size})")
        else:
            missing_files.append(f"{file_pattern} ({size})")
    
    return {
        "complete": len(missing_files) == 0,
        "missing": missing_files,
        "existing": existing_files,
        "cache_dir": chattts_cache_dir,
        "download_url": "https://hf-mirror.com/2Noise/ChatTTS",
        "download_method": "HF_ENDPOINT=https://hf-mirror.com huggingface-cli download 2Noise/ChatTTS"
    }


def get_chattts_model():
    global _chattts_model
    if _chattts_model is None:
        with _chattts_lock:
            if _chattts_model is None:
                logger.info("Loading ChatTTS model...")
                try:
                    # 设置ChatTTS模型缓存目录
                    from bookroom_audio.utils.config import get_config
                    config = get_config()
                    cache_dir = config.cache.cache_dir
                    
                    # 设置Hugging Face缓存环境变量，确保ChatTTS模型下载到统一目录
                    os.environ["TRANSFORMERS_CACHE"] = cache_dir
                    os.environ["HF_HOME"] = cache_dir
                    os.environ["HUGGINGFACE_HUB_CACHE"] = cache_dir
                    
                    logger.info(f"ChatTTS model cache directory: {cache_dir}")
                    
                    # 延迟导入 ChatTTS
                    import ChatTTS
                    _chattts_model = ChatTTS.Chat()
                    
                    # 使用 Hugging Face 源下载模型，这样可以利用 HF_ENDPOINT 环境变量
                    # 默认的 local 源使用 GitHub 下载，可能在某些网络环境下无法访问
                    logger.info("Downloading ChatTTS model from Hugging Face...")
                    success = _chattts_model.load(
                        source="huggingface",
                        compile=False
                    )
                    
                    if success:
                        logger.info("ChatTTS model loaded successfully")
                    else:
                        raise RuntimeError("ChatTTS model download failed")
                        
                except ImportError as e:
                    logger.error(f"ChatTTS import failed: {e}")
                    raise RuntimeError("ChatTTS is not installed. Please install it with: pip install chattts")
                except Exception as e:
                    logger.error(f"Failed to load ChatTTS model: {e}")
                    # 检查模型文件完整性
                    model_status = _check_chattss_model_files()
                    if not model_status["complete"]:
                        error_msg = f"""
ChatTTS 模型文件不完整

已存在的文件:
{chr(10).join(f"  ✓ {f}" for f in model_status["existing"])}

缺失的文件:
{chr(10).join(f"  ✗ {f}" for f in model_status["missing"])}

推荐下载方法（使用 HF Mirror）:
  {model_status["download_method"]}

或者手动下载:
  {model_status["download_url"]}
                        """
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)
                    raise
    return _chattts_model


def generate_audio_chatt(
    text: str,
    voice: Optional[str] = None,
    emotion: str = "neutral",
    target_sample_rate: int = 16000,
) -> bytes:
    model = get_chattts_model()

    params = {
        "temperature": 0.3,
        "top_p": 0.7,
        "top_k": 20,
    }

    if emotion == "happy":
        params["temperature"] = 0.5
    elif emotion == "sad":
        params["temperature"] = 0.2
    elif emotion == "angry":
        params["temperature"] = 0.4

    if voice == "male":
        params["speaker_id"] = 2222
    elif voice == "female":
        params["speaker_id"] = 7869
    else:
        params["speaker_id"] = 0

    # ChatTTS 返回的是 numpy 数组，需要正确处理
    wav = model.infer(text)[0]
    
    # 确保数据是 numpy 数组
    import numpy as np
    if isinstance(wav, np.ndarray):
        # ChatTTS 返回的是 float32 数据，需要转换为 int16
        # 首先归一化到 [-1, 1]
        wav = wav / np.max(np.abs(wav))
        # 然后转换为 int16 (范围 -32768 到 32767)
        wav = (wav * 32767).astype(np.int16)
    
    # 确保数据长度是 sample_width * channels 的倍数
    sample_width = 2  # 16-bit
    channels = 1
    data_len = len(wav) if isinstance(wav, np.ndarray) else len(wav.tobytes())
    padding = (sample_width * channels) - (data_len % (sample_width * channels))
    if padding < (sample_width * channels):
        if isinstance(wav, np.ndarray):
            wav = np.pad(wav, (0, padding // sample_width), mode='constant')
        else:
            wav = wav + b'\x00' * padding

    audio = AudioSegment(
        wav.tobytes() if isinstance(wav, np.ndarray) else wav,
        frame_rate=24000,
        sample_width=sample_width,
        channels=channels
    )

    audio = audio.set_frame_rate(target_sample_rate)

    out_buf = io.BytesIO()
    audio.export(out_buf, format="wav")

    return out_buf.getvalue()


def select_engine(engine: str, text: str) -> str:
    if engine != "auto":
        return engine

    has_chinese = detect_language(text) == "zh"

    if has_chinese:
        if _check_chattss_available():
            return "chattts"
        elif EDGE_TTS_AVAILABLE:
            logger.info("ChatTTS not available, falling back to Edge TTS for Chinese text")
            return "edge-tts"
        elif PYTTSX3_AVAILABLE:
            logger.info("ChatTTS and Edge TTS not available, falling back to pyttsx3 for Chinese text")
            return "pyttsx3"
    else:
        if PYTTSX3_AVAILABLE:
            return "pyttsx3"
        elif EDGE_TTS_AVAILABLE:
            return "edge-tts"
        elif _check_chattss_available():
            return "chattts"

    raise ValueError("No TTS engine available")


def create_tts_routes(args: Any, api_key: Optional[str] = None):
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
                "model_files_complete": chattss_status["model_files_complete"],
                "missing_files": chattss_status["missing_files"] if not chattss_status["model_files_complete"] else [],
                "download_info": {
                    "url": chattss_status["download_url"],
                    "command": chattss_status["download_command"],
                } if not chattss_status["model_files_complete"] else None,
            }
            result["available_engines"].append("chattts")

        if EDGE_TTS_AVAILABLE:
            result["edge_tts"] = {
                "chinese_voices": CHINESE_VOICES,
                "english_voices": ENGLISH_VOICES,
                "descriptions": {
                    "zh-CN-XiaoxiaoNeural": "晓晓 - 标准中文女声",
                    "zh-CN-YunxiNeural": "云希 - 温柔中文女声",
                    "zh-CN-YunxiaNeural": "云霞 - 亲切中文女声",
                    "zh-CN-YunyangNeural": "云阳 - 标准中文男声",
                    "zh-CN-LiaoningNeural": "辽宁方言女声",
                    "zh-CN-ShandongNeural": "山东方言男声",
                    "zh-CN-GuangxiNeural": "广西方言女声",
                    "zh-CN-YunnanNeural": "云南方言女声",
                    "en-US-AriaNeural": "Aria - 英文女声",
                    "en-US-DavidNeural": "David - 英文男声",
                    "en-US-GuyNeural": "Guy - 英文男声",
                    "en-US-JennyNeural": "Jenny - 英文女声",
                },
            }
            result["available_engines"].append("edge-tts")

        if PYTTSX3_AVAILABLE:
            engine = get_thread_local_pyttsx3_engine()
            voices = engine.getProperty("voices")
            pyttsx3_voices = [{"id": v.id, "name": v.name, "language": v.language} for v in voices]
            result["pyttsx3"] = {
                "voices": pyttsx3_voices,
                "description": "系统本地TTS引擎，完全离线",
            }
            result["available_engines"].append("pyttsx3")

        return result

    return router