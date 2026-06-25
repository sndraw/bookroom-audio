"""
FunASR 协议兼容层

提供与 FunASR serve_realtime_ws.py 协议兼容的 WebSocket 端点，
让使用 FunASR 官方客户端 SDK 的项目可以无缝对接 bookroom-audio。

兼容字段映射：
- 客户端初始化 JSON → bookroom-audio START 消息
- 二进制 PCM 音频 → 直接转发到引擎
- {"is_speaking": false} → STOP
- PartialMessage → {mode:"2pass-online", text, is_final:false}
- FinalMessage → {mode:"2pass-offline", text, is_final:true}

注意：本层仅做协议适配，不修改引擎实现。
"""

import asyncio
import json
from typing import Optional, Dict, Any, List

from starlette.websockets import WebSocketState

from bookroom_audio.api.routers.transcribe_streaming.constants import (
    AudioFormat,
    ErrorCode,
    FunASRMessageField,
    FunASRResponseMode,
    StreamingASREngine,
    WS_IDLE_TIMEOUT_SECONDS,
    DEFAULT_VAD_SILENCE_MS,
)
from bookroom_audio.api.routers.transcribe_streaming.schemas import (
    StreamingSessionConfig,
)
from bookroom_audio.api.routers.transcribe_streaming.streaming import (
    StreamingConnectionHandler,
)
from bookroom_audio.api.routers.transcribe_streaming.engines import (
    get_streaming_backend,
)
from bookroom_audio.api.routers.transcribe_streaming.engines.base import (
    EngineUnavailableError,
)
from bookroom_audio.utils.utils_api import logger


# ==================== FunASR 模式到引擎的映射 ====================

# FunASR mode 字段值 → bookroom-audio 引擎
_FUNASR_MODE_TO_ENGINE: Dict[str, StreamingASREngine] = {
    "online": StreamingASREngine.FUNASR_LOCAL,      # 纯流式
    "2pass": StreamingASREngine.FUNASR_LOCAL,       # 流式 + 句末修正
    "offline": StreamingASREngine.SENSE_VOICE_LOCAL,  # 一次性识别
}


def _parse_funasr_init_message(
    raw: Dict[str, Any],
) -> StreamingSessionConfig:
    """将 FunASR 初始化消息转换为 bookroom-audio 配置

    FunASR 客户端发送的初始化消息示例：
    {
        "mode": "2pass",
        "chunk_size": [5, 10, 5],
        "wav_name": "microphone",
        "is_speaking": true,
        "hotwords": "{\"阿里巴巴\":20}",
        "itn": true,
        "audio_fs": 16000,
        "wav_format": "pcm"
    }

    Args:
        raw: FunASR 初始化 JSON 解析后的字典

    Returns:
        StreamingSessionConfig 实例

    Raises:
        ValueError: 配置非法时抛出
    """
    mode = raw.get(FunASRMessageField.MODE.value, "2pass")
    if mode not in _FUNASR_MODE_TO_ENGINE:
        raise ValueError(
            f"Unsupported mode '{mode}', "
            f"must be one of: online/offline/2pass"
        )
    engine = _FUNASR_MODE_TO_ENGINE[mode]

    # 音频采样率（FunASR 用 audio_fs）
    sample_rate = int(raw.get(FunASRMessageField.AUDIO_FS.value, 16000))

    # 音频格式（FunASR 用 wav_format，默认 pcm）
    wav_format = str(raw.get("wav_format", "pcm")).lower()
    try:
        audio_format = AudioFormat(wav_format)
    except ValueError:
        # 不支持的格式，回退到 pcm（由解码器处理）
        audio_format = AudioFormat.PCM

    # chunk_size（FunASR 流式分块）
    chunk_size: Optional[List[int]] = None
    raw_chunk = raw.get(FunASRMessageField.CHUNK_SIZE.value)
    if raw_chunk is not None:
        if not isinstance(raw_chunk, list) or len(raw_chunk) != 3:
            raise ValueError(
                "chunk_size must be a list of 3 integers, "
                f"got: {raw_chunk}"
            )
        chunk_size = [int(x) for x in raw_chunk]

    # 热词（FunASR 用 JSON string，我们用 dict）
    hotwords: Optional[Dict[str, int]] = None
    raw_hotwords = raw.get(FunASRMessageField.HOTWORDS.value)
    if raw_hotwords:
        if isinstance(raw_hotwords, str):
            try:
                hotwords = json.loads(raw_hotwords)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid hotwords JSON: {e}")
        elif isinstance(raw_hotwords, dict):
            hotwords = raw_hotwords

    # itn（逆文本归一化）
    itn = bool(raw.get(FunASRMessageField.ITN.value, True))

    # VAD 静音阈值（FunASR 不直接暴露，使用默认值）
    max_sentence_silence_ms = DEFAULT_VAD_SILENCE_MS

    return StreamingSessionConfig(
        engine=engine,
        language="zh",
        audio_format=audio_format,
        sample_rate=sample_rate,
        enable_punctuation=True,
        enable_vad=True,
        enable_itn=itn,
        enable_speaker_diarization=False,
        enable_emotion=False,
        hotwords=hotwords,
        chunk_size=chunk_size,
        max_sentence_silence_ms=max_sentence_silence_ms,
    )


class FunASRCompatHandler(StreamingConnectionHandler):
    """FunASR 协议兼容连接处理器

    继承 StreamingConnectionHandler，仅重写协议层方法：
    - _wait_for_start: 解析 FunASR 初始化消息
    - _handle_control_message: 处理 is_speaking=false
    - _push_results_loop: 输出 FunASR 格式
    - _send_error: FunASR 错误格式
    - _cleanup: 不发送 CLOSED 消息（FunASR 协议无此概念）
    """

    def __init__(
        self,
        websocket,
        api_key: Optional[str] = None,
    ) -> None:
        super().__init__(websocket, api_key)
        # 会话级别的 wav_name，用于服务端响应中回显
        self._wav_name: str = "microphone"

    async def _wait_for_start(self) -> Optional[StreamingSessionConfig]:
        """等待并解析 FunASR 初始化消息

        FunASR 客户端连接后立即发送初始化 JSON（无 type 字段，
        通过 is_speaking=true 标识）。
        """
        try:
            message = await asyncio.wait_for(
                self.websocket.receive_text(),
                timeout=WS_IDLE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await self._send_error(
                ErrorCode.SESSION_NOT_FOUND,
                "Timeout waiting for init message",
            )
            return None

        try:
            raw = json.loads(message)
        except json.JSONDecodeError as e:
            await self._send_error(
                ErrorCode.INVALID_CONFIG,
                f"Invalid JSON init message: {e}",
            )
            return None

        # 记录 wav_name 用于响应回显
        self._wav_name = raw.get(
            FunASRMessageField.WAV_NAME.value,
            "microphone",
        )

        try:
            config = _parse_funasr_init_message(raw)
        except ValueError as e:
            await self._send_error(
                ErrorCode.INVALID_CONFIG,
                str(e),
            )
            return None

        return config

    async def _handle_control_message(self, text: str) -> bool:
        """处理 FunASR 控制消息

        FunASR 客户端通过发送 {"is_speaking": false} 标识结束。
        本方法重写父类逻辑，识别 is_speaking=false 信号。
        """
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # FunASR 协议不会发送非法 JSON，作为容错处理
            logger.warning(f"[FunASR-Compat] Invalid JSON: {text[:100]}")
            return False

        # 检测结束信号
        if data.get(FunASRMessageField.IS_SPEAKING.value) is False:
            logger.info(
                f"[FunASR-Compat] Client sent is_speaking=false "
                f"for session "
                f"{self.session.session_id if self.session else 'N/A'}"
            )
            return True

        # 其他控制消息（FunASR 协议理论上不会再发其他 JSON）
        # 容错：忽略未知控制消息
        logger.debug(f"[FunASR-Compat] Ignored control message: {data}")
        return False

    async def _init_session(
        self,
        config: StreamingSessionConfig,
    ) -> None:
        """初始化引擎会话（FunASR 兼容版）

        与父类区别：
        - 不发送 STARTED 消息（FunASR 协议无此概念）
        - 客户端通过收到第一条 PARTIAL/FINAL 结果确认会话已启动
        """
        # 确定引擎类型
        engine_type = self._resolve_engine(config)
        self.backend = get_streaming_backend(engine_type)

        # 检查可用性
        if not await self.backend.is_available():
            raise EngineUnavailableError(
                engine_type,
                "Engine check failed"
            )

        # 启动会话（不发送 STARTED 消息）
        self.session = await self.backend.start_session(config)

    async def _push_results_loop(self) -> None:
        """推送 FunASR 格式的识别结果

        将 bookroom-audio 的 PartialMessage/FinalMessage 转换为
        FunASR 服务端响应格式。
        """
        if self.session is None or self.backend is None:
            return

        async for result in self.backend.recv_results(self.session):
            # 跳过空文本的非 final 消息（避免推送无意义的空 PARTIAL）
            if not result.is_final and not result.text:
                continue

            # 构造 FunASR 响应
            if result.is_final:
                # 句末最终结果 → 2pass-offline
                funasr_msg: Dict[str, Any] = {
                    FunASRMessageField.MODE.value:
                        FunASRResponseMode.TWO_PASS_OFFLINE.value,
                    FunASRMessageField.WAV_NAME.value: self._wav_name,
                    FunASRMessageField.TEXT.value: result.text,
                    FunASRMessageField.IS_FINAL.value: True,
                }
            else:
                # 实时中间结果 → 2pass-online
                funasr_msg = {
                    FunASRMessageField.MODE.value:
                        FunASRResponseMode.TWO_PASS_ONLINE.value,
                    FunASRMessageField.WAV_NAME.value: self._wav_name,
                    FunASRMessageField.TEXT.value: result.text,
                    FunASRMessageField.IS_FINAL.value: False,
                }

            # 词级时间戳（如果引擎返回了）
            if result.words:
                timestamp_arr = []
                for w in result.words:
                    timestamp_arr.append([w.start_ms, w.end_ms])
                funasr_msg[FunASRMessageField.TIMESTAMP.value] = json.dumps(
                    timestamp_arr
                )

            await self._send_message(funasr_msg)

    async def _send_error(
        self,
        code: ErrorCode,
        message: str,
    ) -> None:
        """发送 FunASR 风格错误消息

        FunASR 协议没有标准错误消息格式，我们使用与结果类似的
        结构但附加 error 字段，便于客户端识别。
        """
        funasr_msg = {
            FunASRMessageField.MODE.value: "",
            FunASRMessageField.WAV_NAME.value: self._wav_name,
            FunASRMessageField.TEXT.value: f"[error:{code.value}] {message}",
            FunASRMessageField.IS_FINAL.value: True,
            "error": True,
            "error_code": code.value,
        }
        await self._send_message(funasr_msg)

    async def _cleanup(self) -> None:
        """清理资源（FunASR 兼容版）

        与父类区别：
        - 不发送 CLOSED 消息（FunASR 协议无此概念）
        - 直接关闭 WebSocket
        """
        # 1. 停止会话（推送 FINAL 结果到队列）
        if self.session is not None and self.backend is not None:
            try:
                await self.backend.stop_session(self.session)
            except Exception as e:
                logger.warning(f"[FunASR-Compat] Stop session error: {e}")

        # 2. 等待推送循环处理完队列中的 FINAL 结果
        if self._push_task is not None and not self._push_task.done():
            try:
                await asyncio.wait_for(self._push_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "[FunASR-Compat] Push task timeout, cancelling"
                )
                self._push_task.cancel()
                try:
                    await self._push_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

        # 3. 标记关闭
        self._is_closing = True

        # 4. 不发送 CLOSED 消息，直接关闭 WebSocket
        if self.websocket.client_state == WebSocketState.CONNECTED:
            try:
                await self.websocket.close()
            except Exception:
                pass
