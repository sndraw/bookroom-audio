"""
FunASR Server 代理后端
作为 WebSocket 客户端连接到外部 FunASR serve_realtime_ws.py 服务
负责音频转发和结果协议转换
"""

import asyncio
import json
from typing import AsyncIterator, Optional, List
from urllib.parse import urlparse

import websockets
from websockets.client import WebSocketClientProtocol

from bookroom_audio.api.routers.transcribe_streaming.engines.base import (
    StreamingASRBackend,
    StreamingSession,
    EngineUnavailableError,
)
from bookroom_audio.api.routers.transcribe_streaming.schemas import (
    StreamingSessionConfig,
    ASRResult,
    WordInfo,
)
from bookroom_audio.api.routers.transcribe_streaming.constants import (
    StreamingASREngine,
    FunASRMode,
    FunASRMessageField,
    FunASRResponseMode,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_ENCODER_CHUNK_LOOK_BACK,
    DEFAULT_DECODER_CHUNK_LOOK_BACK,
    DEFAULT_SAMPLE_RATE,
    PCM_BYTES_PER_MS,
)
from bookroom_audio.utils.config import get_config
from bookroom_audio.utils.utils_api import logger


class FunASRServerBackend(StreamingASRBackend):
    """FunASR Server 代理后端

    连接到外部 FunASR WebSocket 服务（serve_realtime_ws.py），
    转发客户端音频和识别结果。

    服务端地址通过环境变量 STREAMING_FUNASR_SERVER_URL 配置，
    不硬编码任何 IP/域名/端口。
    """

    def __init__(self) -> None:
        self._server_url: Optional[str] = None

    @property
    def engine_type(self) -> StreamingASREngine:
        return StreamingASREngine.FUNASR_SERVER

    def _get_server_url(self) -> str:
        """从配置获取 FunASR 服务地址"""
        config = get_config()
        server_url = config.model.streaming_funasr_server_url
        if not server_url:
            raise EngineUnavailableError(
                self.engine_type,
                "STREAMING_FUNASR_SERVER_URL not configured"
            )
        return server_url

    async def is_available(self) -> bool:
        """检查 FunASR 服务是否可用"""
        try:
            server_url = self._get_server_url()
            # 尝试建立连接但不发送数据
            async with websockets.connect(
                server_url,
                close_timeout=5,
                open_timeout=5,
            ) as ws:
                await ws.close()
            return True
        except Exception as e:
            logger.warning(
                f"FunASR server unavailable at "
                f"{self._server_url}: {e}"
            )
            return False

    async def start_session(
        self,
        config: StreamingSessionConfig,
    ) -> StreamingSession:
        """启动新会话，建立到 FunASR 服务的 WebSocket 连接"""
        server_url = self._get_server_url()
        session = self._create_session(config)

        try:
            ws = await websockets.connect(
                server_url,
                close_timeout=10,
                open_timeout=10,
                max_size=2 ** 20,
            )
        except Exception as e:
            raise EngineUnavailableError(
                self.engine_type,
                f"Failed to connect FunASR server: {e}"
            )

        # 发送初始化消息
        init_msg = self._build_init_message(config)
        await ws.send(json.dumps(init_msg))
        logger.info(
            f"[FunASR-Server] Session {session.session_id} "
            f"connected, init sent"
        )

        # 保存连接到会话上下文
        setattr(session, "_ws", ws)
        setattr(session, "_recv_task", None)

        return session

    def _build_init_message(
        self,
        config: StreamingSessionConfig,
    ) -> dict:
        """构建 FunASR 初始化消息"""
        chunk_size = config.chunk_size or DEFAULT_CHUNK_SIZE

        msg = {
            FunASRMessageField.MODE.value: FunASRMode.TWO_PASS.value,
            FunASRMessageField.CHUNK_SIZE.value: chunk_size,
            FunASRMessageField.WAV_NAME.value: f"session_{id(config)}",
            FunASRMessageField.IS_SPEAKING.value: True,
            FunASRMessageField.ITN.value: config.enable_itn,
            FunASRMessageField.AUDIO_FS.value: config.sample_rate,
        }

        # 热词
        if config.hotwords:
            msg[FunASRMessageField.HOTWORDS.value] = json.dumps(
                config.hotwords,
                ensure_ascii=False
            )

        # SenseVoice 相关参数（如果服务端支持）
        if config.language:
            msg["svs_lang"] = config.language
        msg["svs_itn"] = config.enable_itn

        return msg

    async def send_audio(
        self,
        session: StreamingSession,
        audio_chunk: bytes,
    ) -> None:
        """转发音频二进制数据到 FunASR 服务"""
        ws: WebSocketClientProtocol = getattr(session, "_ws", None)
        if ws is None or ws.closed:
            raise EngineUnavailableError(
                self.engine_type,
                "WebSocket connection not established"
            )

        await ws.send(audio_chunk)
        session.total_audio_ms += len(audio_chunk) // PCM_BYTES_PER_MS

    async def recv_results(
        self,
        session: StreamingSession,
    ) -> AsyncIterator[ASRResult]:
        """接收并转换 FunASR 服务端返回的识别结果"""
        ws: WebSocketClientProtocol = getattr(session, "_ws", None)
        if ws is None:
            return

        try:
            async for raw_message in ws:
                if session.is_stopped():
                    break

                if isinstance(raw_message, bytes):
                    continue

                result = self._parse_funasr_response(raw_message, session)
                if result is not None:
                    yield result
        except websockets.ConnectionClosed:
            logger.info(
                f"[FunASR-Server] Session {session.session_id} "
                f"connection closed"
            )
        except Exception as e:
            logger.error(
                f"[FunASR-Server] Recv error: {e}",
                exc_info=True,
            )

    def _parse_funasr_response(
        self,
        message: str,
        session: StreamingSession,
    ) -> Optional[ASRResult]:
        """解析 FunASR 服务端响应消息"""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(
                f"[FunASR-Server] Invalid JSON: {message[:200]}"
            )
            return None

        mode = data.get(FunASRMessageField.MODE.value, "")
        text = data.get(FunASRMessageField.TEXT.value, "")
        is_final = data.get(FunASRMessageField.IS_FINAL.value, False)

        if not text:
            return None

        # 解析时间戳
        timestamp_raw = data.get(FunASRMessageField.TIMESTAMP.value)
        words = self._parse_timestamps(timestamp_raw)

        # 2pass-online 是中间结果，2pass-offline 是修正后的最终结果
        is_sentence_final = (
            is_final or
            mode == FunASRResponseMode.TWO_PASS_OFFLINE.value
        )

        # 计算句子时间
        start_ms = 0
        end_ms = session.total_audio_ms
        if words:
            start_ms = words[0].start_ms
            end_ms = words[-1].end_ms

        return ASRResult(
            text=text,
            is_final=is_sentence_final,
            sentence_id=0,
            start_ms=start_ms,
            end_ms=end_ms,
            words=words,
        )

    def _parse_timestamps(
        self,
        timestamp_raw: Optional[str],
    ) -> List[WordInfo]:
        """解析 FunASR 时间戳格式"""
        if not timestamp_raw:
            return []

        try:
            ts_list = json.loads(timestamp_raw)
        except (json.JSONDecodeError, TypeError):
            return []

        words: List[WordInfo] = []
        for ts in ts_list:
            if isinstance(ts, list) and len(ts) >= 2:
                words.append(WordInfo(
                    text="",
                    start_ms=int(ts[0]),
                    end_ms=int(ts[1]),
                ))
        return words

    async def stop_session(self, session: StreamingSession) -> None:
        """停止会话，发送结束信号并关闭连接"""
        ws: WebSocketClientProtocol = getattr(session, "_ws", None)
        if ws is None or ws.closed:
            session.mark_stopped()
            return

        try:
            # 发送结束消息
            end_msg = {
                FunASRMessageField.IS_SPEAKING.value: False,
            }
            await ws.send(json.dumps(end_msg))

            # 等待服务端返回最后结果（最多 5 秒）
            try:
                async for raw_message in ws:
                    if isinstance(raw_message, bytes):
                        continue
                    result = self._parse_funasr_response(
                        raw_message,
                        session,
                    )
                    if result is not None:
                        session.push_result(result)
                    break  # 只等待一个最终结果
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            logger.warning(
                f"[FunASR-Server] Stop error: {e}"
            )
        finally:
            await ws.close()
            session.mark_stopped()
            logger.info(
                f"[FunASR-Server] Session {session.session_id} closed"
            )
