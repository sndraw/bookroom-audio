"""
OpenAI 兼容 API 路由模块。

提供与 OpenAI API 兼容的接口格式，便于开发者和 Agent 无缝迁移。

支持的接口：
- POST /v1/audio/transcriptions - 音频转文字（兼容 OpenAI Whisper API）
- POST /v1/audio/translations - 音频翻译（兼容 OpenAI Whisper API）
- POST /v1/audio/speech - 文字转语音（兼容 OpenAI TTS API）
- POST /v1/video/analyze - 视频分析（自定义扩展）
- POST /v1/image/analyze - 图片分析（自定义扩展）

参考文档：
- https://platform.openai.com/docs/api-reference/audio
"""

import asyncio
import tempfile
import os
from typing import Any, Dict, Optional, Union
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Body
from fastapi.responses import StreamingResponse

from bookroom_audio.utils.utils_api import (
    get_api_key_dependency,
    logger,
)

def create_openai_routes(args: Any, api_key: Optional[str] = None):
    router = APIRouter(
        prefix="/v1",
        tags=["openai-compatible"],
        responses={
            400: {"description": "Invalid request parameters"},
            401: {"description": "Unauthorized - Invalid API key"},
            500: {"description": "Internal server error"},
        },
    )
    optional_api_key = get_api_key_dependency(api_key)

    async def _save_upload_file(file: UploadFile) -> str:
        """保存上传的文件到临时目录"""
        try:
            content = await file.read()
            original_filename = file.filename or "audio.mp3"
            suffix = os.path.splitext(original_filename)[1] or ".mp3"

            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            ) as tmp_file:
                tmp_file.write(content)
                tmp_file_path = tmp_file.name

            return tmp_file_path

        except Exception as e:
            logger.error(f"Failed to save uploaded file: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail="Failed to process uploaded file"
            )

    @router.post(
        "/audio/transcriptions",
        dependencies=[Depends(optional_api_key)],
        operation_id="openai_create_transcription",
        summary="Create transcription",
        description="""
将音频文件转换为文字。兼容 OpenAI Whisper API 格式。

请求参数：
- file: 音频文件（必填）
- model: 模型名称（必填）
- language: 语言代码（可选）
- prompt: 提示文本（可选）
- response_format: 响应格式（可选）
- temperature: 温度参数（可选）

支持的模型：
- whisper-1: 使用 Whisper 模型
- qwen3-asr: 使用 Qwen3-ASR 模型

响应格式：
- json: 返回 JSON 对象
- text: 返回纯文本
- srt: 返回 SRT 字幕格式
- vtt: 返回 VTT 字幕格式
        """,
        responses={
            200: {
                "description": "转录成功",
                "content": {
                    "application/json": {
                        "example": {
                            "text": "这是一段测试音频的转录结果。",
                            "language": "zh",
                            "duration": 10.5
                        }
                    }
                }
            }
        },
    )
    async def create_transcription(
        file: UploadFile = File(..., description="要转录的音频文件"),
        model: str = Body(..., description="模型名称: whisper-1 或 qwen3-asr"),
        language: Optional[str] = Body(None, description="语言代码: zh, en, ja 等"),
        prompt: Optional[str] = Body(None, description="提示文本"),
        response_format: Optional[str] = Body("json", description="响应格式"),
        temperature: Optional[float] = Body(0.0, description="温度参数"),
    ):
        """
        音频转文字 - 兼容 OpenAI Whisper API
        
        Args:
            file: 音频文件
            model: 模型名称
            language: 语言代码
            prompt: 提示文本
            response_format: 响应格式
            temperature: 温度参数
        
        Returns:
            转录结果
        """
        try:
            from bookroom_audio.api.routers.transcribe_routes import (
                create_transcribe_routes,
                SUPPORTED_ENGINES,
            )

            file_path = await _save_upload_file(file)
            
            # 映射模型名称到引擎
            if model.lower().startswith("whisper"):
                engine = "whisper"
                model_size = "large-v3"
            elif model.lower().startswith("qwen"):
                engine = "qwen-asr"
                model_size = "qwen3-asr"
            else:
                engine = "qwen-asr"
                model_size = "qwen3-asr"

            # 调用现有转录逻辑
            from bookroom_audio.models.qwen_asr import transcribe_audio
            
            result = await transcribe_audio(
                file_path,
                model=model_size,
                language=language or "zh",
                task="transcribe",
                engine=engine,
            )

            os.remove(file_path)

            # 格式化响应
            if response_format == "text":
                return result.get("text", "")
            elif response_format in ["srt", "vtt"]:
                return result.get("text", "")
            else:
                return {
                    "text": result.get("text", ""),
                    "language": result.get("language", language or "zh"),
                    "duration": result.get("duration", 0),
                }

        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/audio/translations",
        dependencies=[Depends(optional_api_key)],
        operation_id="openai_create_translation",
        summary="Create translation",
        description="""
将音频文件翻译为英文。兼容 OpenAI Whisper API 格式。

请求参数：
- file: 音频文件（必填）
- model: 模型名称（必填）
- prompt: 提示文本（可选）
- response_format: 响应格式（可选）
- temperature: 温度参数（可选）

支持的模型：
- whisper-1: 使用 Whisper 模型
        """,
        responses={
            200: {
                "description": "翻译成功",
                "content": {
                    "application/json": {
                        "example": {
                            "text": "This is the translation result.",
                            "language": "en",
                            "duration": 10.5
                        }
                    }
                }
            }
        },
    )
    async def create_translation(
        file: UploadFile = File(..., description="要翻译的音频文件"),
        model: str = Body(..., description="模型名称: whisper-1"),
        prompt: Optional[str] = Body(None, description="提示文本"),
        response_format: Optional[str] = Body("json", description="响应格式"),
        temperature: Optional[float] = Body(0.0, description="温度参数"),
    ):
        """
        音频翻译 - 兼容 OpenAI Whisper API
        
        Args:
            file: 音频文件
            model: 模型名称
            prompt: 提示文本
            response_format: 响应格式
            temperature: 温度参数
        
        Returns:
            翻译结果
        """
        try:
            file_path = await _save_upload_file(file)
            
            # 调用现有翻译逻辑
            from bookroom_audio.models.whisper import transcribe_audio
            
            result = await transcribe_audio(
                file_path,
                model="large-v3",
                language="en",
                task="translate",
                engine="whisper",
            )

            os.remove(file_path)

            # 格式化响应
            if response_format == "text":
                return result.get("text", "")
            else:
                return {
                    "text": result.get("text", ""),
                    "language": "en",
                    "duration": result.get("duration", 0),
                }

        except Exception as e:
            logger.error(f"Translation error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/audio/speech",
        dependencies=[Depends(optional_api_key)],
        operation_id="openai_create_speech",
        summary="Create speech",
        description="""
将文字转换为语音。兼容 OpenAI TTS API 格式。

请求参数：
- model: 模型名称（必填）
- input: 要转换的文本（必填）
- voice: 语音名称（可选）
- response_format: 响应格式（可选）
- speed: 语速（可选）

支持的模型：
- tts-1: 标准语音合成
- tts-1-hd: 高清语音合成

支持的语音：
- alloy: 中性声音
- echo: 深沉声音
- fable: 温暖声音
- onyx: 有力声音
- nova: 明亮声音
- shimmer: 柔和声音

响应格式：
- mp3: MP3 格式
- opus: Opus 格式
- aac: AAC 格式
- flac: FLAC 格式
        """,
        responses={
            200: {
                "description": "语音合成成功",
                "content": {
                    "audio/mpeg": {"example": "binary audio data"}
                }
            }
        },
    )
    async def create_speech(
        model: str = Body(..., description="模型名称: tts-1 或 tts-1-hd"),
        input: str = Body(..., description="要转换的文本"),
        voice: Optional[str] = Body("alloy", description="语音名称"),
        response_format: Optional[str] = Body("mp3", description="响应格式"),
        speed: Optional[float] = Body(1.0, description="语速 (0.25-4.0)"),
    ):
        """
        文字转语音 - 兼容 OpenAI TTS API
        
        Args:
            model: 模型名称
            input: 要转换的文本
            voice: 语音名称
            response_format: 响应格式
            speed: 语速
        
        Returns:
            音频流
        """
        try:
            # 修复：原代码 import 的 generate_audio 在 engines.py 中不存在，导致该端点恒 500。
            # 意图是 ChatTTS 合成，直接调用 generate_audio_chatt（失败仍显式报错，无兜底）。
            from bookroom_audio.api.routers.tts.engines import generate_audio_chatt

            # 映射语音名称到本地语音
            voice_map = {
                "alloy": "2",
                "echo": "3",
                "fable": "0",
                "onyx": "4",
                "nova": "1",
                "shimmer": "5",
            }
            local_voice = voice_map.get(voice, "2")

            # 调用现有TTS逻辑（generate_audio_chatt 为同步函数，放线程池执行）
            audio_data = await asyncio.to_thread(
                generate_audio_chatt,
                text=input,
                voice=local_voice,
                emotion="neutral",
                target_sample_rate=24000,
            )

            # 设置正确的 MIME 类型
            mime_type = {
                "mp3": "audio/mpeg",
                "opus": "audio/opus",
                "aac": "audio/aac",
                "flac": "audio/flac",
            }.get(response_format, "audio/mpeg")

            return StreamingResponse(
                iter([audio_data]),
                media_type=mime_type,
                headers={
                    "Content-Disposition": f"attachment; filename=speech.{response_format}"
                },
            )

        except Exception as e:
            logger.error(f"Speech synthesis error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/video/analyze",
        dependencies=[Depends(optional_api_key)],
        operation_id="openai_analyze_video",
        summary="Analyze video",
        description="""
视频内容分析。自定义扩展接口，支持视频识别、评分和内容监测。

请求参数：
- file: 视频文件（必填）
- task: 分析任务类型（可选）
- model: 模型名称（可选）
- frame_interval: 帧提取间隔（可选）

支持的任务类型：
- recognize: 识别视频内容
- score: 视频内容评分
- moderate: 视频内容监测
- full: 完整分析（默认）

支持的模型：
- qwen-vl-4b: Qwen3-VL-4B 模型
- qwen-vl-8b: Qwen3-VL-8B 模型
        """,
        responses={
            200: {
                "description": "分析成功",
                "content": {
                    "application/json": {
                        "example": {
                            "task": "full",
                            "recognize": {"summary": "视频内容摘要"},
                            "score": {"overall_score": 85.5},
                            "moderate": {"safe": True}
                        }
                    }
                }
            }
        },
    )
    async def analyze_video(
        file: UploadFile = File(..., description="要分析的视频文件"),
        task: Optional[str] = Body("full", description="分析任务类型"),
        model: Optional[str] = Body("qwen-vl-4b", description="模型名称"),
        frame_interval: Optional[int] = Body(10, description="帧提取间隔"),
    ):
        """
        视频分析 - 自定义扩展接口
        
        Args:
            file: 视频文件
            task: 分析任务类型
            model: 模型名称
            frame_interval: 帧提取间隔
        
        Returns:
            分析结果
        """
        try:
            from bookroom_audio.models.qwen_vl import (
                recognize_video,
                score_video,
                moderate_video,
                analyze_video_full,
                load_model_task,
            )

            file_path = await _save_upload_file(file)

            # 映射模型名称
            model_map = {
                "qwen-vl-2b": "tiny",
                "qwen-vl-4b": "medium",
                "qwen-vl-8b": "large",
            }
            model_size = model_map.get(model, "medium")

            # 创建模拟参数
            from dataclasses import dataclass, field

            @dataclass
            class MockModelConfig:
                device: str = "cpu"
                vl_model: str = model_size

            @dataclass
            class MockArgs:
                model: MockModelConfig = field(default_factory=MockModelConfig)

            # 加载模型
            await load_model_task(MockArgs(), {"model_size": model_size})

            # 执行分析
            if task == "recognize":
                result = await recognize_video(file_path, MockArgs(), frame_interval)
            elif task == "score":
                result = await score_video(file_path, MockArgs(), frame_interval)
            elif task == "moderate":
                result = await moderate_video(file_path, MockArgs(), frame_interval)
            else:
                result = await analyze_video_full(file_path, MockArgs(), frame_interval)

            os.remove(file_path)

            return result

        except Exception as e:
            logger.error(f"Video analysis error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/image/analyze",
        dependencies=[Depends(optional_api_key)],
        operation_id="openai_analyze_image",
        summary="Analyze image",
        description="""
图片内容分析。自定义扩展接口，支持图片识别、评分和内容监测。

请求参数：
- file: 图片文件（必填）
- task: 分析任务类型（可选）
- model: 模型名称（可选）

支持的任务类型：
- recognize: 识别图片内容
- score: 图片内容评分
- moderate: 图片内容监测（违规检测）

支持的模型：
- qwen-vl-4b: Qwen3-VL-4B 模型（默认）
- qwen-vl-8b: Qwen3-VL-8B 模型

支持的图片格式：JPEG, PNG, GIF, BMP, WebP
        """,
        responses={
            200: {
                "description": "分析成功",
                "content": {
                    "application/json": {
                        "example": {
                            "task": "recognize",
                            "summary": "图片内容摘要",
                            "description": "详细描述..."
                        }
                    }
                }
            }
        },
    )
    async def analyze_image(
        file: UploadFile = File(..., description="要分析的图片文件"),
        task: Optional[str] = Body("recognize", description="分析任务类型"),
        model: Optional[str] = Body("qwen-vl-4b", description="模型名称"),
    ):
        """
        图片分析 - 自定义扩展接口
        
        Args:
            file: 图片文件
            task: 分析任务类型
            model: 模型名称
        
        Returns:
            分析结果
        """
        try:
            from bookroom_audio.models.qwen_vl import (
                recognize_image,
                score_image,
                moderate_image,
                load_model_task,
            )

            # 验证文件格式
            original_filename = file.filename or "image.jpg"
            suffix = os.path.splitext(original_filename)[1].lower()
            supported_formats = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]
            if suffix not in supported_formats:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported image format: {suffix}. Supported: {supported_formats}"
                )

            file_path = await _save_upload_file(file)

            model_map = {
                "qwen-vl-2b": "tiny",
                "qwen-vl-4b": "medium",
                "qwen-vl-8b": "large",
            }
            model_size = model_map.get(model, "medium")

            from dataclasses import dataclass, field

            @dataclass
            class MockModelConfig:
                device: str = "cpu"
                vl_model: str = model_size

            @dataclass
            class MockArgs:
                model: MockModelConfig = field(default_factory=MockModelConfig)

            await load_model_task(MockArgs(), {"model_size": model_size})

            if task == "recognize":
                result = await recognize_image(file_path, MockArgs())
            elif task == "score":
                result = await score_image(file_path, MockArgs())
            elif task == "moderate":
                result = await moderate_image(file_path, MockArgs())
            else:
                result = await recognize_image(file_path, MockArgs())

            os.remove(file_path)

            return result

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Image analysis error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    return router