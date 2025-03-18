import asyncio
from contextlib import asynccontextmanager
import os
from fastapi import Depends, FastAPI, HTTPException, Request
from dotenv import load_dotenv, find_dotenv
from fastapi.middleware.cors import CORSMiddleware
from ascii_colors import ASCIIColors
from bookroom_audio.api.model.whisper import cleanup_model, load_model_task, run_model_loaded_process
from bookroom_audio.api.utils import (
    get_api_key_dependency,
    get_cors_origins,
    parse_args,
    logger
)
from bookroom_audio.api import __api_name__, __api_description__, __api_version__

# 确保环境变量已加载
load_dotenv(find_dotenv(), override=True)


# 创建一个全局锁
global_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Store background tasks
    app.state.background_tasks = set()
    try:
        async with global_lock:
            task = asyncio.create_task(run_model_loaded_process(args))
            task.add_done_callback(app.state.background_tasks.discard)
            logger.info(f"Process {os.getpid()} auto scan task started at startup.")
        ASCIIColors.green("\nServer is ready to accept connections! 🚀\n")
        yield
    finally:
        async with global_lock:
            # 取消所有后台任务
            for task in app.state.background_tasks:
                task.cancel()
        ASCIIColors.green("\nServer is shutting down! 🛑\n")
        # 在应用关闭时清理模型
        await cleanup_model()


args = parse_args()

app = FastAPI(
    title=__api_name__,
    description=__api_description__,
    version=__api_version__,
    openapi_url="/openapi.json",  # Explicitly set OpenAPI schema URL
    docs_url="/docs",  # Explicitly set docs URL
    redoc_url="/redoc",  # Explicitly set redoc URL
    openapi_tags=[{"name": "api"}],
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key = args.key
# Create the optional API key dependency
optional_api_key = get_api_key_dependency(api_key)


@app.post("/v1/audio/translations", dependencies=[Depends(optional_api_key)])
async def translate_audio(request: Request):
    try:
        data = await request.form()
        result = await load_model_task(args, data, task="translate")
        return result
    except asyncio.CancelledError:
        return {"error": "Request cancelled"}, 499  # 使用499状态码表示客户端中止请求
    except Exception as e:
        logger.error(f"Error during transcriptions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/audio/transcriptions", dependencies=[Depends(optional_api_key)])
async def transcribe_audio(request: Request):
    try:
        data = await request.form()
        result = await load_model_task(args, data, task="transcribe")
        return result
    except asyncio.CancelledError:
        return {"error": "Request cancelled"}, 499  # 使用499状态码表示客户端中止请求
    except Exception as e:
        logger.error(f"Error during transcriptions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def main():
    import uvicorn
    uvicorn.run(
        "bookroom_audio.api.app:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
    )


# 如果直接运行此脚本，则启动Uvicorn服务器
if __name__ == "__main__":
    main()
