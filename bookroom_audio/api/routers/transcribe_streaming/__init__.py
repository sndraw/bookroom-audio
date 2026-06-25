"""
流式语音识别模块入口
提供 create_streaming_transcribe_routes 统一路由创建函数
"""

from typing import Optional

from fastapi import APIRouter

from bookroom_audio.api.routers.transcribe_streaming.streaming import (
    create_streaming_routes,
)


def create_streaming_transcribe_routes(
    args: object,
    api_key: Optional[str] = None,
) -> APIRouter:
    """创建流式语音识别路由

    Args:
        args: 应用配置参数（AppConfig）
        api_key: 可选的 API 密钥

    Returns:
        注册了流式识别端点的 APIRouter
    """
    return create_streaming_routes(args, api_key)


__all__ = [
    "create_streaming_transcribe_routes",
]
