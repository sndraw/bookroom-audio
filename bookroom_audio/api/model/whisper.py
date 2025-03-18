import asyncio
from datetime import datetime
from typing import Any
from ascii_colors import ASCIIColors
from faster_whisper import WhisperModel
from bookroom_audio.api.utils import (
    logger,
    parse_keep_alive,
)

model_client = None
model_last_loaded = None

# 异步加载模型，并更新加载/调用时间，便于监控模型加载情况
async def load_model_task(args: Any, params: dict, task: str):
    global model_client
    global model_last_loaded
    model = params.get("model", args.model)
    if model_client is None:
        ASCIIColors.blue("\nModel is being loaded...\n")
        model_last_loaded = datetime.now()
        # 加载Whisper模型,可根据实际情况选择模型大小和设备
        model_client = WhisperModel(
            model_size_or_path=model,
            device=args.device,
            compute_type=args.compute_type,
            num_workers=args.num_workers,
            download_root=args.download_root,
        )
        ASCIIColors.green("\nModel has been loaded\n")
        ASCIIColors.white("    ├─ model_size_or_path: ", end="")
        ASCIIColors.yellow(f"{model}")
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
        # 获取上传的音频文件
    audio_content = params.get("file")
    language = params.get("language", "en")
    # 这里需要将audio_content转换成适合Whisper模型输入的格式，
    ASCIIColors.blue("\nTranscribing audio...\n")
    ASCIIColors.white("    ├─ task: ", end="")
    ASCIIColors.yellow(f"{task}")
    ASCIIColors.white("    ├─ language: ", end="")
    ASCIIColors.yellow(f"{language}")
    result, _ = model_client.transcribe(
        audio=audio_content, task=task, language=language
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
            model_client=None
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
            if model_last_loaded and (datetime.now() - model_last_loaded).total_seconds() > model_keep_alive:
                ASCIIColors.blue("\nModel has been loaded for too long, unloading...\n")
                await cleanup_model()
        except asyncio.CancelledError:
            print("Task was cancelled")
            break  # 任务被取消后退出循环

        except Exception as e:
            print(f"An error occurred: {e}")
            break  # 出现错误后退出循环
