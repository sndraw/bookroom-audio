"""
TTS module - Text-to-Speech functionality.

This module provides:
- Schemas for TTS requests and responses
- Constants for voice lists and configuration
- Utility functions for language detection and parameter parsing
- TTS engine implementations (ChatTTS, Edge TTS, pyttsx3)
"""

from bookroom_audio.api.routers.tts.schemas import TTSRequest, VoiceInfo, EngineStatus
from bookroom_audio.api.routers.tts.constants import (
    CHINESE_VOICES,
    ENGLISH_VOICES,
    EDGE_TTS_VOICES,
    CHATTTS_VOICES,
    CHATTTS_EMOTIONS,
)
from bookroom_audio.api.routers.tts.utils import (
    detect_language,
    get_default_edge_voice,
    parse_rate,
    parse_volume,
    preprocess_text_for_chattts,
    select_engine,
)
from bookroom_audio.api.routers.tts.engines import (
    EDGE_TTS_AVAILABLE,
    PYTTSX3_AVAILABLE,
    generate_audio_edge_tts,
    generate_audio_pyttsx3,
    generate_audio_chatt,
)


__all__ = [
    # Schemas
    "TTSRequest",
    "VoiceInfo",
    "EngineStatus",
    
    # Constants
    "CHINESE_VOICES",
    "ENGLISH_VOICES",
    "EDGE_TTS_VOICES",
    "CHATTTS_VOICES",
    "CHATTTS_EMOTIONS",
    
    # Utilities
    "detect_language",
    "get_default_edge_voice",
    "parse_rate",
    "parse_volume",
    "preprocess_text_for_chattts",
    "select_engine",
    
    # Engines
    "EDGE_TTS_AVAILABLE",
    "PYTTSX3_AVAILABLE",
    "generate_audio_edge_tts",
    "generate_audio_pyttsx3",
    "generate_audio_chatt",
]