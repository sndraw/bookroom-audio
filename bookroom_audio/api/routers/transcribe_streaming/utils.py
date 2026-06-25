"""
流式语音识别音频处理工具
- 音频格式转换（mp3/opus/wav/aac 等 → PCM）
- 采样率重采样
- 音频分块
"""

import io
import asyncio
from typing import Optional

from pydub import AudioSegment

from bookroom_audio.api.routers.transcribe_streaming.constants import (
    AudioFormat,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SAMPLE_WIDTH,
    DEFAULT_CHANNELS,
    PCM_BYTES_PER_MS,
)
from bookroom_audio.utils.utils_api import logger


def decode_to_pcm(
    audio_data: bytes,
    audio_format: AudioFormat,
    target_sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> bytes:
    """
    将各种音频格式解码为统一 PCM（16-bit little-endian, mono）

    Args:
        audio_data: 原始音频字节
        audio_format: 音频格式枚举
        target_sample_rate: 目标采样率

    Returns:
        PCM 字节流
    """
    if audio_format == AudioFormat.PCM:
        # PCM 无需解码，直接返回（假设已是 16k/16bit/mono）
        return audio_data

    try:
        # pydub 格式映射
        format_map = {
            AudioFormat.WAV: "wav",
            AudioFormat.MP3: "mp3",
            AudioFormat.OPUS: "ogg",  # opus 通常封装在 ogg 容器
            AudioFormat.SPEEX: "ogg",
            AudioFormat.AAC: "adts",
            AudioFormat.AMR: "amr",
        }

        pydub_format = format_map.get(audio_format)
        if pydub_format is None:
            raise ValueError(f"Unsupported audio format: {audio_format}")

        audio = AudioSegment.from_file(
            io.BytesIO(audio_data),
            format=pydub_format
        )

        # 转换为目标参数
        audio = audio.set_frame_rate(target_sample_rate)
        audio = audio.set_sample_width(DEFAULT_SAMPLE_WIDTH)
        audio = audio.set_channels(DEFAULT_CHANNELS)

        # 导出为 raw PCM
        pcm_data = audio.raw_data
        return pcm_data

    except Exception as e:
        logger.error(f"Failed to decode audio format {audio_format}: {e}")
        raise ValueError(f"Audio decode failed: {str(e)}")


def resample_pcm(
    pcm_data: bytes,
    source_rate: int,
    target_rate: int = DEFAULT_SAMPLE_RATE,
) -> bytes:
    """
    重采样 PCM 数据

    Args:
        pcm_data: 原 PCM 数据
        source_rate: 原采样率
        target_rate: 目标采样率

    Returns:
        重采样后的 PCM 数据
    """
    if source_rate == target_rate:
        return pcm_data

    try:
        audio = AudioSegment(
            data=pcm_data,
            sample_width=DEFAULT_SAMPLE_WIDTH,
            frame_rate=source_rate,
            channels=DEFAULT_CHANNELS,
        )
        audio = audio.set_frame_rate(target_rate)
        return audio.raw_data
    except Exception as e:
        logger.error(f"Resample failed: {e}")
        raise ValueError(f"Resample failed: {str(e)}")


def split_pcm_into_chunks(
    pcm_data: bytes,
    chunk_ms: int,
) -> list[bytes]:
    """
    将 PCM 数据按毫秒切分为多个 chunk

    Args:
        pcm_data: PCM 数据
        chunk_ms: 每个 chunk 的毫秒数

    Returns:
        chunk 列表
    """
    bytes_per_chunk = chunk_ms * PCM_BYTES_PER_MS
    chunks = []

    for i in range(0, len(pcm_data), bytes_per_chunk):
        chunk = pcm_data[i:i + bytes_per_chunk]
        if len(chunk) > 0:
            chunks.append(chunk)

    return chunks


def bytes_to_ms(byte_count: int) -> int:
    """字节数转毫秒数"""
    if PCM_BYTES_PER_MS == 0:
        return 0
    return byte_count // PCM_BYTES_PER_MS


async def decode_to_pcm_async(
    audio_data: bytes,
    audio_format: AudioFormat,
    target_sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> bytes:
    """
    异步版本音频解码（避免阻塞事件循环）

    Args:
        audio_data: 原始音频字节
        audio_format: 音频格式
        target_sample_rate: 目标采样率

    Returns:
        PCM 字节流
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        decode_to_pcm,
        audio_data,
        audio_format,
        target_sample_rate,
    )


def validate_pcm_format(
    pcm_data: bytes,
    expected_sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> bool:
    """
    验证 PCM 数据格式是否合法

    Args:
        pcm_data: PCM 数据
        expected_sample_rate: 期望采样率

    Returns:
        是否合法
    """
    if not pcm_data:
        return False

    # PCM 16-bit，每个样本 2 字节，长度必须是偶数
    if len(pcm_data) % DEFAULT_SAMPLE_WIDTH != 0:
        return False

    # 检查数据量是否合理（至少 10ms 音频）
    min_bytes = 10 * PCM_BYTES_PER_MS
    if len(pcm_data) < min_bytes:
        return False

    return True
