"""
This module contains all transcribe related routes.
"""

import asyncio
import tempfile
import os
from typing import Any, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, File, UploadFile
from pydantic import BaseModel

from bookroom_audio.utils.utils_api import (
    get_api_key_dependency,
    logger,
)

router = APIRouter(prefix="/v1/audio", tags=["transcribe"])

SUPPORTED_MODELS = {
    "tiny.en", "tiny", "base.en", "base", "small.en", "small",
    "medium.en", "medium", "large-v1", "large-v2", "large-v3", "large",
    "distil-large-v2", "distil-medium.en", "distil-small.en",
    "distil-large-v3", "distil-large-v3.5", "large-v3-turbo", "turbo"
}

SUPPORTED_ENGINES = {
    "whisper",
    "qwen-asr",
}


def create_transcribe_routes(args: Any, api_key: Optional[str] = None):
    """
    Creates and registers the transcription and translation routes.
    """
    optional_api_key = get_api_key_dependency(api_key)

    async def _process_audio_task(
        file: Any, model: Optional[str], language: Optional[str], task: str, engine: Optional[str]
    ):
        """
        Internal helper to process audio files for transcription or translation.
        """
        try:
            selected_engine = engine or args.engine or "whisper"
            
            if selected_engine not in SUPPORTED_ENGINES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid engine '{selected_engine}'. Supported engines: {', '.join(SUPPORTED_ENGINES)}"
                )

            if selected_engine == "qwen-asr":
                from bookroom_audio.models.qwen_asr import load_model_task as qwen_load_model
                final_model = model or "qwen3-asr"
                params = dict(
                    audio=file,
                    model_size_or_path=final_model,
                    language=language or args.language,
                    task=task,
                )
                results = await qwen_load_model(args, params)
                return _format_qwen_result(results)
            else:
                from bookroom_audio.models.whisper import ModelQueryResponse, load_model_task as whisper_load_model
                
                final_model = model or args.model

                if not os.path.exists(final_model) and final_model not in SUPPORTED_MODELS:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid model '{final_model}'. Supported models: {', '.join(sorted(SUPPORTED_MODELS))}"
                    )

                logger.info(f"Attempting to load model: {final_model}")

                params = dict(
                    audio=file,
                    model_size_or_path=final_model,
                    language=language or args.language,
                    task=task,
                )
                results = await whisper_load_model(args, params)
                return _format_whisper_result(results)

        except asyncio.CancelledError:
            logger.warning(f"Request cancelled during {task}")
            raise HTTPException(status_code=499, detail="Request cancelled")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error during {task}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    def _format_whisper_result(results):
        segments = []
        for segment in results:
            segments.append({
                'text': segment.text,
                'start': segment.start,
                'end': segment.end,
                'confidence': segment.probability if hasattr(segment, 'probability') else 1.0,
            })
        return {
            'text': ''.join(s['text'] for s in segments),
            'segments': segments,
        }

    def _format_qwen_result(results):
        if isinstance(results, list):
            text = ''.join(s.get('text', '') for s in results)
            return {
                'text': text,
                'segments': results,
            }
        return {
            'text': str(results) if results else '',
            'segments': [],
        }

    @router.post(
        "/translations",
        dependencies=[Depends(optional_api_key)],
    )
    async def translate_audio(
        file: Optional[Any] = Form(None),
        file_upload: Optional[UploadFile] = File(None),
        model: Optional[str] = Form(None),
        language: Optional[str] = Form(None),
        engine: Optional[str] = Form(None),
    ):
        """
        Translate audio content to text in a target language.
        """
        actual_file = await _resolve_file_input(file, file_upload)
        
        if engine == "qwen-asr":
            raise HTTPException(status_code=400, detail="Qwen3-ASR does not support translation task")
            
        return await _process_audio_task(actual_file, model, language, task="translate", engine=engine)

    @router.post(
        "/transcriptions",
        dependencies=[Depends(optional_api_key)],
        operation_id="transcribe_audio",
    )
    async def transcribe_audio(
        file: Optional[Any] = Form(None),
        file_upload: Optional[UploadFile] = File(None),
        model: Optional[str] = Form(None),
        language: Optional[str] = Form(None),
        engine: Optional[str] = Form(None),
    ):
        """
        Transcribe audio content to text in the source language.
        
        Parameters:
            file: Legacy file input
            file_upload: File upload input
            model: Model name/path (depends on engine)
            language: Language code (e.g., zh, en)
            engine: Speech recognition engine. Options: whisper, qwen-asr
        """
        actual_file = await _resolve_file_input(file, file_upload)
        return await _process_audio_task(
            actual_file, model, language, task="transcribe", engine=engine
        )

    @router.get(
        "/engines",
        dependencies=[Depends(optional_api_key)],
        summary="List available engines",
        description="Returns a list of available speech recognition engines.",
    )
    async def list_engines():
        """
        Get available speech recognition engines.
        """
        return {
            "engines": list(SUPPORTED_ENGINES),
            "whisper_models": sorted(SUPPORTED_MODELS),
            "qwen_asr_models": ["qwen3-asr", "qwen3-asr-zh", "qwen3-asr-en"],
            "recommendations": {
                "chinese": "qwen-asr",
                "english": "whisper (large-v3)",
                "multilingual": "whisper (large-v3)",
            },
        }

    async def _resolve_file_input(
        file: Optional[Any], file_upload: Optional[UploadFile]
    ) -> Any:
        """
        Resolves the input file from either legacy 'file' form field or new 'file_upload'.
        """
        if file:
            return file

        if file_upload:
            try:
                content = await file_upload.read()
                original_filename = file_upload.filename or "audio.wav"
                suffix = os.path.splitext(original_filename)[1]

                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=suffix
                ) as tmp_file:
                    tmp_file.write(content)
                    tmp_file_path = tmp_file.name

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