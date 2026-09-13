"""
ALPHA BIST — API v2 Paketi

Kurumsal seviye REST API v2 ve GraphQL uç noktaları.
"""
from __future__ import annotations

from services.api.v2.router import router as api_v2_router

__all__ = ["api_v2_router"]
