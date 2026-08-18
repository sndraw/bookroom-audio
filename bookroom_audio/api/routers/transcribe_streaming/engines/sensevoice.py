"""
SenseVoice 本地后端
进程内加载 SenseVoice 模型，通过 VAD 检测端点后分块识别
模拟流式效果
"""

import asyncio
import threading
from typing import AsyncIterator, Optional, Dict, Any, List

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
    DefaultModel,
    DEFAULT_SAMPLE_RATE,
    PCM_BYTES_PER_MS,
    DEFAULT_VAD_SILENCE_MS,
)
from bookroom_audio.utils.config import get_config
from bookroom_audio.utils.utils_api import logger


# 模型单例
_sensevoice_model: Optional[Any] = None
_vad_model: Optional[Any] = None
_sensevoice_lock = threading.Lock()
_sensevoice_available: Optional[bool] = None


def _check_sensevoice_available() -> bool:
    """检查 SenseVoice（通过 funasr 包）是否可用"""
    global _sensevoice_available
    if _sensevoice_available is None:
        try:
            import funasr  # noqa: F401
            _sensevoice_available = True
        except ImportError:
            _sensevoice_available = False
    return _sensevoice_available


def _get_sensevoice_model() -> Any:
    """获取或加载 SenseVoice 模型（单例）"""
    global _sensevoice_model

    if _sensevoice_model is None:
        with _sensevoice_lock:
            if _sensevoice_model is None:
                if not _check_sensevoice_available():
                    raise EngineUnavailableError(
                        StreamingASREngine.SENSE_VOICE_LOCAL,
                        "funasr package not installed. "
                        "Run: pip install funasr"
                    )

                config = get_config()
                model_name = (
                    config.model.streaming_sensevoice_model
                    or DefaultModel.SENSE_VOICE.value
                )

                logger.info(
                    f"Loading SenseVoice model: {model_name}"
                )

                from funasr import AutoModel

                model_kwargs: Dict[str, Any] = {
                    "model": model_name,
                    "device": config.model.device,
                    "disable_update": True,
                    # SenseVoice 模型托管在 ModelScope，始终使用 ms 源
                    "hub": "ms",
                }

                _sensevoice_model = AutoModel(**model_kwargs)
                logger.info("SenseVoice model loaded")

    return _sensevoice_model


def _get_vad_model() -> Any:
    """获取或加载 VAD 模型（单例，供 SenseVoice 使用）"""
    global _vad_model

    if _vad_model is None:
        with _sensevoice_lock:
            if _vad_model is None:
                if not _check_sensevoice_available():
                    raise EngineUnavailableError(
                        StreamingASREngine.SENSE_VOICE_LOCAL,
                        "funasr package not installed"
                    )

                config = get_config()
                vad_name = (
                    config.model.streaming_vad_model
                    or DefaultModel.FUNASR_VAD.value
                )

                logger.info(f"Loading VAD model: {vad_name}")

                from funasr import AutoModel

                vad_kwargs: Dict[str, Any] = {
                    "model": vad_name,
                    "device": config.model.device,
                    "disable_update": True,
                    # VAD 模型托管在 ModelScope，始终使用 ms 源
                    "hub": "ms",
                }

                _vad_model = AutoModel(**vad_kwargs)
                logger.info("VAD model loaded")

    return _vad_model


class SenseVoiceLocalBackend(StreamingASRBackend):
    """SenseVoice 本地后端

    SenseVoice 本身是非流式模型，本后端通过 VAD 检测语音端点，
    在端点处触发 SenseVoice 识别，模拟流式效果。

    工作流程：
    1. 累积音频
    2. 定期调用 VAD 检测端点
    3. 检测到端点后，提取该段音频调用 SenseVoice
    4. 输出最终结果

    优势：SenseVoice 极速（10s 音频 70ms），支持情感和事件检测
    劣势：延迟比真流式高（需等待 VAD 断句）
    """

    @property
    def engine_type(self) -> StreamingASREngine:
        return StreamingASREngine.SENSE_VOICE_LOCAL

    async def is_available(self) -> bool:
        """检查 SenseVoice 是否可用"""
        return _check_sensevoice_available()

    async def start_session(
        self,
        config: StreamingSessionConfig,
    ) -> StreamingSession:
        """启动新会话，预加载模型

        预加载失败立即抛异常，让客户端在 STARTED 阶段收到 ERROR
        """
        if not _check_sensevoice_available():
            raise EngineUnavailableError(
                self.engine_type,
                "funasr package not installed"
            )

        # 预加载 SenseVoice 与 VAD 模型（首次会下载，可能耗时）
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, _get_sensevoice_model)
            await loop.run_in_executor(None, _get_vad_model)
        except EngineUnavailableError:
            raise
        except Exception as e:
            raise EngineUnavailableError(
                self.engine_type,
                f"Model load failed: {type(e).__name__}: {e}"
            ) from e

        session = self._create_session(config)
        setattr(session, "_audio_buffer", bytearray())
        setattr(session, "_vad_cache", {})
        setattr(session, "_sentence_count", 0)
        setattr(session, "_last_vad_ms", 0)
        # 已识别到的音频位置（毫秒），避免重复识别
        setattr(session, "_last_processed_ms", 0)
        return session

    async def send_audio(
        self,
        session: StreamingSession,
        audio_chunk: bytes,
    ) -> None:
        """累积音频并定期 VAD 检测"""
        buffer: bytearray = getattr(session, "_audio_buffer")
        buffer.extend(audio_chunk)
        session.total_audio_ms += len(audio_chunk) // PCM_BYTES_PER_MS

        # 每 500ms 检测一次端点
        vad_interval_ms = 500
        last_vad_ms: int = getattr(session, "_last_vad_ms", 0)
        if session.total_audio_ms - last_vad_ms < vad_interval_ms:
            return

        setattr(session, "_last_vad_ms", session.total_audio_ms)

        # 异步执行 VAD 检测
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._detect_and_recognize,
            session,
        )

    def _detect_and_recognize(self, session: StreamingSession) -> None:
        """VAD 检测端点，识别完成的句子"""
        buffer: bytearray = getattr(session, "_audio_buffer")
        if len(buffer) < PCM_BYTES_PER_MS * 1000:
            return  # 至少 1 秒音频

        try:
            vad_model = _get_vad_model()
            vad_cache: Dict[str, Any] = getattr(session, "_vad_cache")

            silence_ms = (
                session.config.max_sentence_silence_ms
                or DEFAULT_VAD_SILENCE_MS
            )

            # VAD 切分（chunk_size 为 int 毫秒值，而非列表）
            vad_results = vad_model.generate(
                input=bytes(buffer),
                cache=vad_cache,
                is_final=False,
                chunk_size=100,
                max_single_segment_time=60000,
            )

            completed_segments = self._extract_completed_segments(
                vad_results,
                session,
            )

            for segment_audio, start_ms, end_ms in completed_segments:
                self._recognize_segment(
                    session,
                    segment_audio,
                    start_ms,
                    end_ms,
                )

        except Exception as e:
            logger.error(
                f"[SenseVoice] VAD error: {e}",
                exc_info=True,
            )
            # 推送错误信息让客户端可见
            session.push_result(ASRResult(
                text=f"[VAD错误] {type(e).__name__}: {e}",
                is_final=True,
                sentence_id=-1,
                start_ms=0,
                end_ms=session.total_audio_ms,
            ))

    def _extract_completed_segments(
        self,
        vad_results: List[Dict[str, Any]],
        session: StreamingSession,
    ) -> List[tuple[bytes, int, int]]:
        """从 VAD 结果提取已完成的语音段

        fsmn-vad 返回 value=[[start_ms, end_ms], ...]，最后一个段是
        "活跃段"（尚未结束），除非 is_final=True。前面的段都已完成。

        通过 _last_processed_ms 跳过已识别的段，避免重复识别。
        """
        segments: List[tuple[bytes, int, int]] = []
        buffer: bytearray = getattr(session, "_audio_buffer")
        last_processed_ms: int = getattr(session, "_last_processed_ms", 0)

        for vad_res in vad_results:
            value = vad_res.get("value", [])
            if not value:
                continue

            is_final = vad_res.get("is_final", False)
            # is_final=True 时所有段都已完成；否则最后一个是活跃段
            last_idx = len(value) if is_final else max(len(value) - 1, 0)

            for idx in range(last_idx):
                segment_info = value[idx]
                if not isinstance(segment_info, list):
                    continue
                if len(segment_info) < 2:
                    continue

                start_ms = int(segment_info[0])
                end_ms = int(segment_info[1])

                # 跳过已处理的段
                if end_ms <= last_processed_ms:
                    continue

                start_byte = max(start_ms, last_processed_ms) * PCM_BYTES_PER_MS
                end_byte = end_ms * PCM_BYTES_PER_MS

                if end_byte > len(buffer):
                    continue

                segment_audio = bytes(buffer[start_byte:end_byte])
                if len(segment_audio) > 0:
                    segments.append((segment_audio, start_ms, end_ms))
                    if end_ms > last_processed_ms:
                        last_processed_ms = end_ms

        setattr(session, "_last_processed_ms", last_processed_ms)
        return segments

    def _recognize_segment(
        self,
        session: StreamingSession,
        audio_bytes: bytes,
        start_ms: int,
        end_ms: int,
    ) -> None:
        """识别单个语音段"""
        try:
            model = _get_sensevoice_model()
            sentence_count: int = getattr(session, "_sentence_count", 0)

            results = model.generate(
                input=audio_bytes,
                cache={},
                language=session.config.language,
                use_itn=session.config.enable_itn,
            )

            if not results:
                return

            result = results[0]
            text = self._postprocess_text(result.get("text", ""))

            if not text:
                return

            # 解析 SenseVoice 的情感/语种标签
            emotion = None
            if session.config.enable_emotion:
                emotion = self._extract_emotion(text)
                text = self._strip_tags(text)

            sentence_count += 1
            setattr(session, "_sentence_count", sentence_count)

            session.push_result(ASRResult(
                text=text,
                is_final=True,
                sentence_id=sentence_count,
                start_ms=start_ms,
                end_ms=end_ms,
                emotion=emotion,
            ))

        except Exception as e:
            logger.error(
                f"[SenseVoice] Recognition error: {e}",
                exc_info=True,
            )
            # 推送错误信息让客户端可见
            session.push_result(ASRResult(
                text=f"[识别错误] {type(e).__name__}: {e}",
                is_final=True,
                sentence_id=-1,
                start_ms=start_ms,
                end_ms=end_ms,
            ))

    def _postprocess_text(self, text: str) -> str:
        """SenseVoice 文本后处理"""
        if not text:
            return ""
        # 去除开头可能的多余空格
        return text.strip()

    def _extract_emotion(self, text: str) -> Optional[str]:
        """从 SenseVoice 输出提取情感标签"""
        # SenseVoice 输出格式：<|zh|><|HAPPY|>实际文本
        emotion_tags = ["HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL", "DISGUSTED", "SURPRISED"]
        for tag in emotion_tags:
            tag_str = f"<|{tag}|>"
            if tag_str in text:
                return tag.lower()
        return None

    def _strip_tags(self, text: str) -> str:
        """去除 SenseVoice 输出中的特殊标签"""
        import re
        return re.sub(r"<\|[^|]+\|>", "", text).strip()

    async def recv_results(
        self,
        session: StreamingSession,
    ) -> AsyncIterator[ASRResult]:
        """从会话队列读取结果

        即使 session 已 stopped，也处理完队列中剩余结果，
        确保 FINAL 结果能送达客户端。
        """
        while True:
            if session.is_stopped() and session.result_queue.empty():
                break
            try:
                result = await asyncio.wait_for(
                    session.result_queue.get(),
                    timeout=1.0,
                )
                yield result
            except asyncio.TimeoutError:
                continue

    async def stop_session(self, session: StreamingSession) -> None:
        """停止会话，处理剩余音频

        只识别 _last_processed_ms 之后的未识别部分，避免重复识别。
        """
        buffer: bytearray = getattr(session, "_audio_buffer", bytearray())
        last_processed_ms: int = getattr(session, "_last_processed_ms", 0)
        last_processed_byte = last_processed_ms * PCM_BYTES_PER_MS

        # 只处理未识别的部分
        if len(buffer) > last_processed_byte:
            remaining_audio = bytes(buffer[last_processed_byte:])
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._recognize_segment,
                session,
                remaining_audio,
                last_processed_ms,
                session.total_audio_ms,
            )

        session.mark_stopped()
        logger.info(
            f"[SenseVoice] Session {session.session_id} closed"
        )
