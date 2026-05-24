"""
TTS constants - Voice lists and configuration.
"""

# Edge TTS 中文语音列表
CHINESE_VOICES = [
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunxiaNeural",
    "zh-CN-YunyangNeural",
    "zh-CN-LiaoningNeural",
    "zh-CN-ShandongNeural",
    "zh-CN-GuangxiNeural",
    "zh-CN-YunnanNeural",
]

# Edge TTS 英文语音列表
ENGLISH_VOICES = [
    "en-US-AriaNeural",
    "en-US-DavidNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
]

# 所有 Edge TTS 语音
EDGE_TTS_VOICES = CHINESE_VOICES + ENGLISH_VOICES

# ChatTTS 语音类型
CHATTTS_VOICES = [
    "male",
    "female",
    "neutral",
]

# ChatTTS 情感类型
CHATTTS_EMOTIONS = [
    "happy",
    "sad",
    "angry",
    "neutral",
]