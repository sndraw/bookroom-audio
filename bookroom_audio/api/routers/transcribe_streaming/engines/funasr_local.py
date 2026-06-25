"""
FunASR 本地后端
进程内加载 FunASR AutoModel，通过 chunk + cache 模式实现流式
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
    DEFAULT_CHUNK_SIZE,
    DEFAULT_ENCODER_CHUNK_LOOK_BACK,
    DEFAULT_DECODER_CHUNK_LOOK_BACK,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_CHUNK_MS,
    PCM_BYTES_PER_MS,
)
from bookroom_audio.utils.config import get_config
from bookroom_audio.utils.utils_api import logger


# 模型单例 + 延迟加载
_funasr_model: Optional[Any] = None
_funasr_lock = threading.Lock()
_funasr_available: Optional[bool] = None

# 标点恢复模型单例（仅在 enable_punc=True 时加载）
_punc_model: Optional[Any] = None
_punc_lock = threading.Lock()


def _check_funasr_available() -> bool:
    """检查 funasr 包是否可导入"""
    global _funasr_available
    if _funasr_available is None:
        try:
            import funasr  # noqa: F401
            _funasr_available = True
        except ImportError:
            _funasr_available = False
    return _funasr_available


def _get_punc_model() -> Optional[Any]:
    """获取或加载标点恢复模型（单例）

    仅当配置启用标点恢复时加载。用于对 FINAL 整句文本加标点。
    """
    global _punc_model

    if _punc_model is None:
        with _punc_lock:
            if _punc_model is None:
                config = get_config()
                if not config.model.streaming_enable_punc:
                    return None

                punc_model_name = (
                    config.model.streaming_punc_model
                    or DefaultModel.FUNASR_PUNC.value
                )
                logger.info(f"Loading FunASR punc model: {punc_model_name}")

                from funasr import AutoModel
                _punc_model = AutoModel(
                    model=punc_model_name,
                    device=config.model.device,
                    disable_update=True,
                    hub="ms",
                )
                logger.info("FunASR punc model loaded")

    return _punc_model


def _apply_punc(text: str) -> str:
    """对整句文本应用标点恢复

    加载标点恢复模型，对输入文本加标点。
    失败时返回原始文本。
    """
    if not text or not text.strip():
        return text

    try:
        punc_model = _get_punc_model()
        if punc_model is None:
            return text

        results = punc_model.generate(input=text)
        if results:
            return results[0].get("text", text)
    except Exception as e:
        logger.warning(f"[FunASR-Local] Punc failed: {e}")

    return text


def _get_funasr_model() -> Any:
    """获取或加载 FunASR 流式模型（单例）"""
    global _funasr_model

    if _funasr_model is None:
        with _funasr_lock:
            if _funasr_model is None:
                if not _check_funasr_available():
                    raise EngineUnavailableError(
                        StreamingASREngine.FUNASR_LOCAL,
                        "funasr package not installed. "
                        "Run: pip install funasr"
                    )

                config = get_config()
                streaming_model = (
                    config.model.streaming_asr_model
                    or DefaultModel.FUNASR_STREAMING.value
                )

                logger.info(
                    f"Loading FunASR streaming model: asr={streaming_model} "
                    f"(punc 在 FINAL 时单独调用)"
                )

                from funasr import AutoModel

                # 流式 ASR 通过 chunk_size + cache 控制流式。
                # 不在 AutoModel 中加 punc_model，避免 PARTIAL 增量被加标点。
                # 标点恢复在 FINAL 时单独加载 punc 模型处理（见 _apply_punc）。
                model_kwargs: Dict[str, Any] = {
                    "model": streaming_model,
                    "device": config.model.device,
                    "disable_update": True,
                    # funasr 官方预训练模型托管在 ModelScope，始终使用 ms 源
                    "hub": "ms",
                }

                _funasr_model = AutoModel(**model_kwargs)
                logger.info("FunASR streaming model loaded")

    return _funasr_model


class FunASRLocalBackend(StreamingASRBackend):
    """FunASR 本地后端

    进程内加载 FunASR AutoModel（paraformer-zh-streaming + fsmn-vad + ct-punc），
    通过 chunk + cache 机制实现流式识别。

    工作流程：
    1. 累积音频到 600ms
    2. 调用 model.generate() 传入 cache 字典
    3. 解析返回结果推送到会话队列
    """

    @property
    def engine_type(self) -> StreamingASREngine:
        return StreamingASREngine.FUNASR_LOCAL

    async def is_available(self) -> bool:
        """检查 FunASR 本地是否可用"""
        return _check_funasr_available()

    async def start_session(
        self,
        config: StreamingSessionConfig,
    ) -> StreamingSession:
        """启动新会话，初始化 cache

        预加载模型：失败时立即抛异常，让客户端在 STARTED 阶段收到 ERROR
        """
        if not _check_funasr_available():
            raise EngineUnavailableError(
                self.engine_type,
                "funasr package not installed"
            )

        # 预加载模型（首次会下载，可能耗时），失败立即反馈
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, _get_funasr_model)
        except EngineUnavailableError:
            raise
        except Exception as e:
            raise EngineUnavailableError(
                self.engine_type,
                f"Model load failed: {type(e).__name__}: {e}"
            ) from e

        session = self._create_session(config)

        # 每个 session 维护独立的 cache
        cache: Dict[str, Any] = {}
        setattr(session, "_cache", cache)
        setattr(session, "_audio_buffer", bytearray())
        setattr(session, "_sentence_count", 0)

        return session

    async def send_audio(
        self,
        session: StreamingSession,
        audio_chunk: bytes,
    ) -> None:
        """累积音频，达到阈值后调用模型"""
        buffer: bytearray = getattr(session, "_audio_buffer")
        buffer.extend(audio_chunk)
        session.total_audio_ms += len(audio_chunk) // PCM_BYTES_PER_MS

        chunk_ms = getattr(session.config, "_effective_chunk_ms", DEFAULT_CHUNK_MS)
        bytes_per_chunk = chunk_ms * PCM_BYTES_PER_MS

        # 累积达到一个 chunk 大小后推理
        while len(buffer) >= bytes_per_chunk:
            chunk_data = bytes(buffer[:bytes_per_chunk])
            del buffer[:bytes_per_chunk]

            # 异步执行同步推理
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._infer_chunk,
                session,
                chunk_data,
            )

            if result is not None:
                session.push_result(result)

    def _infer_chunk(
        self,
        session: StreamingSession,
        audio_chunk: bytes,
    ) -> Optional[ASRResult]:
        """调用 FunASR 模型推理单个 chunk"""
        try:
            model = _get_funasr_model()
            cache: Dict[str, Any] = getattr(session, "_cache")

            chunk_size = (
                session.config.chunk_size
                or DEFAULT_CHUNK_SIZE
            )

            results = model.generate(
                input=audio_chunk,
                cache=cache,
                chunk_size=chunk_size,
                encoder_chunk_look_back=DEFAULT_ENCODER_CHUNK_LOOK_BACK,
                decoder_chunk_look_back=DEFAULT_DECODER_CHUNK_LOOK_BACK,
                is_final=False,
            )

            if not results:
                return None

            result = results[0]
            text = result.get("text", "")
            if not text:
                return None

            # 判断是否为新句
            sentence_id = result.get("sentence_id", 0)
            is_final = result.get("is_final", False)

            asr_result = ASRResult(
                text=text,
                is_final=is_final,
                sentence_id=sentence_id,
                start_ms=result.get("timestamp", [[0]])[0][0]
                if result.get("timestamp") else 0,
                end_ms=session.total_audio_ms,
            )

            # 保存最后一次 PARTIAL 结果，用于停止时生成 FINAL
            if not is_final:
                setattr(session, "_last_partial", asr_result)
                # 累积所有 PARTIAL 文本，用于 STOP 时拼接整句
                accumulated: str = getattr(
                    session, "_accumulated_text", ""
                )
                accumulated += text
                setattr(session, "_accumulated_text", accumulated)

            return asr_result

        except Exception as e:
            logger.error(
                f"[FunASR-Local] Inference error: {e}",
                exc_info=True,
            )
            session.push_result(ASRResult(
                text=f"[引擎推理错误] {type(e).__name__}: {e}",
                is_final=True,
                sentence_id=-1,
                start_ms=0,
                end_ms=session.total_audio_ms,
            ))
            return None

    async def recv_results(
        self,
        session: StreamingSession,
    ) -> AsyncIterator[ASRResult]:
        """从会话队列读取结果

        即使 session 已 stopped，也处理完队列中剩余结果，
        确保 FINAL 结果能送达客户端。
        """
        while True:
            # stopped 后仍要处理队列剩余结果
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
        """停止会话，处理剩余缓冲并生成最终结果

        按 funasr 官方流式示例，即使无剩余音频，也要调用
        model.generate(input=[], cache=cache, is_final=True)
        来触发最终 flush。

        FINAL 结果为所有 PARTIAL 累积文本经标点恢复后的整句。
        """
        buffer: bytearray = getattr(session, "_audio_buffer", bytearray())

        # 1. flush 最后一段音频（处理残留 cache）
        try:
            loop = asyncio.get_event_loop()
            flush_result = await loop.run_in_executor(
                None,
                self._infer_final,
                session,
                bytes(buffer),
            )
            # flush 结果追加到累积文本
            if flush_result is not None and flush_result.text:
                accumulated: str = getattr(
                    session, "_accumulated_text", ""
                )
                accumulated += flush_result.text
                setattr(session, "_accumulated_text", accumulated)
        except Exception as e:
            logger.error(
                f"[FunASR-Local] Final inference error: {e}"
            )

        # 2. 用累积文本 + 标点恢复构建 FINAL 结果
        accumulated_text: str = getattr(
            session, "_accumulated_text", ""
        )
        last_partial = getattr(session, "_last_partial", None)

        if accumulated_text:
            # 对整句应用标点恢复
            final_text = await loop.run_in_executor(
                None,
                _apply_punc,
                accumulated_text,
            )
            session.push_result(ASRResult(
                text=final_text,
                is_final=True,
                sentence_id=last_partial.sentence_id if last_partial else 0,
                start_ms=last_partial.start_ms if last_partial else 0,
                end_ms=session.total_audio_ms,
            ))
        elif last_partial is not None:
            # 无累积文本时，使用最后一次 PARTIAL + 标点
            final_text = await loop.run_in_executor(
                None,
                _apply_punc,
                last_partial.text,
            )
            session.push_result(ASRResult(
                text=final_text,
                is_final=True,
                sentence_id=last_partial.sentence_id,
                start_ms=last_partial.start_ms,
                end_ms=session.total_audio_ms,
            ))

        session.mark_stopped()
        logger.info(
            f"[FunASR-Local] Session {session.session_id} closed"
        )

    def _infer_final(
        self,
        session: StreamingSession,
        audio_chunk: bytes,
    ) -> Optional[ASRResult]:
        """处理最后一段音频（flush 残留）"""
        try:
            model = _get_funasr_model()
            cache: Dict[str, Any] = getattr(session, "_cache")

            chunk_size = (
                session.config.chunk_size
                or DEFAULT_CHUNK_SIZE
            )

            # 流式模型即使 flush 也需要 chunk_size 等参数，
            # 否则 funasr 内部无法正确解码残留 cache
            results = model.generate(
                input=audio_chunk,
                cache=cache,
                chunk_size=chunk_size,
                encoder_chunk_look_back=DEFAULT_ENCODER_CHUNK_LOOK_BACK,
                decoder_chunk_look_back=DEFAULT_DECODER_CHUNK_LOOK_BACK,
                is_final=True,
            )

            if not results:
                return None

            result = results[0]
            text = result.get("text", "")
            if not text:
                return None

            return ASRResult(
                text=text,
                is_final=True,
                sentence_id=result.get("sentence_id", 0),
                start_ms=0,
                end_ms=session.total_audio_ms,
            )
        except Exception as e:
            logger.error(
                f"[FunASR-Local] Final error: {e}",
                exc_info=True,
            )
            return None
