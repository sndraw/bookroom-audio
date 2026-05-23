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

# --- 语言代码标准化函数 ---
def normalize_language_code(language: str | None) -> str | None:
    """
    将常见的语言代码转换为 Whisper/faster-whisper 支持的两位代码。
    例如: 'zh-CN' -> 'zh', 'en-US' -> 'en', 'yue' -> 'yue'
    """
    if not language:
        return None
    
    # 转为小写
    lang = language.lower().strip()
    
    # 如果已经是两位代码，直接返回（假设输入合法）
    if len(lang) == 2:
        return lang
        
    # 处理带横杠的代码 (如 zh-CN, en-US)
    if '-' in lang:
        lang = lang.split('-')[0]
        
    # 特殊处理：有些三位代码可能需要映射，但 whisper 主要支持两位。
    # yue (粤语) 是三位但在 whitelist 中，需保留
    if lang == 'yue':
        return 'yue'
        
    # 默认取前两位
    return lang[:2]
def print_model_loading(args: Any, params: dict):
    ASCIIColors.blue("\nModel is being loaded...\n")
    ASCIIColors.white("    ├─ model_size_or_path: ", end="")
    ASCIIColors.yellow(f"{params.get('model_size_or_path')}")
    ASCIIColors.white("    ├─ device: ", end="")
    ASCIIColors.yellow(f"{args.device}")
    ASCIIColors.white("    ├─ compute_type: ", end="")
    ASCIIColors.yellow(f"{args.compute_type}")
    ASCIIColors.white("    ├─ num_workers: ", end="")
    ASCIIColors.yellow(f"{args.num_workers}")
    ASCIIColors.white("    ├─ model_keep_alive: ", end="")
    ASCIIColors.yellow(f"{args.model_keep_alive}")
    ASCIIColors.white("    ├─ download_root: ", end="")
    ASCIIColors.yellow(f"{args.download_root}")
    ASCIIColors.white("    ├─ local_files_only: ", end="")
    ASCIIColors.yellow(f"{args.local_files_only}")
    
def print_transcribing_audio(params: dict):
    ASCIIColors.blue("\nTranscribing audio...\n")
    ASCIIColors.white("    ├─ model: ", end="")
    ASCIIColors.yellow(f"{params.get('model_size_or_path')}")
    ASCIIColors.white("    ├─ task: ", end="")
    ASCIIColors.yellow(f"{params.get('task')}")
    ASCIIColors.white("    ├─ language: ", end="")
    ASCIIColors.yellow(f"{params.get('language')}")

# 异步加载模型，并更新加载/调用时间，便于监控模型加载情况
async def load_model_task(args: Any, params: dict):
    global model_client
    global model_last_loaded
    print_transcribing_audio(params)
    if model_client is None:
        print_model_loading(args, params)
        model_last_loaded = datetime.now()
        # 加载Whisper模型,可根据实际情况选择模型大小和设备
        try:
            model_client = WhisperModel(
                model_size_or_path=params.get("model_size_or_path"),
                device=args.device,
                compute_type=args.compute_type,
                num_workers=args.num_workers,
                download_root=args.download_root,
                local_files_only=bool(args.local_files_only),
            )
            ASCIIColors.green("\nModel has been loaded\n")
        except LocalEntryNotFoundError as e:
            model_name = params.get("model_size_or_path")
            error_msg = f"""
模型 '{model_name}' 未在本地缓存中找到。

请按以下步骤解决：

1. 手动下载模型到本地缓存目录：
   git clone https://huggingface.co/openai/whisper-{model_name} {args.download_root}/openai--whisper-{model_name}

2. 或者设置环境变量允许在线下载：
   LOCAL_FILES_ONLY=false

3. 确认模型名称正确，支持的模型：
   tiny, tiny.en, base, base.en, small, small.en, medium, medium.en, large-v1, large-v2, large-v3, large
   distil-large-v2, distil-large-v3, distil-large-v3.5, distil-medium.en, distil-small.en, large-v3-turbo, turbo
"""
            ASCIIColors.red(f"\nModel loading failed: {error_msg}")
            raise RuntimeError(error_msg)
    

    # --- 在此处标准化语言代码 ---
    original_language = params.get("language")
    normalized_language = normalize_language_code(original_language)
    
    # 如果标准化后的语言与原始不同，可以打印日志方便调试（可选）
    if original_language and original_language != normalized_language:
        ASCIIColors.yellow(f"Language code converted: '{original_language}' -> '{normalized_language}'")

    result, _ = model_client.transcribe(
        audio=params.get("audio"), 
        task=params.get("task"), 
        language=normalized_language, # 使用标准化后的语言代码
    )
    model_last_loaded = datetime.now()
    return result


async def cleanup_model():
    global model_client
    global model_last_loaded
    if model_client is not None:
        try:
            ASCIIColors.blue("\nCleaning up model...\n")
            # 调用清理方法，待实现
            # model_client.cleanup()
            model_client = None
            model_last_loaded = None
        except Exception as e:
            ASCIIColors.red("\n Error in model cleaning up:{e}\n")
        finally:
            ASCIIColors.green("\nModel has been cleaned up\n")


async def run_model_loaded_process(args: Any):
    """Run the model loaded process in a background task"""
    global model_last_loaded
    while True:
        model_keep_alive = parse_keep_alive(args.model_keep_alive)
        try:
            # model_keep_alive 小于0秒，直接退出循环
            if model_keep_alive < 0 or model_keep_alive is None:
                break  # 直接退出循环
            await asyncio.sleep(60)  # 默认每1分钟扫描一次
            # 判定上次加载/调用模型时间是否超过model_keep_alive时间
            if (
                model_last_loaded
                and (datetime.now() - model_last_loaded).total_seconds()
                > model_keep_alive
            ):
                ASCIIColors.blue("\nModel has been loaded for too long, unloading...\n")
                await cleanup_model()
        except asyncio.CancelledError:
            print("Task was cancelled")
            break  # 任务被取消后退出循环

        except Exception as e:
            print(f"An error occurred: {e}")
            break  # 出现错误后退出循环