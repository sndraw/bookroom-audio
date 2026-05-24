__api_name__="BookRoom Audio"
__api_description__ = """
BookRoom Audio API - 提供完整的语音合成(TTS)和语音识别(ASR)功能。

**主要功能:**

🎤 **语音识别 (ASR)**
- 支持 Qwen3-ASR 模型
- 支持 Whisper 系列模型
- 支持多种语言识别
- 支持音频文件上传和流式识别

🔊 **语音合成 (TTS)**
- 支持 ChatTTS 模型
- 支持 MeloTTS 模型
- 支持多种语音和情感选择
- 支持中文、英文、日文等多种语言

**API端点:**
- `/v1/transcribe` - 语音识别相关接口
- `/v1/tts` - 语音合成相关接口
- `/health` - 健康检查

**默认配置:**
- TTS引擎: ChatTTS (中文)
- ASR引擎: Qwen3-ASR (中文)
"""
__api_version__ = "0.0.5"