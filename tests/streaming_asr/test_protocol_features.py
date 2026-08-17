"""
流式 ASR 新增功能单元测试（不依赖模型与真实服务器）

覆盖功能：
1. 心跳保活：PING → PONG（回显 client_time_ms）
2. 暂停/恢复：PAUSE → PAUSED、RESUME → RESUMED、重复请求忽略
3. 暂停期间丢弃音频，不转发引擎
4. 心跳超时断开：超过 WS_HEARTBEAT_TIMEOUT_SECONDS 无消息则报错断开
5. 任意消息更新保活时间戳
6. FunASR 2pass 字级时间戳解析（_parse_offline_timestamps）
7. FunASR 2pass 离线识别（_infer_offline_full，mock 模型）
8. SenseVoice VAD 段去重（_extract_completed_segments / _last_processed_ms）
9. SenseVoice stop_session 只识别未处理部分

运行方式（项目根目录）：
  python -m unittest tests.streaming_asr.test_protocol_features -v
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from bookroom_audio.api.routers.transcribe_streaming import streaming
from bookroom_audio.api.routers.transcribe_streaming.constants import (
    ClientMessageType,
    ErrorCode,
    PCM_BYTES_PER_MS,
    ServerMessageType,
)
from bookroom_audio.api.routers.transcribe_streaming.engines.base import (
    StreamingSession,
)
from bookroom_audio.api.routers.transcribe_streaming.engines.funasr_local import (
    _infer_offline_full,
    _parse_offline_timestamps,
)
from bookroom_audio.api.routers.transcribe_streaming.engines.sensevoice import (
    SenseVoiceLocalBackend,
)
from bookroom_audio.api.routers.transcribe_streaming.schemas import (
    StreamingSessionConfig,
)

from starlette.websockets import WebSocketState


# ==================== 测试替身 ====================

class FakeWebSocket:
    """模拟 starlette WebSocket：记录发送的消息，支持注入接收队列"""

    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent_texts: list[str] = []
        # (消息字典 | 异常) 队列，None 表示挂起等待
        self._recv_queue: list[dict | BaseException] = []

    async def accept(self) -> None:
        self.client_state = WebSocketState.CONNECTED

    async def receive(self) -> dict:
        if self._recv_queue:
            item = self._recv_queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        # 挂起，直到超时（由 asyncio.wait_for 触发）
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)

    async def close(self) -> None:
        self.client_state = WebSocketState.DISCONNECTED

    # ---------- 测试辅助 ----------

    def parsed_messages(self) -> list[dict]:
        return [json.loads(t) for t in self.sent_texts]

    def messages_of_type(self, msg_type: str) -> list[dict]:
        return [m for m in self.parsed_messages() if m.get("type") == msg_type]

    def queue_text(self, text: str) -> None:
        self._recv_queue.append({"type": "websocket.receive", "text": text})

    def queue_bytes(self, data: bytes) -> None:
        self._recv_queue.append({"type": "websocket.receive", "bytes": data})


class FakeBackend:
    """记录 send_audio / stop_session 调用的假引擎后端"""

    def __init__(self) -> None:
        self.send_calls: list[bytes] = []
        self.stop_calls = 0

    async def send_audio(self, session: StreamingSession, chunk: bytes) -> None:
        self.send_calls.append(bytes(chunk))

    async def stop_session(self, session: StreamingSession) -> None:
        self.stop_calls += 1


def make_session() -> StreamingSession:
    """构造一个可直接使用的会话上下文"""
    return StreamingSession("test-session", StreamingSessionConfig())


def make_handler() -> tuple[streaming.StreamingConnectionHandler, FakeWebSocket]:
    ws = FakeWebSocket()
    handler = streaming.StreamingConnectionHandler(ws)
    return handler, ws


# ==================== 心跳保活 ====================

class TestPingPong(unittest.IsolatedAsyncioTestCase):
    async def test_ping_returns_pong_with_echo(self) -> None:
        handler, ws = make_handler()
        handler.session = make_session()

        await handler._handle_ping({"type": "ping", "timestamp_ms": 12345})

        pongs = ws.messages_of_type(ServerMessageType.PONG.value)
        self.assertEqual(len(pongs), 1)
        self.assertEqual(pongs[0]["client_time_ms"], 12345)
        self.assertGreater(pongs[0]["server_time_ms"], 0)
        self.assertEqual(pongs[0]["session_id"], "test-session")

    async def test_ping_without_session(self) -> None:
        handler, ws = make_handler()
        await handler._handle_ping({"type": "ping"})

        pongs = ws.messages_of_type(ServerMessageType.PONG.value)
        self.assertEqual(len(pongs), 1)
        self.assertIsNone(pongs[0]["session_id"])


class TestPauseResume(unittest.IsolatedAsyncioTestCase):
    async def test_pause_sends_paused_and_sets_flag(self) -> None:
        handler, ws = make_handler()
        handler.session = make_session()

        await handler._handle_pause()

        self.assertTrue(handler._paused)
        paused_msgs = ws.messages_of_type(ServerMessageType.PAUSED.value)
        self.assertEqual(len(paused_msgs), 1)
        self.assertEqual(paused_msgs[0]["session_id"], "test-session")

    async def test_repeated_pause_ignored(self) -> None:
        handler, ws = make_handler()
        handler.session = make_session()

        await handler._handle_pause()
        await handler._handle_pause()

        self.assertEqual(
            len(ws.messages_of_type(ServerMessageType.PAUSED.value)),
            1,
        )

    async def test_resume_sends_resumed_and_clears_flag(self) -> None:
        handler, ws = make_handler()
        handler.session = make_session()

        await handler._handle_pause()
        await handler._handle_resume()

        self.assertFalse(handler._paused)
        resumed_msgs = ws.messages_of_type(ServerMessageType.RESUMED.value)
        self.assertEqual(len(resumed_msgs), 1)
        self.assertEqual(resumed_msgs[0]["session_id"], "test-session")

    async def test_resume_without_pause_ignored(self) -> None:
        handler, ws = make_handler()
        handler.session = make_session()

        await handler._handle_resume()

        self.assertEqual(
            len(ws.messages_of_type(ServerMessageType.RESUMED.value)),
            0,
        )

    async def test_pause_drops_audio(self) -> None:
        """暂停期间音频不转发到引擎"""
        handler, ws = make_handler()
        handler.session = make_session()
        backend = FakeBackend()
        handler.backend = backend

        handler._paused = True
        await handler._handle_audio_chunk(b"\x00" * 3200)

        self.assertEqual(len(backend.send_calls), 0)

    async def test_audio_forwarded_when_not_paused(self) -> None:
        handler, ws = make_handler()
        handler.session = make_session()
        backend = FakeBackend()
        handler.backend = backend

        await handler._handle_audio_chunk(b"\x01\x02" * 1600)

        self.assertEqual(len(backend.send_calls), 1)
        self.assertEqual(backend.send_calls[0], b"\x01\x02" * 1600)


# ==================== 心跳超时 ====================

class TestHeartbeatTimeout(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_sends_error_and_exits(self) -> None:
        """超过心跳阈值未收到任何消息 → 发 ERROR 并退出接收循环"""
        handler, ws = make_handler()

        with patch.object(
            streaming,
            "WS_HEARTBEAT_TIMEOUT_SECONDS",
            0.05,
        ):
            await handler._receive_audio_loop()

        errors = ws.messages_of_type(ServerMessageType.ERROR.value)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], ErrorCode.SESSION_NOT_FOUND.value)
        self.assertIn("Heartbeat timeout", errors[0]["message"])

    async def test_any_message_updates_last_recv_time(self) -> None:
        """收到任意消息（含 PING）都会刷新保活时间戳"""
        handler, ws = make_handler()
        handler.session = make_session()

        ws.queue_text(json.dumps({"type": "ping", "timestamp_ms": 1}))
        ws.queue_text(json.dumps({"type": "stop"}))
        await handler._receive_audio_loop()

        self.assertGreater(handler._last_recv_time, 0)
        # PING 被应答，STOP 使循环退出
        self.assertEqual(len(ws.messages_of_type(ServerMessageType.PONG.value)), 1)


# ==================== FunASR 2pass 字级时间戳 ====================

class TestParseOfflineTimestamps(unittest.TestCase):
    def test_parse_valid_timestamps(self) -> None:
        words = _parse_offline_timestamps([[0, 100], [100, 200], [200, 300]])
        self.assertEqual(len(words), 3)
        self.assertEqual(words[0].text, "")
        self.assertEqual(words[0].start_ms, 0)
        self.assertEqual(words[0].end_ms, 100)
        self.assertEqual(words[1].start_ms, 100)
        self.assertEqual(words[2].end_ms, 300)

    def test_parse_none_or_empty(self) -> None:
        self.assertEqual(_parse_offline_timestamps(None), [])
        self.assertEqual(_parse_offline_timestamps([]), [])

    def test_parse_invalid_entries_skipped(self) -> None:
        words = _parse_offline_timestamps([[0, 100], "bad", [200]])
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0].start_ms, 0)

    def test_parse_non_numeric_returns_empty(self) -> None:
        # int("a") 抛 ValueError → 整体返回 []
        self.assertEqual(_parse_offline_timestamps([["a", "b"]]), [])


class TestInferOfflineFull(unittest.IsolatedAsyncioTestCase):
    """通过 mock 模型验证 _infer_offline_full 的完整行为"""

    def _make_audio(self, ms: int) -> bytes:
        samples = int(16000 * ms / 1000)
        return np.zeros(samples, dtype=np.int16).tobytes()

    def test_success_returns_text_and_words(self) -> None:
        fake_model = MagicMock()
        fake_model.generate.return_value = [{
            "text": "你 好 世 界",
            "timestamp": [[0, 100], [100, 200], [200, 300], [300, 400]],
        }]
        with patch(
            "bookroom_audio.api.routers.transcribe_streaming.engines."
            "funasr_local._get_offline_model",
            return_value=fake_model,
        ):
            result = _infer_offline_full(self._make_audio(400))

        self.assertIsNotNone(result)
        text, words = result
        # 空格被去除还原自然文本
        self.assertEqual(text, "你好世界")
        self.assertEqual(len(words), 4)

        # 验证以 output_timestamp=True 调用模型
        kwargs = fake_model.generate.call_args.kwargs
        self.assertTrue(kwargs.get("output_timestamp"))

    def test_empty_audio_returns_none(self) -> None:
        self.assertIsNone(_infer_offline_full(b""))

    def test_model_unavailable_returns_none(self) -> None:
        with patch(
            "bookroom_audio.api.routers.transcribe_streaming.engines."
            "funasr_local._get_offline_model",
            return_value=None,
        ):
            self.assertIsNone(_infer_offline_full(self._make_audio(100)))

    def test_empty_text_returns_none(self) -> None:
        fake_model = MagicMock()
        fake_model.generate.return_value = [{"text": "", "timestamp": []}]
        with patch(
            "bookroom_audio.api.routers.transcribe_streaming.engines."
            "funasr_local._get_offline_model",
            return_value=fake_model,
        ):
            self.assertIsNone(_infer_offline_full(self._make_audio(100)))

    def test_generate_exception_returns_none(self) -> None:
        fake_model = MagicMock()
        fake_model.generate.side_effect = RuntimeError("model crash")
        with patch(
            "bookroom_audio.api.routers.transcribe_streaming.engines."
            "funasr_local._get_offline_model",
            return_value=fake_model,
        ):
            self.assertIsNone(_infer_offline_full(self._make_audio(100)))


# ==================== SenseVoice 去重 ====================

class TestSenseVoiceDedup(unittest.IsolatedAsyncioTestCase):
    def _make_backend_and_session(self, buffer_ms: int = 2000):
        backend = SenseVoiceLocalBackend()
        session = StreamingSession("sv-test", StreamingSessionConfig())
        setattr(session, "_audio_buffer", bytearray(b"\x00" * (buffer_ms * PCM_BYTES_PER_MS)))
        setattr(session, "_last_processed_ms", 0)
        setattr(session, "_sentence_count", 0)
        session.total_audio_ms = buffer_ms
        return backend, session

    def test_active_segment_excluded_when_not_final(self) -> None:
        """is_final=False 时最后一个活跃段不识别"""
        backend, session = self._make_backend_and_session()
        vad_results = [{
            "value": [[100, 500], [500, 900]],
            "is_final": False,
        }]

        segments = backend._extract_completed_segments(vad_results, session)

        # 只返回第一个已完成的段
        self.assertEqual(len(segments), 1)
        _, start_ms, end_ms = segments[0]
        self.assertEqual(start_ms, 100)
        self.assertEqual(end_ms, 500)
        self.assertEqual(session._last_processed_ms, 500)

    def test_all_segments_when_final(self) -> None:
        backend, session = self._make_backend_and_session()
        vad_results = [{
            "value": [[100, 500], [500, 900]],
            "is_final": True,
        }]

        segments = backend._extract_completed_segments(vad_results, session)

        self.assertEqual(len(segments), 2)
        self.assertEqual(session._last_processed_ms, 900)

    def test_no_repeat_on_second_call(self) -> None:
        """同一 VAD 结果第二次调用不重复识别

        注意：is_final=False 时最后一个段是活跃段，会被排除；
        首次调用只识别第一个段（100-500），第二次调用应全部跳过。
        """
        backend, session = self._make_backend_and_session()
        vad_results = [{
            "value": [[100, 500], [500, 900]],
            "is_final": False,
        }]

        first = backend._extract_completed_segments(vad_results, session)
        second = backend._extract_completed_segments(vad_results, session)

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0][1], 100)
        self.assertEqual(first[0][2], 500)
        self.assertEqual(len(second), 0)

    def test_stop_session_only_recognizes_remaining(self) -> None:
        """stop 时只识别 _last_processed_ms 之后的音频"""
        backend, session = self._make_backend_and_session(buffer_ms=1000)
        setattr(session, "_last_processed_ms", 400)
        recognized = []
        backend._recognize_segment = MagicMock(
            side_effect=lambda *args: recognized.append(args),
        )

        async def run():
            await backend.stop_session(session)

        asyncio.get_event_loop().run_until_complete(run())

        self.assertEqual(len(recognized), 1)
        _, audio, start_ms, end_ms = recognized[0]
        # 只包含 400ms 之后的部分
        self.assertEqual(len(audio), (1000 - 400) * PCM_BYTES_PER_MS)
        self.assertEqual(start_ms, 400)
        self.assertEqual(end_ms, 1000)
        self.assertTrue(session.is_stopped())


if __name__ == "__main__":
    unittest.main()
