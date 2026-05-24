"""
TTS utilities - Helper functions for TTS processing.
"""

import re
from typing import Any


def detect_language(text: str) -> str:
    """
    检测文本语言。
    
    Args:
        text: 要检测的文本
        
    Returns:
        "zh" 表示中文，"en" 表示英文
    """
    chinese_char_pattern = re.compile(r'[\u4e00-\u9fff]+')
    if chinese_char_pattern.search(text):
        return "zh"
    return "en"


def get_default_edge_voice(text: str) -> str:
    """
    根据文本语言获取默认的 Edge TTS 语音。
    
    Args:
        text: 要转换的文本
        
    Returns:
        默认的语音名称
    """
    from bookroom_audio.api.routers.tts.constants import CHINESE_VOICES
    
    lang = detect_language(text)
    if lang == "zh":
        return CHINESE_VOICES[0]  # zh-CN-XiaoxiaoNeural
    return "en-US-AriaNeural"


def parse_rate(rate: Any) -> str:
    """
    解析语速参数。
    
    Args:
        rate: 语速，可以是整数(WPM)或百分比字符串
        
    Returns:
        Edge TTS 格式的语速字符串（百分比格式）
    """
    if isinstance(rate, str):
        if rate.endswith("%"):
            return rate
        try:
            wpm = int(rate)
            return f"{int((wpm - 200) / 2)}%"
        except ValueError:
            return "0%"
    elif isinstance(rate, int):
        return f"{int((rate - 200) / 2)}%"
    return "0%"


def parse_volume(volume: Any) -> str:
    """
    解析音量参数。
    
    Args:
        volume: 音量，可以是浮点数(0.0-1.0)或百分比字符串
        
    Returns:
        Edge TTS 格式的音量字符串（百分比格式）
    """
    if isinstance(volume, str):
        if volume.endswith("%"):
            return volume
        try:
            vol = float(volume)
            return f"{int((vol - 0.5) * 200)}%"
        except ValueError:
            return "0%"
    elif isinstance(volume, float):
        return f"{int((volume - 0.5) * 200)}%"
    return "0%"


def select_engine(engine: str, text: str) -> str:
    """
    根据指定的引擎和文本选择合适的TTS引擎。
    
    Args:
        engine: 用户指定的引擎
        text: 要转换的文本
        
    Returns:
        实际使用的引擎名称
    """
    if engine != "auto":
        return engine
    
    lang = detect_language(text)
    if lang == "zh":
        return "chattts"
    return "edge-tts"