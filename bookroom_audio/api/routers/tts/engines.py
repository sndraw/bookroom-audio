"""
TTS engines - Implementation of various TTS engines.
"""

import asyncio
import io
import os
import threading
import tempfile
from typing import Optional

from pydub import AudioSegment

from bookroom_audio.utils.utils_api import logger


# Edge TTS 支持检查
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False


# pyttsx3 支持检查
try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False


# ChatTTS 延迟导入，避免启动时加载复杂依赖
CHATTTS_AVAILABLE = False
_chattts_model = None
_chattts_lock = threading.Lock()


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


async def generate_audio_edge_tts(
    text: str,
    voice: Optional[str] = None,
    rate: str = "0%",
    volume: str = "0%",
    target_sample_rate: int = 16000,
) -> bytes:
    """
    使用 Edge TTS 生成音频。
    
    Args:
        text: 要转换的文本
        voice: 语音名称
        rate: 语速（百分比格式）
        volume: 音量（百分比格式）
        target_sample_rate: 目标采样率
        
    Returns:
        WAV格式的音频数据
    """
    from bookroom_audio.api.routers.tts.constants import EDGE_TTS_VOICES
    from bookroom_audio.api.routers.tts.utils import get_default_edge_voice

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


# pyttsx3 线程本地存储
_local_engine_storage = threading.local()


def get_thread_local_pyttsx3_engine():
    """获取线程本地的 pyttsx3 引擎实例"""
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
    """
    使用 pyttsx3 生成音频。
    
    Args:
        text: 要转换的文本
        voice_id: 语音ID
        rate: 语速（WPM）
        volume: 音量（0.0-1.0）
        target_sample_rate: 目标采样率
        
    Returns:
        WAV格式的音频数据
    """
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


def _check_chattss_model_files() -> dict:
    """检查 ChatTTS 模型文件是否完整"""
    import glob
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
    
    # 获取环境变量配置的模型下载端点
    hf_endpoint = os.getenv("HF_ENDPOINT", "https://www.modelscope.cn")
    modelscope_endpoint = os.getenv("MODELSCOPE_ENDPOINT", "https://www.modelscope.cn")
    
    # 根据配置选择下载端点
    if hf_endpoint == "https://www.modelscope.cn":
        download_url = f"{modelscope_endpoint}/models/2Noise/ChatTTS"
        download_method = f"HF_ENDPOINT={modelscope_endpoint} huggingface-cli download 2Noise/ChatTTS"
    else:
        download_url = f"{hf_endpoint}/2Noise/ChatTTS"
        download_method = f"HF_ENDPOINT={hf_endpoint} huggingface-cli download 2Noise/ChatTTS"
    
    # 检查缓存目录是否存在
    if not os.path.exists(chattts_cache_dir):
        return {
            "complete": False,
            "missing": ["整个 ChatTTS 模型目录"],
            "existing": [],
            "cache_dir": chattts_cache_dir,
            "download_url": download_url,
            "download_method": download_method
        }
    
    # 检查模型文件完整性
    for file_pattern, size in required_files.items():
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
        "download_url": download_url,
        "download_method": download_method
    }


def _get_chattss_model():
    """获取或加载 ChatTTS 模型"""
    global _chattts_model
    import os
    
    if _chattts_model is None:
        with _chattts_lock:
            if _chattts_model is None:
                logger.info("Loading ChatTTS model...")
                try:
                    # 设置ChatTTS模型缓存目录
                    from bookroom_audio.utils.config import get_config
                    config = get_config()
                    cache_dir = config.cache.cache_dir
                    
                    # 设置本地文件优先（必须在导入ChatTTS之前设置）
                    os.environ["HF_HUB_OFFLINE"] = "1" if config.cache.local_files_only else "0"
                    os.environ["TRANSFORMERS_CACHE"] = cache_dir
                    os.environ["HF_HOME"] = cache_dir
                    os.environ["HUGGINGFACE_HUB_CACHE"] = cache_dir
                    
                    logger.info(f"Local files only mode: {config.cache.local_files_only}")
                    logger.info(f"HF_HUB_OFFLINE: {os.environ.get('HF_HUB_OFFLINE')}")
                    logger.info(f"ChatTTS model cache directory: {cache_dir}")
                    
                    # 检查模型文件是否存在
                    model_status = _check_chattss_model_files()
                    logger.info(f"Model files status: {'complete' if model_status['complete'] else 'incomplete'}")
                    if not model_status['complete']:
                        logger.warning(f"Missing model files: {model_status['missing']}")
                    
                    # 延迟导入 ChatTTS
                    import ChatTTS
                    _chattts_model = ChatTTS.Chat()
                    
                    # 使用 Hugging Face 源加载模型
                    logger.info("Loading ChatTTS model components...")
                    
                    # 构建模型路径，ChatTTS 期望模型在 {custom_path}/models--2Noise--ChatTTS/snapshots/ 目录下
                    chattts_model_dir = os.path.join(cache_dir, "models--2Noise--ChatTTS")
                    logger.info(f"ChatTTS model directory: {chattts_model_dir}")
                    
                    try:
                        success = _chattts_model.load(
                            source="huggingface",
                            compile=False,
                            custom_path=cache_dir
                        )
                    except Exception as load_error:
                        logger.error(f"ChatTTS load() failed with exception: {load_error}", exc_info=True)
                        success = False
                    
                    # 检查组件是否真正加载成功
                    if success:
                        logger.info(f"ChatTTS components status: vocos={_chattts_model.vocos is not None}, gpt={_chattts_model.gpt is not None}, tokenizer={_chattts_model.tokenizer is not None}, embed={_chattts_model.embed is not None}, decoder={_chattts_model.decoder is not None}")
                        if not _chattts_model.has_loaded():
                            logger.warning("ChatTTS load() returned True but components not properly initialized")
                            # 尝试重新加载
                            logger.info("Attempting to reload ChatTTS model...")
                            _chattts_model.clear()
                            success = _chattts_model.load(
                                source="huggingface",
                                compile=False
                            )
                    
                    if success and _chattts_model.has_loaded():
                        logger.info("ChatTTS model loaded successfully!")
                    else:
                        logger.error("Failed to load ChatTTS model - components not initialized")
                        _chattts_model = None
                    
                except Exception as e:
                    logger.error(f"Error loading ChatTTS model: {e}", exc_info=True)
                    _chattts_model = None
    
    return _chattts_model


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


def generate_audio_chatt(
    text: str,
    voice: Optional[str] = None,
    emotion: str = "neutral",
    target_sample_rate: int = 16000,
) -> bytes:
    """
    使用 ChatTTS 生成音频。
    
    Args:
        text: 要转换的文本
        voice: 语音选择（male, female, neutral 或数字索引）
        emotion: 情感类型
        target_sample_rate: 目标采样率
        
    Returns:
        WAV格式的音频数据
    """
    from bookroom_audio.api.routers.tts.constants import CHATTTS_VOICES, CHATTTS_EMOTIONS
    from bookroom_audio.api.routers.tts.utils import preprocess_text_for_chattts
    
    # 预处理文本，移除可能导致警告的无效字符
    text = preprocess_text_for_chattts(text)
    
    model = _get_chattss_model()
    
    # 如果模型未加载，尝试自动加载
    if model is None:
        logger.info("ChatTTS model not loaded, attempting automatic loading...")
        
        # 检查模型文件是否存在
        model_status = _check_chattss_model_files()
        if not model_status['complete']:
            raise Exception(f"ChatTTS model files not found. Missing: {model_status['missing']}. Please download the model first.")
        
        # 尝试加载模型
        global _chattts_model
        import ChatTTS
        _chattts_model = ChatTTS.Chat()
        
        # 获取缓存目录配置
        from bookroom_audio.utils.config import get_config
        config = get_config()
        cache_dir = config.cache.cache_dir
        
        try:
            success = _chattts_model.load(
                source="huggingface", 
                compile=False,
                custom_path=cache_dir
            )
            if success and _chattts_model.has_loaded():
                logger.info("ChatTTS model loaded successfully!")
                model = _chattts_model
            else:
                raise Exception("Failed to load ChatTTS model - components not initialized")
        except Exception as e:
            _chattts_model = None
            raise Exception(f"Failed to load ChatTTS model: {str(e)}")
    
    if model is None:
        raise Exception("ChatTTS model not loaded")
    
    # 设置情感参数
    if emotion not in CHATTTS_EMOTIONS:
        emotion = "neutral"
    
    # 设置语音参数
    voice_num = 0
    if voice is not None:
        if voice in CHATTTS_VOICES:
            # 根据语音类型设置索引
            voice_map = {"male": 0, "female": 1, "neutral": 2}
            voice_num = voice_map.get(voice, 0)
        else:
            try:
                voice_num = int(voice)
            except ValueError:
                voice_num = 0
    
    # 使用 ChatTTS 提供的参数类
    params_infer_code = model.InferCodeParams()
    params_infer_code.spk_emb = None  # 使用默认语音
    params_infer_code.temperature = 0.3
    params_infer_code.top_k = 20
    params_infer_code.top_p = 0.8
    
    # 添加情感控制
    if emotion == "happy":
        params_infer_code.temperature = 0.5
    elif emotion == "sad":
        params_infer_code.temperature = 0.1
    elif emotion == "angry":
        params_infer_code.temperature = 0.7
    
    # 生成音频
    audio_data = model.infer(
        [text],
        skip_refine_text=False,
        params_infer_code=params_infer_code,
    )
    
    # 获取音频数据
    wav_data = audio_data[0]
    
    # 将 float32 转换为 int16
    import numpy as np
    wav_data_int16 = (wav_data * 32767).astype(np.int16)
    
    # 转换采样率
    audio = AudioSegment(
        data=wav_data_int16.tobytes(),
        sample_width=2,
        frame_rate=24000,
        channels=1
    )
    
    audio = audio.set_frame_rate(target_sample_rate)
    
    out_buf = io.BytesIO()
    audio.export(out_buf, format="wav")
    
    return out_buf.getvalue()