"""
流式 ASR 引擎抽象基类
定义所有引擎后端必须实现的统一接口
"""

import abc
import asyncio
from typing import AsyncIterator, Optional
from uuid import uuid4

from bookroom_audio.api.routers.transcribe_streaming.schemas import (
    StreamingSessionConfig,
    ASRResult,
)
from bookroom_audio.api.routers.transcribe_streaming.constants import (
    StreamingASREngine,
)
from bookroom_audio.utils.utils_api import logger


class StreamingSession:
    """单个流式识别会话上下文"""

    def __init__(
        self,
        session_id: str,
        config: StreamingSessionConfig,
    ) -> None:
        self.session_id = session_id
        self.config = config
        self.result_queue: asyncio.Queue[ASRResult] = asyncio.Queue()
        self.audio_buffer: bytearray = bytearray()
        self.total_audio_ms: int = 0
        self.is_active: bool = True
        self._stop_event = asyncio.Event()

    def push_result(self, result: ASRResult) -> None:
        """推送识别结果到队列"""
        if self.is_active:
            self.result_queue.put_nowait(result)

    def mark_stopped(self) -> None:
        """标记会话停止"""
        self.is_active = False
        self._stop_event.set()

    def is_stopped(self) -> bool:
        """是否已停止"""
        return self._stop_event.is_set()


class StreamingASRBackend(abc.ABC):
    """流式 ASR 引擎后端抽象基类"""

    @property
    @abc.abstractmethod
    def engine_type(self) -> StreamingASREngine:
        """引擎类型标识"""
        ...

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """检查引擎是否可用"""
        ...

    @abc.abstractmethod
    async def start_session(
        self,
        config: StreamingSessionConfig,
    ) -> StreamingSession:
        """
        启动新的流式识别会话

        Args:
            config: 会话配置

        Returns:
            会话上下文
        """
        ...

    @abc.abstractmethod
    async def send_audio(
        self,
        session: StreamingSession,
        audio_chunk: bytes,
    ) -> None:
        """
        发送音频块到引擎

        Args:
            session: 会话上下文
            audio_chunk: PCM 音频数据
        """
        ...

    @abc.abstractmethod
    async def recv_results(
        self,
        session: StreamingSession,
    ) -> AsyncIterator[ASRResult]:
        """
        接收识别结果流

        Args:
            session: 会话上下文

        Yields:
            识别结果
        """
        ...

    @abc.abstractmethod
    async def stop_session(self, session: StreamingSession) -> None:
        """
        停止会话，释放资源

        Args:
            session: 会话上下文
        """
        ...

    def _create_session(
        self,
        config: StreamingSessionConfig,
    ) -> StreamingSession:
        """创建会话上下文（辅助方法）"""
        session_id = str(uuid4())
        session = StreamingSession(session_id, config)
        logger.info(
            f"[{self.engine_type}] Session created: {session_id}"
        )
        return session


class EngineUnavailableError(RuntimeError):
    """引擎不可用异常"""

    def __init__(self, engine: StreamingASREngine, reason: str) -> None:
        self.engine = engine
        self.reason = reason
        super().__init__(
            f"Engine '{engine.value}' unavailable: {reason}"
        )
