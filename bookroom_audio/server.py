import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from urllib.parse import unquote
import os
from fastapi import FastAPI, HTTPException, Request, Response
from dotenv import load_dotenv, find_dotenv
from fastapi.middleware.cors import CORSMiddleware
from ascii_colors import ASCIIColors
from fastapi.responses import JSONResponse
import uvicorn

from bookroom_audio.models.whisper import (
    cleanup_model as cleanup_whisper_model,
    run_model_loaded_process,
)
from bookroom_audio.api.routers.server_routes import create_server_routes
from bookroom_audio.api.routers.transcribe_routes import create_transcribe_routes
from bookroom_audio.api.routers.transcribe_streaming import create_streaming_transcribe_routes
from bookroom_audio.api.routers.tts_routes import create_tts_routes
from bookroom_audio.api.routers.video_routes import create_video_routes
from bookroom_audio.api.routers.image_routes import create_image_routes
from bookroom_audio.api.routers.openai_routes import create_openai_routes
from bookroom_audio.utils.utils_api import (
    get_cors_origins,
    parse_args,
    logger,
)
from bookroom_audio.api import __api_name__, __api_description__, __api_version__

class _ProxyPathNormalizeMiddleware:
    """代理绝对 URI 路径归一化。

    某些 HTTP 代理（如开发沙箱代理）会把请求行中的绝对 URI URL 编码后转发
    （POST http%3A//host%3Aport/v1/...），FastAPI 严格路径匹配会 404。
    在 ASGI 层解码并剥离 scheme/host，恢复为 /v1/... 再交给路由。
    仅影响以 http:// / https:// 开头的畸形路径，正常请求不受影响。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path", "") or ""
            decoded = unquote(path)
            if decoded.startswith("http://") or decoded.startswith("https://"):
                from urllib.parse import urlsplit

                parsed = urlsplit(decoded)
                scope["path"] = parsed.path or "/"
                scope["raw_path"] = scope["path"].encode("utf-8", "surrogateescape")
                scope["query_string"] = parsed.query.encode("utf-8")
        await self.app(scope, receive, send)


# 确保环境变量已加载
load_dotenv(find_dotenv(), override=True)

# 创建一个全局锁
global_lock = asyncio.Lock()

# 全局关闭标志
shutdown_event = asyncio.Event()

def create_app(args) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan context manager for startup and shutdown events"""
        # Store background tasks
        app.state.background_tasks = set()
        
        # 设置信号处理器
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            async with global_lock:
                task = asyncio.create_task(run_model_loaded_process(args))
                task.add_done_callback(app.state.background_tasks.discard)
                logger.info(f"Process {os.getpid()} auto scan task started at startup.")
            ASCIIColors.green("\nServer is ready to accept connections! 🚀\n")
            yield
        finally:
            ASCIIColors.yellow("\nInitiating graceful shutdown...\n")
            
            # 取消所有后台任务
            async with global_lock:
                for task in app.state.background_tasks:
                    if not task.done():
                        task.cancel()
                        try:
                            await asyncio.wait_for(task, timeout=2.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError):
                            pass
            
            ASCIIColors.green("\nServer is shutting down! 🛑\n")
            
            # 在应用关闭时清理模型
            try:
                await cleanup_whisper_model()
            except Exception as e:
                logger.error(f"Error during Whisper model cleanup: {e}")
            
            #清理VL模型
            try:
                from bookroom_audio.models.qwen_vl import cleanup_model as cleanup_vl_model
                await cleanup_vl_model()
            except Exception as e:
                logger.error(f"Error during VL model cleanup: {e}")
            
            # 清理流式 ASR 后端
            try:
                from bookroom_audio.api.routers.transcribe_streaming.engines import (
                    cleanup_all_backends,
                )
                await cleanup_all_backends()
            except Exception as e:
                logger.error(f"Error during streaming ASR cleanup: {e}")
            
            ASCIIColors.green("\nShutdown completed gracefully. Goodbye! 👋\n")

    openapi_tags=[
        {
            "name":"server",
            "description": "Server management routes."
        },
        {
            "name": "transcribe",
            "description": "Speech Recognition (ASR) API routes. Supports Qwen3-ASR and Whisper models."
        },
        {
            "name": "streaming-transcribe",
            "description": "Real-time streaming Speech Recognition (ASR) via WebSocket. Supports FunASR and SenseVoice engines."
        },
        {
            "name": "tts",
            "description": "Text-to-Speech (TTS) API routes. Supports ChatTTS and MeloTTS models."
        },
        {
            "name": "video",
            "description": "Video content analysis and moderation API routes. Supports Qwen3-VL models."
        },
        {
            "name": "image",
            "description": "Image content analysis and moderation API routes. Supports Qwen3-VL models."
        },
        {
            "name": "openai-compatible",
            "description": "OpenAI-compatible API routes. Supports audio transcription, translation, speech synthesis, video analysis, and image analysis."
        },
    ]
    app = FastAPI(
        title=__api_name__,
        description=__api_description__,
        version=__api_version__,
        openapi_url="/openapi.json",  # Explicitly set OpenAPI schema URL
        docs_url="/docs",  # Explicitly set docs URL
        redoc_url="/redoc",  # Explicitly set redoc URL
        lifespan=lifespan,
        openapi_tags=[*openapi_tags],
        contact={"name": "sndraw", "url": "https://github.com/sndraw"},
        license_info={
            "name": "Apache 2.0",
            "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
        },
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if args.server.debug:
        app.debug = True

    api_key = args.server.api_key


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
    app.include_router(create_streaming_transcribe_routes(args, api_key))
    app.include_router(create_server_routes(args, api_key))
    app.include_router(create_tts_routes(args, api_key))
    app.include_router(create_video_routes(args, api_key))
    app.include_router(create_image_routes(args, api_key))
    app.include_router(create_openai_routes(args, api_key))

    # 代理绝对 URI 路径归一化（沙箱代理会把绝对 URI 编码成 http%3A//...，FastAPI 会 404）
    app = _ProxyPathNormalizeMiddleware(app)
    return app

args = parse_args()

# 打印配置摘要
from bookroom_audio.utils.config import print_config_summary
print_config_summary()

app = create_app(args)

def main():
    
    # Start Uvicorn in single process mode
    uvicorn_config = {
        "host": args.server.host,
        "port": args.server.port,
    }
    if args.server.reload:
        uvicorn_config["reload"] = True
        
    if args.server.workers > 1:
        uvicorn_config["workers"] = args.server.workers
        
    if args.server.ssl:
        uvicorn_config.update(
            {
                "ssl_certfile": args.server.ssl_certfile,
                "ssl_keyfile": args.server.ssl_keyfile,
            }
        )

    if args.server.debug:
        ASCIIColors.yellow("\nServer is running in debug mode! \n")
           
    uvicorn.run("bookroom_audio.server:app", **uvicorn_config)

if __name__ == "__main__":
    main()