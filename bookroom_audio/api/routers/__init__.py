"""
This module contains all the routers for the API.
"""

from .server_routes import router as server_router
from .transcribe_routes import router as transcribe_router
__all__ = [
    "server_router",
    "transcribe_router"
]
