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

# Kokoro-82M 中文音色（text-only 预置音色，Apache 2.0 可商用）
# 中文用 v1.1-zh 优化版，音色为数字编号：zf_001~zf_099（女 55 个）、zm_009~zm_100（男 45 个）。
# 任意编号均可用（如 zf_017、zm_033），voice 参数直接透传；不存在时引擎显式报错。
# 英文音色：af_maple / af_sol（美音女）、bf_vale（英音女）等。
KOKORO_VOICES = [
    "zf_001",  # 中文女声（v1.1-zh 默认）
    "zf_002",  # 中文女声
    "zf_003",  # 中文女声
    "zf_005",  # 中文女声
    "zf_008",  # 中文女声
    "zm_010",  # 中文男声
    "zm_011",  # 中文男声
    "zm_016",  # 中文男声
    "zm_020",  # 中文男声
    "af_maple",  # 英文女声
    "af_sol",    # 英文女声
    "bf_vale",   # 英式女声
]