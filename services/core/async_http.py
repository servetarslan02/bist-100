"""ALPHA BIST — Async HTTP Client Utility v2.0 (Enterprise-Grade)

Kurumsal Standartlar:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. MİMARİ:    asyncio.Lock ile session race condition koruması
2. OPTİMİZASYON: orjson module-level import (her çağrıda re-import yok)
3. DAYANIKLILIK: Exponential Backoff + Jitter retry, 429 Retry-After desteği
4. İZLENEBİLİRLİK: OTel span her HTTP isteğinde
5. GÜVENLİK:  %100 type hint, generic dict
6. KALİTE:    %100 docstring, context manager desteği
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import aiohttp
import orjson
import structlog
from opentelemetry import metrics, trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.async-http")
meter = metrics.get_meter("alpha-bist.async-http")

_http_requests_counter = meter.create_counter(
    "alpha.http.requests.total",
    description="Toplam HTTP istek sayısı",
)
_http_errors_counter = meter.create_counter(
    "alpha.http.errors.total",
    description="Başarısız HTTP istek sayısı",
)
_http_latency_histogram = meter.create_histogram(
    "alpha.http.latency_seconds",
    description="HTTP istek gecikme süresi",
    unit="s",
)


class AsyncHTTPClient:
    """Retry, Jitter Backoff ve OTel izleme özellikli async HTTP istemcisi.

    Args:
        timeout: İstek zaman aşımı (saniye).
        max_retries: Maksimum deneme sayısı.
        base_retry_delay_s: İlk retry bekleme süresi (saniye).
        max_retry_delay_s: Maksimum retry bekleme süresi (saniye).
        headers: Varsayılan HTTP başlıkları.
    """

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        base_retry_delay_s: float = 1.0,
        max_retry_delay_s: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout, connect=min(5.0, timeout / 3))
        self._max_retries = max_retries
        self._base_retry_delay_s = base_retry_delay_s
        self._max_retry_delay_s = max_retry_delay_s
        self._headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/html, */*",
        }
        self._session: aiohttp.ClientSession | None = None
        # Race condition önleme: aynı anda birden fazla coroutine session oluşturamaz
        self._session_lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Singleton aiohttp session döner; kapalıysa yeniden oluşturur."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=self._timeout,
                    headers=self._headers,
                )
        return self._session

    def _jitter_delay(self, attempt: int) -> float:
        """Exponential Backoff + Jitter hesaplar."""
        base = min(self._base_retry_delay_s * (2**attempt), self._max_retry_delay_s)
        return base + random.uniform(0, base * 0.2)

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any | None:
        """GET isteği yapar ve JSON response döner.

        Args:
            url: Hedef URL.
            params: Query parametreleri.

        Returns:
            Parse edilmiş JSON verisi veya None (hata durumunda).
        """
        text = await self.get_text(url, params=params)
        if text:
            try:
                return orjson.loads(text)
            except Exception as exc:
                logger.warning("JSON parse hatası", url=url, error=str(exc))
        return None

    async def get_text(self, url: str, params: dict[str, Any] | None = None) -> str | None:
        """GET isteği yapar ve metin response döner.

        Args:
            url: Hedef URL.
            params: Query parametreleri.

        Returns:
            Response metni veya None (hata durumunda).
        """
        import time

        for attempt in range(self._max_retries):
            t0 = time.monotonic()
            with tracer.start_as_current_span("http.get") as span:
                span.set_attribute("http.url", url)
                span.set_attribute("http.attempt", attempt + 1)
                try:
                    session = await self._get_session()
                    async with session.get(url, params=params) as resp:
                        elapsed = time.monotonic() - t0
                        _http_latency_histogram.record(elapsed, {"method": "GET"})
                        _http_requests_counter.add(1, {"method": "GET", "status": str(resp.status)})
                        span.set_attribute("http.status_code", resp.status)

                        if resp.status == 200:
                            return await resp.text()
                        elif resp.status == 429:
                            # Rate limited — Retry-After başlığını oku
                            wait = float(
                                resp.headers.get("Retry-After", self._jitter_delay(attempt))
                            )
                            logger.warning("Rate limit aşıldı", url=url, wait_s=wait)
                            await asyncio.sleep(wait)
                            continue
                        else:
                            logger.warning(
                                "HTTP hata kodu",
                                url=url,
                                status=resp.status,
                                attempt=attempt + 1,
                            )
                            _http_errors_counter.add(1, {"method": "GET", "status": str(resp.status)})

                except TimeoutError:
                    _http_errors_counter.add(1, {"method": "GET", "error": "timeout"})
                    logger.warning("HTTP zaman aşımı", url=url, attempt=attempt + 1)
                except aiohttp.ClientError as exc:
                    _http_errors_counter.add(1, {"method": "GET", "error": "client_error"})
                    logger.warning("HTTP istemci hatası", url=url, error=str(exc), attempt=attempt + 1)
                except Exception as exc:
                    _http_errors_counter.add(1, {"method": "GET", "error": "unexpected"})
                    logger.error("HTTP beklenmeyen hata", url=url, error=str(exc))

            if attempt < self._max_retries - 1:
                delay = self._jitter_delay(attempt)
                await asyncio.sleep(delay)

        logger.error("HTTP isteği başarısız", url=url, max_retries=self._max_retries)
        return None

    async def post_json(
        self,
        url: str,
        data: Any = None,
        json_data: Any = None,
    ) -> Any | None:
        """POST isteği yapar ve JSON response döner.

        Args:
            url: Hedef URL.
            data: Raw body verisi.
            json_data: JSON serializable body verisi.

        Returns:
            Parse edilmiş response veya None.
        """
        import time

        for attempt in range(self._max_retries):
            t0 = time.monotonic()
            with tracer.start_as_current_span("http.post") as span:
                span.set_attribute("http.url", url)
                span.set_attribute("http.attempt", attempt + 1)
                try:
                    session = await self._get_session()
                    async with session.post(url, data=data, json=json_data) as resp:
                        elapsed = time.monotonic() - t0
                        _http_latency_histogram.record(elapsed, {"method": "POST"})
                        _http_requests_counter.add(1, {"method": "POST", "status": str(resp.status)})
                        span.set_attribute("http.status_code", resp.status)

                        if resp.status < 400:
                            text = await resp.text()
                            try:
                                return orjson.loads(text)
                            except Exception:
                                return text
                        else:
                            logger.warning("POST hata kodu", url=url, status=resp.status)
                            _http_errors_counter.add(1, {"method": "POST", "status": str(resp.status)})

                except Exception as exc:
                    _http_errors_counter.add(1, {"method": "POST", "error": "unexpected"})
                    logger.warning("POST hatası", url=url, error=str(exc), attempt=attempt + 1)

            if attempt < self._max_retries - 1:
                delay = self._jitter_delay(attempt)
                await asyncio.sleep(delay)

        return None

    async def close(self) -> None:
        """HTTP session'ı kapatır ve belleği temizler."""
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

    async def __aenter__(self) -> "AsyncHTTPClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


# ─── Singleton Registry ───────────────────────────────────────────────────────

_clients: dict[str, AsyncHTTPClient] = {}
_registry_lock = asyncio.Lock()


def get_client(name: str, **kwargs: Any) -> AsyncHTTPClient:
    """Provider bazlı singleton HTTP client döner.

    Args:
        name: Client kimliği (provider adı).
        **kwargs: AsyncHTTPClient constructor parametreleri.

    Returns:
        Mevcut veya yeni oluşturulan AsyncHTTPClient.
    """
    if name not in _clients:
        _clients[name] = AsyncHTTPClient(**kwargs)
    return _clients[name]


async def close_all_clients() -> None:
    """Registry'deki tüm HTTP client session'larını kapatır."""
    for client in list(_clients.values()):
        await client.close()
    _clients.clear()
