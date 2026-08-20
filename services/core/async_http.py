"""
ALPHA BIST — Async HTTP Client Utility

Tüm provider'lar için ortak async HTTP altyapısı.

Özellikler:
- aiohttp tabanlı async HTTP client
- Timeout, retry, hata yönetimi
- Connection pooling
- Rate limiting
- Response caching (opsiyonel)

Kullanım:
    client = AsyncHTTPClient(timeout=10, max_retries=3)
    data = await client.get_json("https://api.example.com/data")
"""

import asyncio
import time
from typing import Dict, Any, Optional
import aiohttp
import structlog

logger = structlog.get_logger()


class AsyncHTTPClient:
    """Async HTTP client with retry and timeout."""

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay_s: float = 1.0,
        headers: Optional[Dict[str, str]] = None,
    ):
        self._timeout = aiohttp.ClientTimeout(total=timeout, connect=min(5.0, timeout / 3))
        self._max_retries = max_retries
        self._retry_delay_s = retry_delay_s
        self._headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/html, */*",
        }
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers=self._headers,
            )
        return self._session

    async def get_json(self, url: str, params: Optional[Dict] = None) -> Optional[Any]:
        """GET request, JSON response."""
        text = await self.get_text(url, params=params)
        if text:
            try:
                import json
                return json.loads(text)
            except Exception as e:
                logger.warning("JSON parse error", url=url, error=str(e))
        return None

    async def get_text(self, url: str, params: Optional[Dict] = None) -> Optional[str]:
        """GET request, text response."""
        for attempt in range(self._max_retries):
            try:
                session = await self._get_session()
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    elif resp.status == 429:
                        # Rate limited — bekle ve tekrar dene
                        wait = float(resp.headers.get("Retry-After", self._retry_delay_s * (attempt + 1)))
                        logger.warning("Rate limited", url=url, wait=wait)
                        await asyncio.sleep(wait)
                        continue
                    else:
                        logger.warning("HTTP error", url=url, status=resp.status, attempt=attempt + 1)
            except asyncio.TimeoutError:
                logger.warning("HTTP timeout", url=url, attempt=attempt + 1)
            except aiohttp.ClientError as e:
                logger.warning("HTTP client error", url=url, error=str(e), attempt=attempt + 1)
            except Exception as e:
                logger.error("HTTP unexpected error", url=url, error=str(e))

            if attempt < self._max_retries - 1:
                await asyncio.sleep(self._retry_delay_s * (attempt + 1))

        logger.error("HTTP request failed after retries", url=url, retries=self._max_retries)
        return None

    async def post_json(self, url: str, data: Any = None, json_data: Any = None) -> Optional[Any]:
        """POST request, JSON response."""
        for attempt in range(self._max_retries):
            try:
                session = await self._get_session()
                async with session.post(url, data=data, json=json_data) as resp:
                    if resp.status < 400:
                        text = await resp.text()
                        try:
                            import json
                            return json.loads(text)
                        except Exception:
                            return text
                    else:
                        logger.warning("POST error", url=url, status=resp.status)
            except Exception as e:
                logger.warning("POST error", url=url, error=str(e), attempt=attempt + 1)

            if attempt < self._max_retries - 1:
                await asyncio.sleep(self._retry_delay_s * (attempt + 1))

        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


# Singleton clients per provider
_clients: Dict[str, AsyncHTTPClient] = {}


def get_client(name: str, **kwargs) -> AsyncHTTPClient:
    """Provider bazlı singleton client."""
    if name not in _clients:
        _clients[name] = AsyncHTTPClient(**kwargs)
    return _clients[name]


async def close_all_clients():
    """Tüm client'ları kapat."""
    for client in _clients.values():
        await client.close()
    _clients.clear()
