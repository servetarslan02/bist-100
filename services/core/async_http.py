"""ALPHA BIST — Asenkron HTTP İstemci Yardımcısı v2.0 (Enterprise-Grade).

Yüksek performanslı, dayanıklı ve izlenebilir asenkron HTTP istemcisi:
- aiohttp ve httpx uyumlu, bağlantı havuzu ve oturum (session) yönetimi
- Exponential backoff ve jitter ile otomatik yeniden deneme (retry) mekanizması
- HTTP 429 (Rate Limit) durumunda 'Retry-After' başlığına tam uyum
- OpenTelemetry span'leri ve Prometheus metrikleri (istek sayısı, gecikme, hata)
- Async context manager desteği ve thread-safe istemci kayıt defteri (registry)
"""

from __future__ import annotations

import asyncio
import random
import threading
import time
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
    """Yeniden deneme, jitter backoff ve OTel izleme özellikli kurumsal HTTP istemcisi."""

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        base_retry_delay_s: float = 1.0,
        max_retry_delay_s: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Asenkron HTTP istemcisini yapılandırır.

        Args:
            timeout: Toplam istek zaman aşımı (saniye).
            max_retries: Maksimum yeniden deneme sayısı.
            base_retry_delay_s: İlk deneme bekleme süresi tabanı (saniye).
            max_retry_delay_s: Maksimum bekleme süresi tavanı (saniye).
            headers: Varsayılan HTTP başlıkları sözlüğü.
        """
        self._timeout = aiohttp.ClientTimeout(total=timeout, connect=min(5.0, timeout / 3.0))
        self._max_retries = max_retries
        self._base_retry_delay_s = base_retry_delay_s
        self._max_retry_delay_s = max_retry_delay_s
        self._headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ALPHA-BIST/2.0",
            "Accept": "application/json, text/html, */*",
        }
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    def __repr__(self) -> str:
        """İstemcinin dize temsili."""
        status = "acik" if self._session and not self._session.closed else "kapali"
        return f"<AsyncHTTPClient(oturum='{status}', max_retries={self._max_retries})>"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Geçerli aiohttp oturumunu döner; kapalıysa kilit korumasıyla yeniden açar."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=self._timeout,
                    headers=self._headers,
                )
        return self._session

    def _jitter_delay(self, attempt: int) -> float:
        """Üstel geri çekilme (exponential backoff) ve rastgele gecikme (jitter) hesaplar."""
        base = min(self._base_retry_delay_s * (2**attempt), self._max_retry_delay_s)
        return base + random.uniform(0, base * 0.2)

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any | None:
        """GET isteği gönderir ve yanıtı JSON formatında ayrıştırarak döner.

        Args:
            url: İstek yapılacak hedef web adresi.
            params: İsteğe eklenecek sorgu parametreleri.

        Returns:
            Any | None: Ayrıştırılmış veri veya başarısızlık durumunda None.
        """
        text = await self.get_text(url, params=params)
        if text:
            try:
                return orjson.loads(text)
            except Exception as exc:
                logger.warning("http_json_ayristirma_hatasi", url=url, error=str(exc))
        return None

    async def get_text(self, url: str, params: dict[str, Any] | None = None) -> str | None:
        """GET isteği gönderir ve yanıt gövdesini düz metin olarak döner.

        Args:
            url: İstek yapılacak hedef web adresi.
            params: İsteğe eklenecek sorgu parametreleri.

        Returns:
            str | None: Yanıt metni veya hata durumunda None.
        """
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
                            wait = float(resp.headers.get("Retry-After", self._jitter_delay(attempt)))
                            logger.warning("http_istek_siniri_asildi", url=url, bekleme_s=wait)
                            await asyncio.sleep(wait)
                            continue
                        else:
                            logger.warning(
                                "http_basarisiz_durum_kodu",
                                url=url,
                                status=resp.status,
                                deneme=attempt + 1,
                            )
                            _http_errors_counter.add(1, {"method": "GET", "status": str(resp.status)})

                except TimeoutError:
                    _http_errors_counter.add(1, {"method": "GET", "error": "timeout"})
                    logger.warning("http_zaman_asimi", url=url, deneme=attempt + 1)
                except aiohttp.ClientError as exc:
                    _http_errors_counter.add(1, {"method": "GET", "error": "client_error"})
                    logger.warning("http_istemci_hatasi", url=url, error=str(exc), deneme=attempt + 1)
                except Exception as exc:
                    _http_errors_counter.add(1, {"method": "GET", "error": "unexpected"})
                    logger.error("http_beklenmeyen_hata", url=url, error=str(exc))

            if attempt < self._max_retries - 1:
                delay = self._jitter_delay(attempt)
                await asyncio.sleep(delay)

        logger.error("http_istekleri_tukendi_basarisiz", url=url, deneme_siniri=self._max_retries)
        return None

    async def post_json(
        self,
        url: str,
        data: Any = None,
        json_data: Any = None,
    ) -> Any | None:
        """POST isteği gönderir ve yanıtı JSON veya metin olarak döndürür.

        Args:
            url: İstek yapılacak hedef adres.
            data: Ham gövde verisi (bytes veya str).
            json_data: Serileştirilecek JSON gövdesi.

        Returns:
            Any | None: Ayrıştırılmış yanıt verisi veya None.
        """
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
                            logger.warning("http_post_hata_kodu", url=url, status=resp.status)
                            _http_errors_counter.add(1, {"method": "POST", "status": str(resp.status)})

                except Exception as exc:
                    _http_errors_counter.add(1, {"method": "POST", "error": "unexpected"})
                    logger.warning("http_post_hatasi", url=url, error=str(exc), deneme=attempt + 1)

            if attempt < self._max_retries - 1:
                delay = self._jitter_delay(attempt)
                await asyncio.sleep(delay)

        return None

    async def close(self) -> None:
        """Aktif HTTP oturumunu kapatır ve bellek kaynaklarını serbest bırakır."""
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

    async def __aenter__(self) -> AsyncHTTPClient:
        """Asenkron context manager giriş metodu."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Asenkron context manager çıkış metodu; oturumu güvenle kapatır."""
        await self.close()


# ─── Singleton Registry (Thread-Safe) ─────────────────────────────────────────

_clients: dict[str, AsyncHTTPClient] = {}
_registry_lock = threading.Lock()


def get_client(name: str, **kwargs: Any) -> AsyncHTTPClient:
    """Sağlayıcı veya servis bazlı tekil (singleton) HTTP istemcisi döndürür.

    Args:
        name: İstemciyi tanımlayan tekil anahtar (örn: 'kap_provider').
        **kwargs: AsyncHTTPClient başlatma parametreleri.

    Returns:
        AsyncHTTPClient: Mevcut veya yeni oluşturulan istemci nesnesi.
    """
    with _registry_lock:
        if name not in _clients:
            _clients[name] = AsyncHTTPClient(**kwargs)
        return _clients[name]


async def close_all_clients() -> None:
    """Kayıt defterindeki tüm HTTP istemcilerinin oturumlarını eşzamanlı kapatır."""
    with _registry_lock:
        clients_to_close = list(_clients.values())
        _clients.clear()

    for client in clients_to_close:
        await client.close()


__all__ = [
    "AsyncHTTPClient",
    "close_all_clients",
    "get_client",
]
