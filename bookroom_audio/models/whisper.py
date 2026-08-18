import asyncio
from datetime import datetime
from typing import Any, Iterable
from ascii_colors import ASCIIColors
from faster_whisper import WhisperModel
from faster_whisper.transcribe import Segment
import os

from bookroom_audio.utils.utils_api import (
    logger,
    parse_keep_alive,
)

try:
    from huggingface_hub.errors import LocalEntryNotFoundError
    HAS_HF_HUB = True
except ImportError:
    LocalEntryNotFoundError = Exception
    HAS_HF_HUB = False

model_client = None
model_last_loaded = None

ModelQueryResponse = Iterable[Segment]


def normalize_language_code(language: str | None) -> str | None:
    if not language:
        return None
    
    lang = language.lower().strip()
    
    if len(lang) == 2:
        return lang
        
    if '-' in lang:
        lang = lang.split('-')[0]
        
    if lang == 'yue':
        return 'yue'
        
    return lang[:2]


def print_model_loading(args: Any, params: dict):
    ASCIIColors.blue("\nModel is being loaded...\n")
    ASCIIColors.white("    ├─ model_size_or_path: ", end="")
    ASCIIColors.yellow(f"{params.get('model_size_or_path')}")
    ASCIIColors.white("    ├─ device: ", end="")
    ASCIIColors.yellow(f"{args.model.device}")
    ASCIIColors.white("    ├─ compute_type: ", end="")
    ASCIIColors.yellow(f"{args.model.compute_type}")
    ASCIIColors.white("    ├─ num_workers: ", end="")
    ASCIIColors.yellow(f"{args.model.num_workers}")
    ASCIIColors.white("    ├─ model_keep_alive: ", end="")
    ASCIIColors.yellow(f"{args.model.model_keep_alive}")
    ASCIIColors.white("    ├─ download_root: ", end="")
    from bookroom_audio.utils.config import get_config
    config = get_config()
    ASCIIColors.yellow(f"{config.cache.cache_dir}")
    ASCIIColors.white("    └─ local_files_only: ", end="")
    ASCIIColors.yellow("True (强制禁用自动下载)")
    

def print_transcribing_audio(params: dict):
    ASCIIColors.blue("\nTranscribing audio...\n")
    ASCIIColors.white("    ├─ model: ", end="")
    ASCIIColors.yellow(f"{params.get('model_size_or_path')}")
    ASCIIColors.white("    ├─ task: ", end="")
    ASCIIColors.yellow(f"{params.get('task')}")
    ASCIIColors.white("    └─ language: ", end="")
    ASCIIColors.yellow(f"{params.get('language')}")


async def load_model_task(args: Any, params: dict):
    global model_client
    global model_last_loaded
    print_transcribing_audio(params)
    if model_client is None:
        print_model_loading(args, params)
        model_last_loaded = datetime.now()
        try:
            from bookroom_audio.utils.config import get_config
            config = get_config()
            
            # 强制使用本地文件模式，禁止自动下载
            # 原因：非官方Whisper模型可能包含广告，必须手动下载官方版本
            model_client = WhisperModel(
                model_size_or_path=params.get("model_size_or_path"),
                device=args.model.device,
                compute_type=args.model.compute_type,
                num_workers=args.model.num_workers,
                download_root=config.cache.cache_dir,
                local_files_only=True,  # 强制本地模式，禁止自动下载
            )
            ASCIIColors.green("\nModel has been loaded\n")
        except LocalEntryNotFoundError as e:
            model_name = params.get("model_size_or_path")
            from bookroom_audio.utils.config import get_config
            config = get_config()
            error_msg = f"""
⚠️  Whisper 模型 '{model_name}' 未在本地缓存中找到！

🔒 安全提示：本系统禁止自动下载 Whisper 模型，
   请手动下载 OpenAI 官方版本以避免非官方版本中的广告。

📥 推荐下载方式（使用阿里 ModelScope）：
   export HF_ENDPOINT=https://www.modelscope.cn
   huggingface-cli download openai/whisper-{model_name} --cache-dir {config.cache.cache_dir}

📥 备选下载方式（官方 Hugging Face）：
   export HF_ENDPOINT=https://huggingface.co
   huggingface-cli download openai/whisper-{model_name} --cache-dir {config.cache.cache_dir}

📁 模型下载后会自动存放在：
   {config.cache.cache_dir}/models--openai--whisper-{model_name}

✅ 支持的官方模型（请确保使用 openai/ 前缀）：
   tiny, tiny.en, base, base.en, small, small.en,
   medium, medium.en, large-v1, large-v2, large-v3, large
   distil-large-v2, distil-large-v3, distil-large-v3.5

❌ 不推荐的非官方模型（可能包含广告）：
   Systran/faster-whisper-* (第三方修改版本)

💡 提示：下载完成后请重启服务器或等待模型自动重载
"""
            ASCIIColors.red(f"\nModel loading failed: {error_msg}")
            raise RuntimeError(error_msg)
        except Exception as e:
            model_name = params.get("model_size_or_path")
            error_msg = f"""
❌ Whisper 模型加载失败: {str(e)}

💡 请确保：
1. 模型文件已完整下载到本地缓存目录
2. 使用的是 OpenAI 官方版本（openai/whisper-*）
3. 模型名称正确

📥 下载命令：
   export HF_ENDPOINT=https://www.modelscope.cn
   huggingface-cli download openai/whisper-{model_name}
"""
            ASCIIColors.red(f"\nModel loading failed: {error_msg}")
            raise RuntimeError(error_msg)


    original_language = params.get("language")
    normalized_language = normalize_language_code(original_language)
    
    if original_language and original_language != normalized_language:
        ASCIIColors.yellow(f"Language code converted: '{original_language}' -> '{normalized_language}'")

    result, _ = await asyncio.to_thread(
        model_client.transcribe,
        audio=params.get("audio"), 
        task=params.get("task"), 
        language=normalized_language,
    )
    model_last_loaded = datetime.now()
    return result


async def cleanup_model():
    global model_client
    global model_last_loaded
    if model_client is not None:
        try:
            ASCIIColors.blue("\nCleaning up model...\n")
            model_client = None
            model_last_loaded = None
        except Exception as e:
            ASCIIColors.red(f"\nError in model cleaning up: {e}\n")
        finally:
            ASCIIColors.green("\nModel has been cleaned up\n")


async def run_model_loaded_process(args: Any):
    global model_last_loaded
    while True:
        model_keep_alive = parse_keep_alive(args.model.model_keep_alive)
        try:
            if model_keep_alive < 0 or model_keep_alive is None:
                break
            await asyncio.sleep(60)
            if (
                model_last_loaded
                and (datetime.now() - model_last_loaded).total_seconds()
                > model_keep_alive
            ):
                ASCIIColors.blue("\nModel has been loaded for too long, unloading...\n")
                await cleanup_model()
        except asyncio.CancelledError:
            print("Task was cancelled")
            break
        except Exception as e:
            print(f"An error occurred: {e}")
            break