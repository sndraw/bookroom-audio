__api_name__="BookRoom Audio"
__api_description__ = """
BookRoom Audio API - 提供完整的语音合成(TTS)、语音识别(ASR)、视频分析(VL)和图片分析功能。

**主要功能:**

🎤 **语音识别 (ASR)**
- 支持 Qwen3-ASR 模型
- 支持 Whisper 系列模型
- 支持多种语言识别
- 支持音频文件上传和流式识别
- 支持语音转文字和翻译功能

🔊 **语音合成 (TTS)**
- 支持 ChatTTS 模型（高质量中文离线TTS）
- 支持 Edge TTS（基于Azure的在线TTS服务）
- 支持 pyttsx3（本地离线TTS引擎）
- 支持多种语音选择（male/female/neutral）
- 支持情感控制（happy/sad/angry/neutral）
- 支持中文语音合成
- 支持离线运行（ChatTTS/pyttsx3）

🎬 **视频分析 (VL)**
- 支持 Qwen3-VL 模型 (2B/4B/8B参数)
- 视频内容识别: 描述视频中的视觉内容
- 视频内容评分: 对视频质量和适宜性评分
- 视频内容监测: 检测违规内容（色情、暴力、恐怖等）
- 完整分析: 同时执行识别、评分和监测

🖼️ **图片分析 (VL)**
- 支持 Qwen3-VL 模型 (2B/4B/8B参数)
- 图片内容识别: 描述图片中的视觉内容
- 图片内容评分: 对图片质量和适宜性评分
- 图片内容监测: 检测违规内容（色情、暴力、恐怖等）
- 支持 JPEG、PNG、GIF、BMP、WebP 等格式

**API端点:**

📝 **语音识别**
- `POST /v1/audio/transcriptions` - 音频转文字
- `POST /v1/audio/translations` - 音频翻译
- `GET /v1/audio/engines` - 获取支持的引擎列表

🔊 **语音合成**
- `POST /v1/tts/generate` - 生成语音
- `GET /v1/tts/voices` - 获取可用语音列表

🎬 **视频分析**
- `POST /v1/video/recognize` - 识别视频内容
- `POST /v1/video/score` - 视频内容评分
- `POST /v1/video/moderate` - 视频内容监测
- `POST /v1/video/analyze` - 完整视频分析
- `GET /v1/video/models` - 获取支持的模型列表
- `GET /v1/video/tasks` - 获取支持的任务类型
- `GET /v1/video/status` - 获取VL模型状态

🖼️ **图片分析**
- `POST /v1/image/recognize` - 识别图片内容
- `POST /v1/image/score` - 图片内容评分
- `POST /v1/image/moderate` - 图片内容监测
- `GET /v1/image/models` - 获取支持的模型列表
- `GET /v1/image/status` - 获取图片分析状态

🔌 **OpenAI 兼容接口**
- `POST /v1/audio/transcriptions` - 音频转文字（兼容 OpenAI Whisper API）
- `POST /v1/audio/translations` - 音频翻译（兼容 OpenAI Whisper API）
- `POST /v1/audio/speech` - 文字转语音（兼容 OpenAI TTS API）
- `POST /v1/video/analyze` - 视频分析（自定义扩展）
- `POST /v1/image/analyze` - 图片分析（自定义扩展）

🏠 **服务器管理**
- `GET /health` - 健康检查

**默认配置:**
- TTS引擎: ChatTTS (中文)
- ASR引擎: Qwen3-ASR (中文)
- VL模型: Qwen3-VL-4B-Instruct (medium)

**访问文档:**
- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI Schema: `/openapi.json`
"""
__api_version__ = "0.0.7"