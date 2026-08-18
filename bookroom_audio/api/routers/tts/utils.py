"""
TTS utilities - Helper functions for TTS processing.
"""

import re
from typing import Any


# 全角标点 -> 半角标点 的映射表（ChatTTS 只接受 ASCII/中文常见符号，
# 遇到其他全角符号会打印 "found invalid characters" 警告，这里提前规范化）
_FULLWIDTH_PUNCTUATION_MAP: dict[str, str] = {
    # 常用全角标点
    '！': '!', '？': '?', '：': ':', '；': ';',
    '（': '(', '）': ')', '【': '[', '】': ']',
    '《': '<', '》': '>', '｛': '{', '｝': '}',
    '「': '"', '」': '"', '『': '"', '』': '"',
    '〈': '<', '〉': '>', '〔': '(', '〕': ')',
    '—': '-', '－': '-', '–': '-', '−': '-',
    '…': '...', '⋯': '...',
    '～': '~', '·': ',', '•': ',',
    '、': ',', '，': ',', '。': '.',
    '“': '"', '”': '"', '‘': "'", '’': "'",
    '〝': '"', '〟': '"',
    '／': '/', '＼': '\\',
    '＋': '+', '＝': '=', '％': '%', '＃': '#',
    '＆': '&', '＊': '*', '＠': '@',
    '＜': '<', '＞': '>',
    '｜': '|', '＾': '^', '＿': '_',
    '＃': '#', '＄': '$', '％': '%',
}

# ChatTTS 允许的字符模式：中文 \u4e00-\u9fff、ASCII 英文字母数字、
# 常用 ASCII 标点、空格。其它字符一律移除，避免 ChatTTS 内部发出警告。
_CHATTTS_ALLOWED_PATTERN = re.compile(
    r'[^\u4e00-\u9fffA-Za-z0-9，。、,.!?;:"\'()\[\]<>~+\-*/%=&#@ ]'
)

# 对外暴露（向后兼容）
CHINESE_TO_ENGLISH_PUNCTUATION = _FULLWIDTH_PUNCTUATION_MAP
CHATTTS_ALLOWED_PATTERN = _CHATTTS_ALLOWED_PATTERN


def _normalize_fullwidth(text: str) -> str:
    """把全角字符替换为对应半角字符"""
    result = []
    for ch in text:
        mapped = _FULLWIDTH_PUNCTUATION_MAP.get(ch)
        if mapped is not None:
            result.append(mapped)
            continue
        # 额外处理 Unicode 全角字母数字区：U+FF01..U+FF5E -> ASCII
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif ch == '\u3000':  # 全角空格 -> 半角空格
            result.append(' ')
        else:
            result.append(ch)
    return ''.join(result)


def preprocess_text_for_chattts(text: str) -> str:
    """
    为 ChatTTS 预处理文本，替换或移除可能导致警告的无效字符。
    
    Args:
        text: 原始文本
        
    Returns:
        处理后的文本
    """
    if not text:
        return text

    # 1) 把全角字符替换为对应半角字符
    text = _normalize_fullwidth(text)

    # 2) 移除 ChatTTS 不接受的其它字符（保留中文、英文、数字、常用标点、空格）
    text = _CHATTTS_ALLOWED_PATTERN.sub('', text)

    # 3) 规整空白符：连续空白 / 制表符 / 换行 压缩为单个空格
    text = re.sub(r'\s+', ' ', text).strip()

    return text


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
        # 显式指定的引擎（含 cosyvoice3）原样返回。
        # 注意：cosyvoice3 需要参考音频（zero_shot），缺参时由路由层显式 400 报错，绝不兜底到其它引擎。
        return engine
    
    lang = detect_language(text)
    if lang == "zh":
        # 2026-08-18 决策：中文优先 CosyVoice 2（本地离线、Apache 2.0 可商用）；
        # 其次 Kokoro-82M（Apache 2.0 可商用，text-only 预置音色，替代不可商用的 ChatTTS）；
        # ChatTTS 仅作最终兜底（本地离线但不可商用，仅内部体验）。
        # cosyvoice3 不参与 auto 选择：它需要参考音频，auto 无法提供。
        try:
            from bookroom_audio.api.routers.tts.engines import _check_cosyvoice_available
            if _check_cosyvoice_available():
                return "cosyvoice"
        except ImportError:
            pass
        try:
            from bookroom_audio.api.routers.tts.engines import _check_kokoro_available
            if _check_kokoro_available():
                return "kokoro"
        except ImportError:
            pass
        return "chattts"
    return "pyttsx3"