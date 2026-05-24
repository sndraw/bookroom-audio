import argparse
import logging
import os
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN
from bookroom_audio.api import __api_name__
from bookroom_audio.utils.config import get_config, AppConfig, app_config

logger = logging.getLogger(__api_name__)
# 创建一个 StreamHandler 将日志输出到控制台
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)

# 创建一个格式化器并将其添加到处理器中
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
stream_handler.setFormatter(formatter)
# 将处理器添加到 logger 中
logger.addHandler(stream_handler)


def get_cors_origins():
    """Get allowed origins from environment variable
    Returns a list of allowed origins, defaults to ["*"] if not set
    """
    origins_str = os.getenv("CORS_ORIGINS", "*")
    if origins_str == "*":
        return ["*"]
    return [origin.strip() for origin in origins_str.split(",")]


def parse_args() -> AppConfig:
    """解析命令行参数并返回统一的应用配置"""
    parser = argparse.ArgumentParser(
        description="Transcribe audio using Whisper model."
    )

    # 服务器配置
    parser.add_argument(
        "--key",
        type=str,
        default=None,
        help="API key for authentication. This protects server against unauthorized access",
    )

    parser.add_argument(
        "--debug",
        type=lambda x: x.lower() == "true",
        default=None,
        help="Enable debug mode. Default is False.",
    )

    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host to run the server on (default: 0.0.0.0).",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to run the server on (default: 15231).",
    )

    parser.add_argument(
        "--ssl",
        type=lambda x: x.lower() == "true",
        default=None,
        help="Enable SSL. Default is False.",
    )

    parser.add_argument(
        "--ssl-certfile",
        default=None,
        help="Path to SSL certificate file (required if --ssl is enabled)",
    )

    parser.add_argument(
        "--ssl-keyfile",
        default=None,
        help="Path to SSL private key file (required if --ssl is enabled)",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of workers to use for transcription (default:1).",
    )

    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload the model on every request (default: False).",
    )

    # 模型配置
    parser.add_argument(
        "--engine",
        type=str,
        default=None,
        help="Speech recognition engine to use: whisper or qwen-asr (default: whisper).",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Size or path of the Whisper model to use (default: medium).",
    )

    parser.add_argument(
        "--language",
        type=str,
        default=None,
        help="Size or path of the Whisper model to use (default: en).",
    )

    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Device to run the model on (default: cpu).",
    )

    parser.add_argument(
        "--compute-type",
        type=str,
        default=None,
        help="Compute type for the model (default: int8).",
    )

    parser.add_argument(
        "--model-keep-alive",
        type=str,
        default=None,
        help="How long to keep the model in memory before unloading it (default: 5m).",
    )

    parser.add_argument(
        "--num-workers",
        type=int,
        default=None,
        help="Number workders for the model (default: 1).",
    )

    # 缓存配置
    parser.add_argument(
        "--download-root",
        type=str,
        default=None,
        help="Download workders for the model (default: ./.cache).",
    )

    parser.add_argument(
        "--local-files-only",
        type=lambda x: x.lower() == "true",
        default=None,
        help="Whether to only allow local files (default: True).",
    )

    args = parser.parse_args()
    
    # 从环境变量创建配置
    config = AppConfig.from_env()
    
    # 从命令行参数更新配置
    config.update_from_args(args)
    
    return config


def get_api_key_dependency(api_key: Optional[str]):
    """
    Create an API key dependency for route protection.

    Args:
        api_key (Optional[str]): The API key to validate against.
                                If None, no authentication is required.

    Returns:
        Callable: A dependency function that validates the API key.
    """
    if not api_key:
        # If no API key is configured, return a dummy dependency that always succeeds
        async def no_auth():
            return None

        return no_auth

    # If API key is configured, use proper authentication
    api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

    async def api_key_auth(
        api_key_header_value: Optional[str] = Security(api_key_header),
    ):
        if not api_key_header_value:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN, detail="API Key required"
            )

        if api_key_header_value.startswith("Bearer "):
            api_key_header_value = api_key_header_value.split(" ")[1]
        else:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Invalid Authorization header format",
            )

        if api_key_header_value != api_key:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN, detail="Invalid API Key"
            )
        return api_key_header_value

    return api_key_auth


def parse_keep_alive(keep_alive):
    if keep_alive is None or keep_alive == "":
        return -1
    
    try:
        # 尝试将字符串转换为整数
        return int(keep_alive) * 60  # 假设单位是分钟，转换为秒
    
    except ValueError:
        # 如果失败，检查是否包含时间单位（如 'm'）
        if isinstance(keep_alive, str) and keep_alive[-1] in ['s', 'm', 'h']:
            value = int(keep_alive[:-1])
            unit = keep_alive[-1]
            
            if unit == 's':
                return value
            elif unit == 'm':
                return value * 60
            elif unit == 'h':
                return value * 3600
        else:
            raise ValueError(f"Invalid keep_alive value: {keep_alive}")