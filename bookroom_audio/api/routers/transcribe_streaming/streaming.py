"""
流式语音识别 WebSocket 路由
处理客户端 WebSocket 连接，管理会话生命周期
"""

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from starlette.websockets import WebSocketState

from bookroom_audio.api.routers.transcribe_streaming.constants import (
    ClientMessageType,
    ServerMessageType,
    ErrorCode,
    StreamingASREngine,
    AudioFormat,
    WS_IDLE_TIMEOUT_SECONDS,
    WS_RECEIVE_BUFFER_BYTES,
    WS_HEARTBEAT_TIMEOUT_SECONDS,
)
from bookroom_audio.api.routers.transcribe_streaming.schemas import (
    StartMessage,
    StopMessage,
    StartedMessage,
    PartialMessage,
    FinalMessage,
    ErrorMessage,
    ClosedMessage,
    PongMessage,
    PausedMessage,
    ResumedMessage,
    StreamingSessionConfig,
)
from bookroom_audio.api.routers.transcribe_streaming.engines.base import (
    StreamingASRBackend,
    StreamingSession,
    EngineUnavailableError,
)
from bookroom_audio.api.routers.transcribe_streaming.engines import (
    get_streaming_backend,
)
from bookroom_audio.api.routers.transcribe_streaming.utils import (
    decode_to_pcm_async,
    bytes_to_ms,
)
from bookroom_audio.utils.config import get_config
from bookroom_audio.utils.utils_api import logger


class StreamingConnectionHandler:
    """单个 WebSocket 连接处理器

    管理一个客户端连接的完整生命周期：
    - 鉴权
    - 接收 START 配置
    - 创建引擎会话
    - 并发：接收音频 + 推送结果
    - 心跳保活（PING/PONG）
    - 暂停/恢复（PAUSE/RESUME）
    - 停止和清理
    """

    def __init__(
        self,
        websocket: WebSocket,
        api_key: Optional[str] = None,
    ) -> None:
        self.websocket = websocket
        self.api_key = api_key
        self.session: Optional[StreamingSession] = None
        self.backend: Optional[StreamingASRBackend] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._push_task: Optional[asyncio.Task] = None
        self._is_closing = False
        # 暂停状态：暂停期间丢弃音频帧，不转发到引擎
        self._paused = False
        # 最近一次收到任意消息的时间戳（用于心跳超时判定）
        self._last_recv_time: float = time.monotonic()

    async def handle(self) -> None:
        """处理整个连接生命周期"""
        try:
            await self.websocket.accept()

            # 等待 START 消息
            config = await self._wait_for_start()
            if config is None:
                return

            # 创建引擎和会话
            await self._init_session(config)

            # 启动并发任务
            await self._run_concurrent_tasks()

        except WebSocketDisconnect:
            logger.info("Client disconnected")
        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
            await self._send_error(
                ErrorCode.INTERNAL_ERROR,
                str(e),
            )
        finally:
            await self._cleanup()

    async def _wait_for_start(self) -> Optional[StreamingSessionConfig]:
        """等待并解析客户端 START 消息"""
        try:
            message = await asyncio.wait_for(
                self.websocket.receive_text(),
                timeout=WS_IDLE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await self._send_error(
                ErrorCode.SESSION_NOT_FOUND,
                "Timeout waiting for START message",
            )
            return None

        try:
            data = json.loads(message)
            start_msg = StartMessage(**data)
            return start_msg.config
        except Exception as e:
            await self._send_error(
                ErrorCode.INVALID_CONFIG,
                f"Invalid START message: {e}",
            )
            return None

    async def _init_session(
        self,
        config: StreamingSessionConfig,
    ) -> None:
        """初始化引擎会话"""
        # 确定引擎类型
        engine_type = self._resolve_engine(config)
        self.backend = get_streaming_backend(engine_type)

        # 检查可用性
        if not await self.backend.is_available():
            raise EngineUnavailableError(
                engine_type,
                "Engine check failed"
            )

        # 启动会话
        self.session = await self.backend.start_session(config)

        # 发送 STARTED 消息
        started_msg = StartedMessage(
            session_id=self.session.session_id,
            engine=engine_type.value,
            config=config.model_dump(),
        )
        await self._send_message(started_msg.model_dump())

    def _resolve_engine(
        self,
        config: StreamingSessionConfig,
    ) -> StreamingASREngine:
        """解析使用的引擎类型"""
        if config.engine is not None:
            try:
                return StreamingASREngine(config.engine)
            except ValueError:
                raise EngineUnavailableError(
                    StreamingASREngine.FUNASR_LOCAL,
                    f"Unknown engine: {config.engine}",
                )

        # 使用配置默认值
        app_config = get_config()
        default_engine = app_config.model.streaming_asr_engine
        return StreamingASREngine(default_engine)

    async def _run_concurrent_tasks(self) -> None:
        """并发运行接收和推送任务

        当接收循环（_receive_audio_loop）完成时（收到 STOP 或断连），
        不立即取消推送循环（_push_results_loop），因为：
        1. _cleanup 会先调用 stop_session 推送 FINAL 结果
        2. _push_results_loop 需要继续处理队列中的 FINAL 结果
        3. recv_results 在 session stopped 且队列空时自然退出
        """
        self._recv_task = asyncio.create_task(
            self._receive_audio_loop()
        )
        self._push_task = asyncio.create_task(
            self._push_results_loop()
        )

        # 等待接收循环完成（收到 STOP 或断连）
        await asyncio.wait(
            {self._recv_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # 不取消 push_task，由 _cleanup 负责清理
        # push_task 会在 stop_session 后，队列处理完自然退出

    async def _receive_audio_loop(self) -> None:
        """接收客户端消息循环

        支持心跳超时检测：超过 WS_HEARTBEAT_TIMEOUT_SECONDS
        未收到任何消息则主动断开。
        """
        while not self._is_closing:
            try:
                message = await asyncio.wait_for(
                    self.websocket.receive(),
                    timeout=WS_HEARTBEAT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Heartbeat timeout ({WS_HEARTBEAT_TIMEOUT_SECONDS}s), "
                    f"closing connection"
                )
                await self._send_error(
                    ErrorCode.SESSION_NOT_FOUND,
                    "Heartbeat timeout: no message received",
                )
                break
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Receive error: {e}")
                break

            # 更新最近接收时间（任意消息都算保活）
            self._last_recv_time = time.monotonic()

            if "bytes" in message:
                # 音频二进制帧
                await self._handle_audio_chunk(message["bytes"])
            elif "text" in message:
                # 控制消息
                should_stop = await self._handle_control_message(
                    message["text"]
                )
                if should_stop:
                    break

    async def _handle_audio_chunk(self, chunk: bytes) -> None:
        """处理音频块

        暂停期间丢弃音频，不转发到引擎。
        """
        if self.session is None or self.backend is None:
            return

        # 暂停期间丢弃音频
        if self._paused:
            return

        # 解码为 PCM
        audio_format = self.session.config.audio_format
        if audio_format != AudioFormat.PCM.value:
            try:
                chunk = await decode_to_pcm_async(
                    chunk,
                    AudioFormat(audio_format),
                    self.session.config.sample_rate,
                )
            except Exception as e:
                await self._send_error(
                    ErrorCode.AUDIO_DECODE_FAILED,
                    str(e),
                )
                return

        # 转发到引擎
        try:
            await self.backend.send_audio(self.session, chunk)
        except EngineUnavailableError as e:
            await self._send_error(
                ErrorCode.ENGINE_UNAVAILABLE,
                str(e),
            )
            self._is_closing = True

    async def _handle_control_message(self, text: str) -> bool:
        """处理控制消息，返回是否应该停止"""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            await self._send_error(
                ErrorCode.INVALID_CONFIG,
                "Invalid JSON control message",
            )
            return False

        msg_type = data.get("type")
        if msg_type == ClientMessageType.STOP.value:
            logger.info(
                f"Client sent STOP for session "
                f"{self.session.session_id if self.session else 'N/A'}"
            )
            return True

        if msg_type == ClientMessageType.START.value:
            # 不支持会话内重新 start
            await self._send_error(
                ErrorCode.INVALID_CONFIG,
                "Session already started",
            )
            return False

        if msg_type == ClientMessageType.PING.value:
            await self._handle_ping(data)
            return False

        if msg_type == ClientMessageType.PAUSE.value:
            await self._handle_pause()
            return False

        if msg_type == ClientMessageType.RESUME.value:
            await self._handle_resume()
            return False

        return False

    async def _handle_ping(self, data: dict) -> None:
        """处理 PING 心跳，立即回 PONG"""
        client_time_ms = data.get("timestamp_ms")
        pong_msg = PongMessage(
            session_id=self.session.session_id if self.session else None,
            server_time_ms=int(time.time() * 1000),
            client_time_ms=client_time_ms,
        )
        await self._send_message(pong_msg.model_dump())

    async def _handle_pause(self) -> None:
        """处理 PAUSE：暂停音频处理"""
        if self._paused:
            return  # 已暂停，忽略重复请求
        self._paused = True
        if self.session is not None:
            paused_msg = PausedMessage(
                session_id=self.session.session_id,
                paused_at_ms=self.session.total_audio_ms,
            )
            await self._send_message(paused_msg.model_dump())
            logger.info(
                f"Session {self.session.session_id} paused at "
                f"{self.session.total_audio_ms}ms"
            )

    async def _handle_resume(self) -> None:
        """处理 RESUME：恢复音频处理"""
        if not self._paused:
            return  # 未暂停，忽略重复请求
        self._paused = False
        if self.session is not None:
            resumed_msg = ResumedMessage(
                session_id=self.session.session_id,
                resumed_at_ms=self.session.total_audio_ms,
            )
            await self._send_message(resumed_msg.model_dump())
            logger.info(
                f"Session {self.session.session_id} resumed at "
                f"{self.session.total_audio_ms}ms"
            )

    async def _push_results_loop(self) -> None:
        """推送识别结果到客户端

        即使 _is_closing，也处理完队列中剩余结果，
        确保 FINAL 结果能送达客户端。
        """
        if self.session is None or self.backend is None:
            return

        async for result in self.backend.recv_results(self.session):
            if result.is_final:
                msg = FinalMessage(
                    session_id=self.session.session_id,
                    text=result.text,
                    sentence_id=result.sentence_id,
                    start_ms=result.start_ms,
                    end_ms=result.end_ms,
                    speaker=result.speaker,
                    emotion=result.emotion,
                    words=result.words,
                )
            else:
                msg = PartialMessage(
                    session_id=self.session.session_id,
                    text=result.text,
                    is_final=False,
                    sentence_id=result.sentence_id,
                    timestamp_ms=self.session.total_audio_ms,
                )

            await self._send_message(msg.model_dump())

    async def _send_message(self, data: dict) -> None:
        """发送 JSON 消息到客户端"""
        if self.websocket.client_state != WebSocketState.CONNECTED:
            return
        try:
            await self.websocket.send_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"Send message failed: {e}")

    async def _send_error(
        self,
        code: ErrorCode,
        message: str,
    ) -> None:
        """发送错误消息"""
        msg = ErrorMessage(
            session_id=self.session.session_id if self.session else None,
            code=code,
            message=message,
        )
        await self._send_message(msg.model_dump())

    async def _cleanup(self) -> None:
        """清理资源

        顺序：
        1. 调用 stop_session 推送 FINAL 结果到队列
        2. 等待 _push_results_loop 处理完队列中的 FINAL
        3. 设置 _is_closing 并发送 CLOSED 消息
        4. 关闭 WebSocket
        """
        # 1. 停止会话（推送 FINAL 结果到队列）
        if self.session is not None and self.backend is not None:
            try:
                await self.backend.stop_session(self.session)
            except Exception as e:
                logger.warning(f"Stop session error: {e}")

        # 2. 等待推送循环处理完队列中的 FINAL 结果
        if self._push_task is not None and not self._push_task.done():
            try:
                # 给推送循环最多 10 秒处理剩余结果
                await asyncio.wait_for(self._push_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Push task timeout, cancelling")
                self._push_task.cancel()
                try:
                    await self._push_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

        # 3. 标记关闭
        self._is_closing = True

        # 4. 发送 CLOSED 消息
        if self.session is not None:
            closed_msg = ClosedMessage(
                session_id=self.session.session_id,
            )
            await self._send_message(closed_msg.model_dump())

        # 5. 关闭 WebSocket
        if self.websocket.client_state == WebSocketState.CONNECTED:
            try:
                await self.websocket.close()
            except Exception:
                pass


def create_streaming_routes(
    args: object,
    api_key: Optional[str] = None,
) -> APIRouter:
    """创建流式语音识别路由

    Args:
        args: 应用配置参数
        api_key: API 密钥（None 表示不鉴权）

    Returns:
        APIRouter 实例
    """
    router = APIRouter(prefix="/v1/audio/streaming", tags=["streaming-transcribe"])

    async def verify_token(token: Optional[str]) -> bool:
        """验证 API token"""
        if not api_key:
            return True
        return token == api_key

    @router.websocket("/transcriptions")
    async def streaming_transcriptions(
        websocket: WebSocket,
        token: Optional[str] = Query(default=None),
    ) -> None:
        """流式语音识别 WebSocket 端点（bookroom-audio 原生协议）

        协议流程：
        1. 客户端建立 WebSocket 连接（带 token 鉴权）
        2. 客户端发送 START JSON 消息（含配置）
        3. 服务端返回 STARTED 消息
        4. 客户端持续发送 binary 音频帧
        5. 服务端持续推送 PARTIAL/FINAL JSON 消息
        6. 客户端发送 STOP 或断开连接
        7. 服务端返回 CLOSED 消息
        """
        # 鉴权
        if not await verify_token(token):
            await websocket.accept()
            await websocket.send_text(json.dumps({
                "type": ServerMessageType.ERROR.value,
                "code": ErrorCode.AUTH_FAILED.value,
                "message": "Invalid or missing API token",
            }))
            await websocket.close(code=4001)
            return

        handler = StreamingConnectionHandler(websocket, api_key)
        await handler.handle()

    @router.websocket("/funasr")
    async def streaming_funasr_compat(
        websocket: WebSocket,
        token: Optional[str] = Query(default=None),
    ) -> None:
        """FunASR 协议兼容端点

        与 FunASR serve_realtime_ws.py 协议兼容，使用 FunASR
        官方客户端 SDK 的项目可直接对接，无需修改代码。

        协议流程：
        1. 客户端建立 WebSocket 连接（带 token 鉴权）
        2. 客户端发送初始化 JSON（mode/chunk_size/is_speaking=true 等）
        3. 客户端持续发送 binary PCM 音频帧
        4. 服务端持续推送 JSON 结果（mode: 2pass-online/2pass-offline）
        5. 客户端发送 {"is_speaking": false} 标识结束
        6. 服务端推送最后 FINAL 结果后关闭连接
        """
        # 鉴权
        if not await verify_token(token):
            await websocket.accept()
            await websocket.send_text(json.dumps({
                "mode": "",
                "text": "[error:auth_failed] Invalid or missing API token",
                "is_final": True,
                "error": True,
                "error_code": ErrorCode.AUTH_FAILED.value,
            }))
            await websocket.close(code=4001)
            return

        from bookroom_audio.api.routers.transcribe_streaming.funasr_compat import (
            FunASRCompatHandler,
        )
        handler = FunASRCompatHandler(websocket, api_key)
        await handler.handle()

    @router.get("/engines")
    async def list_engines() -> dict:
        """列出可用的流式 ASR 引擎"""
        from bookroom_audio.api.routers.transcribe_streaming.engines import (
            get_available_engines,
        )
        engines = await get_available_engines()
        return {
            "engines": engines,
            "default_engine": get_config().model.streaming_asr_engine,
        }

    return router
