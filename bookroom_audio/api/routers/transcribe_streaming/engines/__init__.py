"""
流式 ASR 引擎工厂
根据引擎类型创建对应的后端实例
"""

from typing import Dict, Type

from bookroom_audio.api.routers.transcribe_streaming.engines.base import (
    StreamingASRBackend,
    EngineUnavailableError,
)
from bookroom_audio.api.routers.transcribe_streaming.engines.funasr_server import (
    FunASRServerBackend,
)
from bookroom_audio.api.routers.transcribe_streaming.engines.funasr_local import (
    FunASRLocalBackend,
)
from bookroom_audio.api.routers.transcribe_streaming.engines.sensevoice import (
    SenseVoiceLocalBackend,
)
from bookroom_audio.api.routers.transcribe_streaming.constants import (
    StreamingASREngine,
)
from bookroom_audio.utils.utils_api import logger


# 引擎注册表：引擎类型 → 后端类
_BACKEND_REGISTRY: Dict[StreamingASREngine, Type[StreamingASRBackend]] = {
    StreamingASREngine.FUNASR_SERVER: FunASRServerBackend,
    StreamingASREngine.FUNASR_LOCAL: FunASRLocalBackend,
    StreamingASREngine.SENSE_VOICE_LOCAL: SenseVoiceLocalBackend,
}

# 后端实例缓存（单例）
_backend_instances: Dict[StreamingASREngine, StreamingASRBackend] = {}


def get_streaming_backend(
    engine: StreamingASREngine,
) -> StreamingASRBackend:
    """获取指定引擎的后端实例（单例）

    Args:
        engine: 引擎类型枚举

    Returns:
        引擎后端实例

    Raises:
        EngineUnavailableError: 引擎不可用
    """
    if engine in _backend_instances:
        return _backend_instances[engine]

    backend_class = _BACKEND_REGISTRY.get(engine)
    if backend_class is None:
        raise EngineUnavailableError(
            engine,
            f"Unknown engine type: {engine}"
        )

    instance = backend_class()
    _backend_instances[engine] = instance
    logger.info(f"Streaming ASR backend initialized: {engine.value}")
    return instance


def list_supported_engines() -> list[str]:
    """列出所有支持的引擎类型"""
    return [engine.value for engine in StreamingASREngine]


async def check_engine_available(engine: StreamingASREngine) -> bool:
    """异步检查引擎是否可用"""
    try:
        backend = get_streaming_backend(engine)
        return await backend.is_available()
    except EngineUnavailableError:
        return False


async def get_available_engines() -> list[dict]:
    """获取所有引擎及其可用性状态"""
    engines_info = []
    for engine in StreamingASREngine:
        available = await check_engine_available(engine)
        engines_info.append({
            "engine": engine.value,
            "available": available,
            "description": _get_engine_description(engine),
        })
    return engines_info


def _get_engine_description(engine: StreamingASREngine) -> str:
    """获取引擎描述"""
    descriptions = {
        StreamingASREngine.FUNASR_SERVER: (
            "FunASR Server proxy - connects to external "
            "serve_realtime_ws.py service, native streaming"
        ),
        StreamingASREngine.FUNASR_LOCAL: (
            "FunASR Local - in-process paraformer-zh-streaming, "
            "chunk-based streaming"
        ),
        StreamingASREngine.SENSE_VOICE_LOCAL: (
            "SenseVoice Local - in-process SenseVoice with VAD, "
            "ultra-fast, supports emotion/event detection"
        ),
    }
    return descriptions.get(engine, "")


async def cleanup_all_backends() -> None:
    """清理所有后端资源（应用关闭时调用）"""
    for engine, instance in _backend_instances.items():
        try:
            # 后端如果有 cleanup 方法，调用它
            cleanup = getattr(instance, "cleanup", None)
            if cleanup is not None:
                await cleanup()
            logger.info(f"Backend {engine.value} cleaned up")
        except Exception as e:
            logger.warning(
                f"Error cleaning up backend {engine.value}: {e}"
            )
    _backend_instances.clear()
