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

# CosyVoice 2 预置音色（SFT 模式，需 spk2info.pt 随模型下载）
# 来自 CosyVoice2-0.5B 官方预置说话人（list_available_spks()）
COSYVOICE_VOICES = [
    "中文女",
    "中文男",
    "英文女",
    "英文男",
    "日语男",
    "粤语女",
    "四川女",
    "武汉女",
    "河南女",
    "浙江女",
]