"""
This module contains all transcribe related routes.
"""

import asyncio
import tempfile
import os
from typing import Any, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, File, UploadFile
from pydantic import BaseModel

from bookroom_audio.models.whisper import ModelQueryResponse, load_model_task
from bookroom_audio.utils.utils_api import (
    get_api_key_dependency,
    logger,
)

router = APIRouter(prefix="/v1/audio", tags=["transcribe"])


def create_transcribe_routes(args: Any, api_key: Optional[str] = None):
    """
    Creates and registers the transcription and translation routes.
    """
    # Create the optional API key dependency
    optional_api_key = get_api_key_dependency(api_key)

    async def _process_audio_task(
        file: Any, model: Optional[str], language: Optional[str], task: str
    ) -> ModelQueryResponse:
        """
        Internal helper to process audio files for transcription or translation.
        """
        try:
            # 确定最终使用的模型标识
            final_model = model or args.model

            # 【调试用】打印正在加载的模型，确认是 ID 还是路径
            logger.info(f"Attempting to load model: {final_model}")

            params = dict(
                audio=file,
                model_size_or_path=final_model,
                language=language or args.language,
                task=task,
            )
            results = await load_model_task(args, params)
            return results

        except asyncio.CancelledError:
            logger.warning(f"Request cancelled during {task}")
            # 使用 HTTPException 保持响应一致性，499 表示 Client Closed Request
            raise HTTPException(status_code=499, detail="Request cancelled")

        except Exception as e:
            logger.error(f"Error during {task}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/translations",
        response_model=ModelQueryResponse,
        dependencies=[Depends(optional_api_key)],
    )
    async def translate_audio(
        file: Optional[Any] = Form(None),
        file_upload: Optional[UploadFile] = File(None),
        model: Optional[str] = Form(None),
        language: Optional[str] = Form(None),
    ):
        """
        Translate audio content to text in a target language.

        Parameters:
            file (Any, optional): The audio file provided as a form field (legacy).
            file_upload (UploadFile, optional): The audio file provided as a file upload.
            model (str, optional): The model to use for transcription or translation.
            language (str, optional): The target language for translation.
        Returns:
            ModelQueryResponse: The translation result.
        Raises:
            HTTPException: If there is an error during processing.
        """
        actual_file = await _resolve_file_input(file, file_upload)
        return await _process_audio_task(actual_file, model, language, task="translate")

    @router.post(
        "/transcriptions",
        response_model=ModelQueryResponse,
        dependencies=[Depends(optional_api_key)],
        operation_id="transcribe_audio",
    )
    async def transcribe_audio(
        file: Optional[Any] = Form(None),
        file_upload: Optional[UploadFile] = File(None),
        model: Optional[str] = Form(None),
        language: Optional[str] = Form(None),
    ):
        """
        Transcribe audio content to text in the source language.

        Parameters:
            file (Any, optional): The audio file provided as a form field (legacy).
            file_upload (UploadFile, optional): The audio file provided as a file upload.
            model (str, optional): The model to use for transcription or translation.
            language (str, optional): The language of the audio content.
        Returns:
            ModelQueryResponse: The transcription or translation result.
        Raises:
            HTTPException: If there is an error during processing.
        """
        actual_file = await _resolve_file_input(file, file_upload)
        return await _process_audio_task(
            actual_file, model, language, task="transcribe"
        )

    async def _resolve_file_input(
        file: Optional[Any], file_upload: Optional[UploadFile]
    ) -> Any:
        """
        Resolves the input file from either legacy 'file' form field or new 'file_upload'.
        If file_upload is used, it reads the content and creates a temporary file.
        """
        if file:
            # 如果提供了传统的 file 字段，直接返回
            return file

        if file_upload:
            # 如果提供了 file_upload，读取内容并创建临时文件
            try:
                # 读取上传文件的内容
                content = await file_upload.read()

                # 获取原始文件名以保留扩展名（whisper 依赖扩展名判断格式）
                original_filename = file_upload.filename or "audio.wav"
                suffix = os.path.splitext(original_filename)[1]

                # 创建临时文件
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=suffix
                ) as tmp_file:
                    tmp_file.write(content)
                    tmp_file_path = tmp_file.name

                # 注意：这里返回的是文件路径字符串
                # 如果 load_model_task 期望文件对象而不是路径，可能需要调整
                # 但通常 whisper 接受路径
                return tmp_file_path

            except Exception as e:
                logger.error(f"Failed to process uploaded file: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500, detail="Failed to process uploaded file"
                )

        raise HTTPException(
            status_code=400,
            detail="No audio file provided. Use 'file' or 'file_upload'.",
        )

    return router
