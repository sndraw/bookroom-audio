"""
This module contains all transcribe related routes.
"""

import asyncio
from typing import Any, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel

from bookroom_audio.api.model.whisper import ModelQueryResponse, load_model_task
from bookroom_audio.api.utils import (
    get_api_key_dependency,
    logger,
)


router = APIRouter(prefix="/v1/audio", tags=["transcribe"])


def create_transcribe_routes(args: Any, api_key: Optional[str] = None):
    """Create transcribe routes."""
    router = APIRouter()
    # Create the optional API key dependency
    optional_api_key = get_api_key_dependency(api_key)

    @router.post(
        "/v1/audio/translations",
        response_model=ModelQueryResponse,
        dependencies=[Depends(optional_api_key)],
    )
    async def translate_audio(
        file: Any = Form(...), model: str = Form(None), language: str = Form(None)
    ):
        """
        Parameters:

            request (Request): The incoming request object

        Args:

            file (file, str): The file or path of the audio file to be translated

            model (str, optional): The translation model to use

            language (str, optional): The target language for translation

        Returns:

            The translated text objects as Array of Objects

        Raises:

            HTTPException: Raised when an error with status code 500 and detail containing the exception message
        """
        try:
            params = dict(
                audio=file,
                model_size_or_path=model or args.model,
                language=language or args.language,
                task="translate",
            )
            results = await load_model_task(args, params)
            return results
        except asyncio.CancelledError:
            return {
                "error": "Request cancelled"
            }, 499  # 使用499状态码表示客户端中止请求
        except Exception as e:
            logger.error(f"Error during transcriptions: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/v1/audio/transcriptions",
        response_model=ModelQueryResponse,
        dependencies=[Depends(optional_api_key)],
    )
    async def transcribe_audio(
        file: Any = Form(...), model: str = Form(None), language: str = Form(None)
    ):
        """
        Parameters:

            request (Request): The incoming request object

        Args:

            file (file, str): The file or path of the audio file to be trscribed

            model (str, optional): The transcription model to use

            language (str, optional): The target language for transcription

        Returns:

            The translated text objects as Array of Objects

        Raises:

            HTTPException: Raised when an error with status code 500 and detail containing the exception message

        """
        try:
            params = dict(
                file=file,
                model_size_or_path=model or args.model,
                language=language or args.language,
                task="transcribe",
            )
            results = await load_model_task(args, params)
            return results
        except asyncio.CancelledError:
            return {
                "error": "Request cancelled"
            }, 499  # 使用499状态码表示客户端中止请求
        except Exception as e:
            logger.error(f"Error during transcriptions: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
