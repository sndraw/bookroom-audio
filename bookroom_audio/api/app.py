import asyncio
from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, HTTPException, Request, Response
from dotenv import load_dotenv, find_dotenv
from fastapi.middleware.cors import CORSMiddleware
from ascii_colors import ASCIIColors
from fastapi.responses import JSONResponse
from bookroom_audio.api.model.whisper import (
    cleanup_model,
    run_model_loaded_process,
)
from bookroom_audio.api.routers.server_routes import create_server_routes
from bookroom_audio.api.routers.transcribe_routes import create_transcribe_routes
from bookroom_audio.api.utils import (
    get_cors_origins,
    parse_args,
    logger,
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

if args.debug:
    app.debug = True

api_key = args.key


# 自定义错误处理程序
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    headers = {}
    if exc.headers is not None:
        headers = {**exc.headers}
    return JSONResponse(
        status_code=exc.status_code,
        headers={
            **headers,
        },
        content={
            "error": {
                "code": None,
                "message": exc.detail,
                "pram": None,
                "type": "server_error",
            }
        },
    )


app.include_router(create_transcribe_routes(args, api_key))
app.include_router(create_server_routes(args, api_key))


def main():
    import uvicorn
    if app.debug:
        ASCIIColors.yellow("\nServer is running in debug mode! \n")

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
