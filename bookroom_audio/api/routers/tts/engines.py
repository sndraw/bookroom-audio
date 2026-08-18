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


def _split_sentence_to_visemes(sentence: str, start_ms: float, duration_ms: float) -> list[dict]:
    """
    将一句文本切成口型驱动单元（viseme），句内时长按字符均分近似。
    - 中文：逐字（跳过空白与标点，标点处不计口型、不占时长权重）
    - 英文：按空格分词
    返回 [{"text","start_ms","end_ms"}]
    """
    import re

    units: list[str] = []
    if re.search(r"[\u4e00-\u9fff]", sentence):
        # 中文：逐字（保留中文与字母数字，跳过标点空白）
        for ch in sentence:
            if ch.strip() and not re.match(r"[，。！？、；：""''（）\s]", ch):
                units.append(ch)
    else:
        units = [w for w in sentence.split() if w]

    if not units:
        return []
    seg = duration_ms / len(units)
    words = []
    for i, u in enumerate(units):
        words.append({
            "text": u,
            "start_ms": round(start_ms + i * seg, 1),
            "end_ms": round(start_ms + (i + 1) * seg, 1),
        })
    return words


async def stream_tts_edge_with_words(
    text: str,
    voice: Optional[str] = None,
    rate: str = "0%",
    volume: str = "0%",
    target_sample_rate: int = 16000,
) -> tuple[bytes, list[dict]]:
    """
    Edge TTS 生成音频 + viseme 时间戳（口型驱动）。
    edge-tts 中文仅返回句级 SentenceBoundary → 按句时长 + 逐字均分近似。

    Returns:
        (wav_bytes, words) 其中 words: [{"text", "start_ms", "end_ms"}]
    """
    from bookroom_audio.api.routers.tts.constants import EDGE_TTS_VOICES
    from bookroom_audio.api.routers.tts.utils import get_default_edge_voice

    if not voice:
        voice = get_default_edge_voice(text)
    if voice not in EDGE_TTS_VOICES:
        raise ValueError(f"Unsupported voice: {voice}. Available voices: {EDGE_TTS_VOICES}")

    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)

    mp3_chunks: list[bytes] = []
    sentence_bounds: list[tuple[float, float, str]] = []  # (start_ms, duration_ms, text)

    async for chunk in communicate.stream():
        t = chunk["type"]
        if t == "audio":
            mp3_chunks.append(chunk["data"])
        elif t == "SentenceBoundary":
            offset_ticks = chunk.get("offset", 0)
            duration_ticks = chunk.get("duration", 0)
            sentence_bounds.append((
                offset_ticks / 10000,
                duration_ticks / 10000,
                chunk.get("text", ""),
            ))

    mp3 = b"".join(mp3_chunks)
    audio = AudioSegment.from_file(io.BytesIO(mp3), format="mp3")
    audio = audio.set_frame_rate(target_sample_rate)
    out_buf = io.BytesIO()
    audio.export(out_buf, format="wav")

    # 无句级边界时（退化）：按整段音频时长均分
    words: list[dict] = []
    if not sentence_bounds and mp3:
        total_ms = len(audio)
        words = _split_sentence_to_visemes(text, 0, total_ms)
    else:
        for start_ms, dur_ms, sentence in sentence_bounds:
            words.extend(_split_sentence_to_visemes(sentence, start_ms, dur_ms))

    return out_buf.getvalue(), words


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


# ---------------------------------------------------------------------------
# CosyVoice 2（阿里 FunAudioLLM，Apache 2.0，本地离线可商用）
# 模型：CosyVoice2-0.5B（ModelScope: iic/CosyVoice2-0.5B，~1.5GB）
# 安装：pip install git+https://github.com/FunAudioLLM/CosyVoice.git
#       需要 third_party/Matcha-TTS 加入 sys.path（代码内处理）
# 参考：cosyvoice.cli.cosyvoice.CosyVoice2 → inference_sft / inference_zero_shot
# 输出采样率：24000（模型固定），再重采样到目标采样率
# ---------------------------------------------------------------------------

# CosyVoice 支持检查（延迟导入，避免启动时加载 torch/依赖）
COSYVOICE_AVAILABLE = False
_cosyvoice_model = None
_cosyvoice_lock = threading.Lock()


def _check_cosyvoice_available() -> bool:
    """检查 CosyVoice 是否可用（延迟检查；cosyvoice 在仓库目录，需先加入 sys.path）"""
    global COSYVOICE_AVAILABLE
    if not COSYVOICE_AVAILABLE:
        try:
            import sys
            from bookroom_audio.utils.config import get_config
            config = get_config()
            repo_root = os.getenv("COSYVOICE_ROOT", os.path.join(config.cache.cache_dir, "CosyVoice"))
            if os.path.isdir(repo_root) and repo_root not in sys.path:
                sys.path.append(repo_root)
            import cosyvoice  # noqa: F401
            COSYVOICE_AVAILABLE = True
        except ImportError:
            COSYVOICE_AVAILABLE = False
    return COSYVOICE_AVAILABLE


def _cosyvoice_model_dir() -> str:
    """CosyVoice2-0.5B 模型目录（环境变量可覆盖，默认在 CosyVoice 仓库 pretrained_models 下）"""
    from bookroom_audio.utils.config import get_config
    config = get_config()
    env_dir = os.getenv("COSYVOICE_MODEL_DIR")
    if env_dir:
        return env_dir
    # 优先仓库内 pretrained_models/CosyVoice2-0.5B
    repo_root = os.getenv("COSYVOICE_ROOT", os.path.join(config.cache.cache_dir, "CosyVoice"))
    return os.path.join(repo_root, "pretrained_models", "CosyVoice2-0.5B")


def _get_cosyvoice_model():
    """获取或加载 CosyVoice2 模型（线程安全懒加载）"""
    global _cosyvoice_model
    if _cosyvoice_model is None:
        with _cosyvoice_lock:
            if _cosyvoice_model is None:
                logger.info("Loading CosyVoice2 model...")
                try:
                    import sys
                    from bookroom_audio.utils.config import get_config
                    config = get_config()

                    model_dir = _cosyvoice_model_dir()
                    if not os.path.isdir(model_dir):
                        raise FileNotFoundError(
                            f"CosyVoice2 model not found: {model_dir}. "
                            f"请先下载：git clone https://www.modelscope.cn/iic/CosyVoice2-0.5B.git "
                            f"{model_dir} （约 1.5GB）"
                        )

                    # CosyVoice 无 setup.py，需把仓库根 + third_party/Matcha-TTS 加入 sys.path
                    repo_root = os.getenv("COSYVOICE_ROOT", os.path.join(config.cache.cache_dir, "CosyVoice"))
                    if os.path.isdir(repo_root) and repo_root not in sys.path:
                        sys.path.append(repo_root)
                    matcha_tts = os.path.join(repo_root, "third_party", "Matcha-TTS")
                    if os.path.isdir(matcha_tts) and matcha_tts not in sys.path:
                        sys.path.append(matcha_tts)

                    from cosyvoice.cli.cosyvoice import CosyVoice2

                    # 设备：config.model.device（默认 auto）；真实设备由 CosyVoice 自行解析（cuda/cpu）
                    device = config.model.device
                    # fp16 仅在真实 CUDA 设备上启用。
                    # 注意：旧判断 `device != "cpu"` 在 DEVICE=auto（非 "cpu" 字符串）且机器无 GPU 时会误开 fp16，
                    # 导致模型以 half 权重在 CPU 上推理——极慢（rtf 10+）且易触发数值异常。
                    import torch as _torch
                    use_fp16 = _torch.cuda.is_available() and (device != "cpu" or os.getenv("COSYVOICE_FP16", "0") == "1")
                    logger.info(f"CosyVoice2 loading from {model_dir} (device={device}, fp16={use_fp16})...")
                    _cosyvoice_model = CosyVoice2(
                        model_dir,
                        load_jit=False,
                        load_trt=False,
                        fp16=use_fp16,
                    )
                    logger.info("CosyVoice2 model loaded successfully!")
                except Exception as e:
                    logger.error(f"Error loading CosyVoice2 model: {e}", exc_info=True)
                    _cosyvoice_model = None
    return _cosyvoice_model


def _get_cosyvoice_status() -> dict:
    """获取 CosyVoice2 状态信息"""
    model_dir = _cosyvoice_model_dir()
    return {
        "available": _check_cosyvoice_available(),
        "model_loaded": _cosyvoice_model is not None,
        "model_dir": model_dir,
        "model_exists": os.path.isdir(model_dir),
        "description": "CosyVoice 2 - 阿里 FunAudioLLM 开源 TTS（Apache 2.0 可商用），中文韵律开源第一梯队",
        "features": [
            "中文/英文/粤语/四川话等预置音色",
            "3 秒零样本音色克隆（inference_zero_shot）",
            "流式合成（首包 ~1.5s）",
            "本地离线运行，Apache 2.0 可商用",
        ],
    }


def generate_audio_cosyvoice(
    text: str,
    voice: Optional[str] = None,
    target_sample_rate: int = 16000,
    emotion: str = "neutral",
) -> bytes:
    """
    使用 CosyVoice 2 生成音频（SFT 预置音色模式）。
    
    Args:
        text: 要转换的文本
        voice: 预置音色名（如 '中文女' / '中文男'，见 COSYVOICE_VOICES）
        target_sample_rate: 目标采样率
        emotion: 保留参数（CosyVoice2 支持指令式情感，此处不强制）

    Returns:
        WAV格式的音频数据
    """
    import numpy as np
    from bookroom_audio.api.routers.tts.constants import COSYVOICE_VOICES

    model = _get_cosyvoice_model()
    if model is None:
        raise Exception(
            "CosyVoice2 model not loaded. 请确认已安装 cosyvoice 包并下载模型 "
            "（见 MODEL_DOWNLOAD.md / COSYVOICE_MODEL_DIR 环境变量）"
        )

    # 音色选择：默认中文女声；无效音色回退第一个可用
    spk_id = voice if voice and voice in COSYVOICE_VOICES else COSYVOICE_VOICES[0]
    # 若模型另有 spk2info 音色表，尝试按名称匹配，失败回退默认
    try:
        spks = model.list_available_spks() if hasattr(model, "list_available_spks") else []
        if spks and spk_id not in spks:
            spk_id = spks[0]
    except Exception:
        pass

    # SFT 推理（非流式，返回 chunks）
    chunks = []
    for out in model.inference_sft(tts_text=text, spk_id=spk_id, stream=False):
        chunks.append(out["tts_speech"])

    if not chunks:
        raise Exception("CosyVoice2 generated no audio chunks")

    # 拼接 → float32 [-1,1] → int16 → WAV（模型固定 24000Hz）
    import torch
    wav = torch.cat(chunks, dim=1)
    wav_np = wav.numpy().squeeze()
    if wav_np.ndim > 1:
        wav_np = wav_np.mean(axis=0)
    wav_int16 = (np.clip(wav_np, -1.0, 1.0) * 32767).astype(np.int16)

    audio = AudioSegment(
        data=wav_int16.tobytes(),
        sample_width=2,
        frame_rate=getattr(model, "sample_rate", 24000),
        channels=1,
    )
    audio = audio.set_frame_rate(target_sample_rate)

    out_buf = io.BytesIO()
    audio.export(out_buf, format="wav")
    return out_buf.getvalue()


# ================================================================
# CosyVoice 3（Fun-CosyVoice3-0.5B-2512，Apache 2.0 可商用）
# 注意：CosyVoice3 模型包不含 spk2info.pt（无预置音色），官方仅支持
# zero_shot / cross_lingual 音色克隆 —— 必须提供参考音频（reference_audio）。
# 缺少参考音频时显式报错，绝不静默回退到其它引擎/模型（避免产出错误语音）。
# 引擎名：cosyvoice3。不参与 auto 自动选择（auto 无法提供参考音频）。
# ================================================================
_cosyvoice3_model = None
_cosyvoice3_lock = threading.Lock()
_COSYVOICE3_DEFAULT_PROMPT = "You are a helpful assistant.<|endofprompt|>"


def _cosyvoice3_model_dir() -> str:
    """CosyVoice3 模型目录（环境变量 COSYVOICE3_MODEL_DIR 可覆盖）"""
    env_dir = os.getenv("COSYVOICE3_MODEL_DIR")
    if env_dir:
        return env_dir
    from bookroom_audio.utils.config import get_config
    config = get_config()
    return os.path.join(config.cache.cache_dir, "cosyvoice-ms", "FunAudioLLM", "Fun-CosyVoice3-0___5B-2512")


def _check_cosyvoice3_available() -> bool:
    """检查 CosyVoice3 是否可用（模型目录 + cosyvoice3.yaml + cosyvoice 可导入）"""
    model_dir = _cosyvoice3_model_dir()
    if not os.path.isdir(model_dir) or not os.path.exists(os.path.join(model_dir, "cosyvoice3.yaml")):
        return False
    try:
        import sys
        from bookroom_audio.utils.config import get_config
        config = get_config()
        repo_root = os.getenv("COSYVOICE_ROOT", os.path.join(config.cache.cache_dir, "CosyVoice"))
        if os.path.isdir(repo_root) and repo_root not in sys.path:
            sys.path.append(repo_root)
        import cosyvoice  # noqa: F401
        return True
    except ImportError:
        return False


def _get_cosyvoice3_model():
    """获取或加载 CosyVoice3 模型（线程安全懒加载）"""
    global _cosyvoice3_model
    if _cosyvoice3_model is None:
        with _cosyvoice3_lock:
            if _cosyvoice3_model is None:
                logger.info("Loading CosyVoice3 model...")
                try:
                    import sys
                    from bookroom_audio.utils.config import get_config
                    config = get_config()
                    repo_root = os.getenv("COSYVOICE_ROOT", os.path.join(config.cache.cache_dir, "CosyVoice"))
                    if os.path.isdir(repo_root) and repo_root not in sys.path:
                        sys.path.append(repo_root)
                    matcha_tts = os.path.join(repo_root, "third_party", "Matcha-TTS")
                    if os.path.isdir(matcha_tts) and matcha_tts not in sys.path:
                        sys.path.append(matcha_tts)

                    from cosyvoice.cli.cosyvoice import CosyVoice3

                    model_dir = _cosyvoice3_model_dir()
                    # fp16 仅在真实 CUDA 设备上启用（与 CosyVoice2 保持一致，CPU 上禁用）
                    import torch as _torch
                    use_fp16 = _torch.cuda.is_available() and os.getenv("COSYVOICE_FP16", "0") == "1"
                    logger.info(f"CosyVoice3 loading from {model_dir} (fp16={use_fp16})...")
                    _cosyvoice3_model = CosyVoice3(model_dir, fp16=use_fp16)
                    logger.info("CosyVoice3 model loaded successfully!")
                except Exception as e:
                    logger.error(f"Error loading CosyVoice3 model: {e}", exc_info=True)
                    _cosyvoice3_model = None
    return _cosyvoice3_model


def _get_cosyvoice3_status() -> dict:
    """获取 CosyVoice3 状态信息"""
    model_dir = _cosyvoice3_model_dir()
    return {
        "available": _check_cosyvoice3_available(),
        "model_loaded": _cosyvoice3_model is not None,
        "model_dir": model_dir,
        "model_exists": os.path.isdir(model_dir),
        "description": "CosyVoice 3 - 阿里通义 Fun-CosyVoice3-0.5B-2512（Apache 2.0 可商用），9 语言 + 18 方言 zero-shot 克隆",
        "features": [
            "zero_shot 音色克隆：需提供参考音频（3~10s）",
            "9 种语言 + 18 种汉语方言",
            "发音修补 / 指令控制情感语速",
            "无预置音色（官方仅 zero_shot 模式）",
        ],
        "requires_reference_audio": True,
    }


def generate_audio_cosyvoice3(
    text: str,
    reference_audio: Optional[str] = None,  # base64 编码的 WAV（说话人音色样本）
    reference_text: Optional[str] = None,   # 参考音频对应文本（prompt_text，可选）
    target_sample_rate: int = 16000,
    emotion: str = "neutral",
) -> bytes:
    """
    使用 CosyVoice 3 生成音频（zero_shot 音色克隆模式）。

    Args:
        text: 要转换的文本（tts_text）
        reference_audio: 参考音频（base64 编码 WAV，3~10s 说话人样本），必填
        reference_text: 参考音频对应文本，可选；默认官方 system prompt。
            会自动确保含 <|endofprompt|>（CosyVoice3 LLM 硬性要求，缺失会 assert 崩溃）。
        target_sample_rate: 目标采样率
        emotion: 保留参数

    Returns:
        WAV 格式音频数据

    Raises:
        ValueError: 缺少参考音频 / base64 非法时显式报错（不静默回退）
        Exception: 模型未加载 / 无输出 / 推理失败（显式报错，不兜底）
    """
    import base64
    import numpy as np
    import tempfile

    if not reference_audio:
        raise ValueError(
            "CosyVoice3 引擎需要参考音频（reference_audio，base64 编码 WAV，3~10s 说话人样本）。"
            "CosyVoice3 无预置音色，仅支持 zero_shot 音色克隆。"
        )

    model = _get_cosyvoice3_model()
    if model is None:
        raise Exception(
            "CosyVoice3 model not loaded. 请确认已下载 Fun-CosyVoice3-0.5B-2512 "
            "（见 MODEL_DOWNLOAD.md / COSYVOICE3_MODEL_DIR 环境变量）"
        )

    # 参考文本：默认官方 system prompt；用户提供时确保含 <|endofprompt|>
    prompt_text = reference_text.strip() if reference_text and reference_text.strip() else _COSYVOICE3_DEFAULT_PROMPT
    if "<|endofprompt|>" not in prompt_text:
        prompt_text = prompt_text + "<|endofprompt|>"

    # base64 -> 临时 wav
    try:
        wav_bytes = base64.b64decode(reference_audio)
    except Exception as e:
        raise ValueError(f"reference_audio base64 解码失败: {e}")
    if len(wav_bytes) == 0:
        raise ValueError("reference_audio 为空")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp_wav = f.name
    try:
        chunks = []
        for out in model.inference_zero_shot(tts_text=text, prompt_text=prompt_text, prompt_wav=tmp_wav, stream=False):
            chunks.append(out["tts_speech"])
    finally:
        os.unlink(tmp_wav)

    if not chunks:
        raise Exception("CosyVoice3 generated no audio chunks")

    import torch
    wav = torch.cat(chunks, dim=1)
    wav_np = wav.numpy().squeeze()
    if wav_np.ndim > 1:
        wav_np = wav_np.mean(axis=0)
    wav_int16 = (np.clip(wav_np, -1.0, 1.0) * 32767).astype(np.int16)

    audio = AudioSegment(
        data=wav_int16.tobytes(),
        sample_width=2,
        frame_rate=getattr(model, "sample_rate", 24000),
        channels=1,
    )
    audio = audio.set_frame_rate(target_sample_rate)

    out_buf = io.BytesIO()
    audio.export(out_buf, format="wav")
    return out_buf.getvalue()


# ================================================================
# Kokoro-82M v1.0（hexgrad，Apache 2.0，代码+权重均可商用）
# text-only 预置音色（54 个，含中文 8 个），82M 极轻量，CPU 可跑。
# 定位：替代 ChatTTS 的可商用本地 TTS。权重经 HF 镜像预下载到
# KOKORO_HF_HOME（.cache/kokoro-hf，HF 缓存结构），加载时临时接管 HF_HOME/
# HF_ENDPOINT（项目 HF_ENDPOINT 指向 modelscope，会破坏 kokoro 的 HF 下载）。
# 引擎名：kokoro。失败显式报错，绝不静默兜底到其它引擎。
# ================================================================
_kokoro_pipelines: dict = {}   # lang_code -> KPipeline
_kokoro_lock = threading.Lock()


def _kokoro_hf_home() -> str:
    """Kokoro 权重 HF 缓存目录（默认 .cache/kokoro-hf，随 .cache 卷同步）"""
    env_dir = os.getenv("KOKORO_HF_HOME")
    if env_dir:
        return env_dir
    from bookroom_audio.utils.config import get_config
    config = get_config()
    return os.path.join(config.cache.cache_dir, "kokoro-hf")


def _check_kokoro_available() -> bool:
    """检查 Kokoro 是否可用（kokoro 包可导入即可；权重首次运行时自动下载）"""
    try:
        import kokoro  # noqa: F401
        return True
    except ImportError:
        return False


def _kokoro_repo_id(lang_code: str) -> str:
    """按语言选择 Kokoro 权重仓库：中文用 v1.1-zh 优化版（hexgrad/Kokoro-82M-v1.1-zh），
    其余语言用 v1.0 标准版（hexgrad/Kokoro-82M）。"""
    if lang_code == "z":
        return os.getenv("KOKORO_REPO_ID_ZH", "hexgrad/Kokoro-82M-v1.1-zh")
    return os.getenv("KOKORO_REPO_ID", "hexgrad/Kokoro-82M")


def _get_kokoro_pipeline(lang_code: str):
    """获取/加载指定语言的 Kokoro pipeline（线程安全懒加载；临时接管 HF 环境变量）"""
    if lang_code not in _kokoro_pipelines:
        with _kokoro_lock:
            if lang_code not in _kokoro_pipelines:
                logger.info(f"Loading Kokoro pipeline (lang={lang_code}, repo={_kokoro_repo_id(lang_code)})...")
                # kokoro 权重走 HF 下载；项目 HF_ENDPOINT 指向 modelscope 会破坏下载，
                # 此处临时接管，加载完成后恢复。
                saved = {k: os.environ.get(k) for k in ("HF_ENDPOINT", "HF_HOME")}
                os.environ["HF_ENDPOINT"] = os.getenv("KOKORO_HF_ENDPOINT", "https://hf-mirror.com")
                os.environ["HF_HOME"] = _kokoro_hf_home()
                try:
                    from kokoro import KPipeline
                    _kokoro_pipelines[lang_code] = KPipeline(
                        lang_code=lang_code,
                        repo_id=_kokoro_repo_id(lang_code),
                    )
                    logger.info(f"Kokoro pipeline loaded (lang={lang_code})")
                except Exception:
                    logger.exception(f"Kokoro pipeline load failed (lang={lang_code})")
                    raise
                finally:
                    for k, v in saved.items():
                        if v is None:
                            os.environ.pop(k, None)
                        else:
                            os.environ[k] = v
    return _kokoro_pipelines[lang_code]


def _kokoro_status() -> dict:
    """获取 Kokoro 状态信息"""
    return {
        "available": _check_kokoro_available(),
        "model_loaded": len(_kokoro_pipelines) > 0,
        "weights_home": _kokoro_hf_home(),
        "description": "Kokoro-82M - hexgrad 开源 TTS（Apache 2.0 可商用），82M 极轻量；中文用 v1.1-zh 优化版",
        "features": [
            "text-only 预置音色（无需参考音频）",
            "Apache 2.0 可商用（代码+权重）",
            "极轻量：CPU 可跑（约 6 倍实时）",
            "中文 v1.1-zh 优化版 + 英/日/西/法/印/意/葡",
        ],
    }


def _kokoro_lang_from_voice(voice: str) -> str:
    """从音色名推断语言代码：zf_xiaobei → 'z'（中文）、af_bella → 'a'（美英）等。
    音色命名规范 {lang}{gender}_{name}，首字符即 LANG_CODES 的 key。"""
    v = (voice or "").strip().split(",")[0]
    return v[0] if len(v) >= 2 else "z"


def _kokoro_timestamps(phonemes: str, pred_dur, sample_rate: int = 24000) -> list:
    """Kokoro pred_dur（每音素帧数）→ 词级时间戳（毫秒）。

    对齐官方 KPipeline.join_timestamps 的数学（半帧计数，MAGIC_DIVISOR=80，1 pred_dur 帧=600
    采样点@24kHz）：pred_dur = [<bos>, ...逐字符对应 phonemes(含空格)..., <eos>]，
    len(pred_dur) == len(phonemes) + 2。空格"半切"：前半归前词尾、后半给后词头。
    无 tokens（中文 misaki）时按 phonemes 逐字符聚合，输出 [{text, start_ms, end_ms}]。

    Args:
        phonemes: Kokoro 音素字符串（Result.phonemes）
        pred_dur: 音素时长帧数（Result.pred_dur，torch.LongTensor / ndarray / list）
        sample_rate: Kokoro 输出采样率（24000，pred_dur 帧单位即 1/600s）

    Returns:
        词级时间戳列表：[{"text": str, "start_ms": float, "end_ms": float}, ...]
    """
    import numpy as np

    pd = np.asarray(pred_dur, dtype=np.float64)
    if len(pd) < 3:  # 至少 <bos>, 一个音素, <eos>
        return []

    DIV = 80.0  # 半帧/秒（1 pred_dur 帧 = 600 samples @24kHz = 2 half-frames）
    words = []
    # 半帧游标：left=词起点，right=词尾（含空格半切），初始对齐官方 bos 偏移
    left = right = 2.0 * max(0.0, pd[0] - 3.0)
    i = 1
    cur = None
    for ch in phonemes:
        if i >= len(pd) - 1:  # 保留最后一个 <eos>
            break
        if ch == " ":
            if cur is not None:
                cur["end_ms"] = round((left / DIV) * 1000.0, 2)
                words.append(cur)
                cur = None
            # 空格半切：前半已计入前词 end（left），后半作为后词起点
            left = right + pd[i]
            right = left + pd[i]
            i += 1
            continue
        if cur is None:
            cur = {"text": ch, "start_ms": round((right / DIV) * 1000.0, 2), "end_ms": 0.0}
        else:
            cur["text"] += ch
        left = right + 2.0 * pd[i]
        right = left
        cur["end_ms"] = round((left / DIV) * 1000.0, 2)
        i += 1
    if cur is not None:
        words.append(cur)
    return words


def generate_audio_kokoro(
    text: str,
    voice: Optional[str] = None,
    target_sample_rate: int = 16000,
    emotion: str = "neutral",
    return_timestamps: bool = False,
):
    """
    使用 Kokoro 生成音频（text-only 预置音色，Apache 2.0 可商用）。

    Args:
        text: 要转换的文本
        voice: 预置音色名。中文（v1.1-zh）用 zf_001~zf_099（女）/ zm_009~zm_100（男），
               如 'zf_001'；英文用 af_maple 等。支持逗号分隔多音色平均。
               默认中文女声 zf_001。
        target_sample_rate: 目标采样率
        emotion: 保留参数
        return_timestamps: True 时返回 (wav_bytes, words)——words 为字级时间戳
               [{text, start_ms, end_ms}]（毫秒，对齐 24kHz 原始音频；重采样后时长不变仍有效），
               来自模型原生 pred_dur 音素时长累计，用于 viseme 口型驱动；False（默认）返回 bytes。

    Returns:
        return_timestamps=False: WAV 格式音频数据
        return_timestamps=True: (WAV bytes, words list)

    Raises:
        Exception: 模型未加载 / 无输出 / 音色不存在（显式报错，不兜底）
    """
    import numpy as np

    voice = (voice or "zf_001").strip()
    lang_code = _kokoro_lang_from_voice(voice)

    pipeline = _get_kokoro_pipeline(lang_code)  # 失败向上抛（路由层转 500）

    chunks = []
    words = []
    sample_rate = 24000
    audio_offset_ms = 0.0
    for result in pipeline(text, voice=voice, speed=1.0):
        chunks.append(result.audio)
        if return_timestamps:
            pred_dur = getattr(result, "pred_dur", None)
            phonemes = getattr(result, "phonemes", None)
            if pred_dur is not None and phonemes:
                for w in _kokoro_timestamps(phonemes, pred_dur, sample_rate):
                    w["start_ms"] = round(w["start_ms"] + audio_offset_ms, 2)
                    w["end_ms"] = round(w["end_ms"] + audio_offset_ms, 2)
                    words.append(w)
        audio_offset_ms += (len(result.audio) / sample_rate) * 1000.0

    if not chunks:
        raise Exception("Kokoro generated no audio chunks")

    wav_np = np.concatenate(chunks)
    wav_int16 = (np.clip(wav_np, -1.0, 1.0) * 32767).astype(np.int16)

    audio = AudioSegment(
        data=wav_int16.tobytes(),
        sample_width=2,
        frame_rate=sample_rate,
        channels=1,
    )
    audio = audio.set_frame_rate(target_sample_rate)

    out_buf = io.BytesIO()
    audio.export(out_buf, format="wav")
    if return_timestamps:
        return out_buf.getvalue(), words
    return out_buf.getvalue()