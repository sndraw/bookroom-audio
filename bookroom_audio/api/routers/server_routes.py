"""
This module contains all server related routes.
"""

import asyncio
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from bookroom_audio.utils.utils_api import get_api_key_dependency


class ServerResponse(BaseModel):
    """Server response model."""

    status: str
    message: str


def create_server_routes(args: Any, api_key: Optional[str] = None):
    router = APIRouter(tags=["server"])
    
    optional_api_key = get_api_key_dependency(api_key)

    @router.get("/health", response_model=ServerResponse, operation_id="get_status_health")
    async def get_status():
        """Get current system status"""
        return ServerResponse(status="healthy", message="System is running normally.")

    return router