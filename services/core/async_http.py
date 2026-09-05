"""ALPHA BIST — Asenkron HTTP İstemci Yardımcısı v2.0 (Enterprise-Grade).

Yüksek performanslı, dayanıklı ve izlenebilir asenkron HTTP istemcisi:
- aiohttp ve orjson entegrasyonu ile sıfır standart-json bağımlılığı
- TCP bağlantı havuzu (connection pool) ve Windows soket sızıntısı koruması
- Exponential backoff ve jitter ile otomatik yeniden deneme (retry) mekanizması
- HTTP 429 (Rate Limit) durumunda RFC 7231 'Retry-After' ayrıştırması ve tavan (cap) koruması
- İkili veri indirme (get_bytes) ve form-encoded POST (post_form) desteği
- Çoklu thread/loop güvenliği (lazy lock), OTel span'leri ve Prometheus metrikleri
- İstek denetim kaydı, Polars ve DuckDB metrik dışa aktarımı
"""

from __future__ import annotations

import asyncio
import email.utils
import random
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import aiohttp
import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import metrics, trace

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.async-http")
meter = metrics.get_meter("alpha-bist.async-http")

# =====================================================
# STANDART HTTP YAPILANDIRMA SABİTLERİ
# =====================================================

DEFAULT_TIMEOUT: Final[float] = 10.0
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_BASE_RETRY_DELAY_S: Final[float] = 1.0
DEFAULT_MAX_RETRY_DELAY_S: Final[float] = 30.0
DEFAULT_USER_AGENT: Final[str] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ALPHA-BIST/2.0"
DEFAULT_MAX_METRICS_HISTORY: Final[int] = 1000
DEFAULT_HTTP_METRICS_DB_PATH: Final[str] = "data/http_metrics.duckdb"

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


def _orjson_serializer(data: Any) -> str:
    """Oturum seviyesinde orjson kullanarak güvenli serileştirme yapar."""
    return orjson.dumps(data, default=str).decode("utf-8")


class AsyncHTTPClient:
    """Yeniden deneme, jitter backoff ve OTel izleme özellikli kurumsal HTTP istemcisi."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_retry_delay_s: float = DEFAULT_BASE_RETRY_DELAY_S,
        max_retry_delay_s: float = DEFAULT_MAX_RETRY_DELAY_S,
        headers: dict[str, str] | None = None,
        retry_delay_s: float | None = None,
        ssl_verify: bool = True,
        max_history: int = DEFAULT_MAX_METRICS_HISTORY,
    ) -> None:
        """Asenkron HTTP istemcisini yapılandırır.

        Args:
            timeout: Toplam istek zaman aşımı (saniye).
            max_retries: Maksimum yeniden deneme sayısı.
            base_retry_delay_s: İlk deneme bekleme süresi tabanı (saniye).
            max_retry_delay_s: Maksimum bekleme süresi tavanı (saniye).
            headers: Varsayılan HTTP başlıkları sözlüğü.
            retry_delay_s: Geriye dönük uyumluluk için temel gecikme.
            ssl_verify: SSL sertifika doğrulamasının yapılıp yapılmayacağı.
            max_history: Bellek içi saklanacak maksimum istek geçmişi adedi.
        """
        self._timeout = aiohttp.ClientTimeout(
            total=timeout,
            connect=min(5.0, max(1.0, timeout / 3.0)),
            sock_read=timeout,
            sock_connect=min(5.0, max(1.0, timeout / 3.0)),
        )
        self._max_retries = max(1, max_retries)
        self._base_retry_delay_s = retry_delay_s if retry_delay_s is not None else base_retry_delay_s
        self._max_retry_delay_s = max_retry_delay_s
        self._ssl_verify = ssl_verify
        self._headers = headers or {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json, text/html, */*",
        }
        self._session: aiohttp.ClientSession | None = None
        self._session_locks: dict[int, asyncio.Lock] = {}
        self._lock_guard: threading.RLock = threading.RLock()
        self._request_history: deque[dict[str, Any]] = deque(maxlen=max_history)

    @property
    def retry_delay_s(self) -> float:
        """Geriye dönük uyumluluk için temel yeniden deneme gecikmesi."""
        return self._base_retry_delay_s

    def __repr__(self) -> str:
        """İstemcinin açıklayıcı dize temsili."""
        status = "acik" if self._session and not self._session.closed else "kapali"
        return f"AsyncHTTPClient(oturum={status!r}, max_retries={self._max_retries}, ssl_verify={self._ssl_verify})"

    def _get_lock(self) -> asyncio.Lock:
        """O anki aktif event loop'a bağlı asyncio.Lock nesnesini thread-safe döner."""
        try:
            loop = asyncio.get_running_loop()
            loop_id = id(loop)
        except RuntimeError as e:
            raise RuntimeError("AsyncHTTPClient yalnızca aktif bir asyncio event loop içinde çağrılabilir.") from e

        with self._lock_guard:
            if loop_id not in self._session_locks:
                self._session_locks[loop_id] = asyncio.Lock()
            return self._session_locks[loop_id]

    async def _get_session(self) -> aiohttp.ClientSession:
        """Geçerli aiohttp oturumunu döner; kapalıysa kilit korumasıyla ve orjson ile yeniden açar."""
        lock = self._get_lock()
        async with lock:
            if self._session is None or self._session.closed:
                connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=20,
                    enable_cleanup_closed=True,
                    ssl=None if self._ssl_verify else False,
                )
                self._session = aiohttp.ClientSession(
                    timeout=self._timeout,
                    headers=self._headers,
                    connector=connector,
                    json_serialize=_orjson_serializer,
                )
        return self._session

    def _jitter_delay(self, attempt: int) -> float:
        """Üstel geri çekilme (exponential backoff) ve rastgele gecikme (jitter) hesaplar."""
        base = min(self._base_retry_delay_s * (2**attempt), self._max_retry_delay_s)
        return float(base + random.uniform(0, base * 0.2))

    def _parse_retry_after(self, header_val: str | None, default_delay: float) -> float:
        """RFC 7231 'Retry-After' başlığını güvenle ayrıştırır ve tavan sınır uygular.

        Args:
            header_val: 'Retry-After' başlık metni (saniye veya HTTP-date).
            default_delay: Ayrıştırma başarısız olursa kullanılacak varsayılan bekleme süresi.

        Returns:
            float: Saniye cinsinden güvenli bekleme süresi.
        """
        if not header_val:
            return default_delay
        try:
            val = float(header_val)
            return float(min(max(0.0, val), self._max_retry_delay_s))
        except ValueError:
            pass

        try:
            target_dt = email.utils.parsedate_to_datetime(header_val)
            now_dt = time.time()
            wait = target_dt.timestamp() - now_dt
            return float(min(max(0.0, wait), self._max_retry_delay_s))
        except Exception:
            return default_delay

    def _record_audit(
        self,
        method: str,
        url: str,
        status: int,
        elapsed_ms: float,
        attempt: int,
        success: bool,
        error: str | None = None,
    ) -> None:
        """İstek sonucunu yerel denetim geçmişine kaydeder."""
        with self._lock_guard:
            self._request_history.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "method": method,
                    "url": url,
                    "status": status,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "attempt": attempt,
                    "success": success,
                    "error": error or "",
                }
            )

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: Any = None,
        json_data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> str | None:
        """Tüm HTTP metotları için standart yeniden deneme ve metrik kayıt boru hattı."""
        upper_method = method.upper().strip()

        for attempt in range(self._max_retries):
            t0 = time.monotonic()
            with tracer.start_as_current_span(f"http.{upper_method.lower()}") as span:
                span.set_attribute("http.url", url)
                span.set_attribute("http.method", upper_method)
                span.set_attribute("http.attempt", attempt + 1)
                try:
                    session = await self._get_session()
                    req_kwargs: dict[str, Any] = {"params": params}
                    if headers:
                        req_kwargs["headers"] = headers
                    if data is not None:
                        req_kwargs["data"] = data
                    if json_data is not None:
                        req_kwargs["json"] = json_data

                    async with session.request(upper_method, url, **req_kwargs) as resp:
                        elapsed = time.monotonic() - t0
                        elapsed_ms = elapsed * 1000.0
                        _http_latency_histogram.record(elapsed, {"method": upper_method})
                        _http_requests_counter.add(1, {"method": upper_method, "status": str(resp.status)})
                        span.set_attribute("http.status_code", resp.status)

                        if 200 <= resp.status < 300:
                            content = await resp.text(encoding="utf-8", errors="replace")
                            self._record_audit(
                                method=upper_method,
                                url=url,
                                status=resp.status,
                                elapsed_ms=elapsed_ms,
                                attempt=attempt + 1,
                                success=True,
                            )
                            return content
                        elif resp.status == 429:
                            default_wait = self._jitter_delay(attempt)
                            wait = self._parse_retry_after(resp.headers.get("Retry-After"), default_wait)
                            self._record_audit(
                                method=upper_method,
                                url=url,
                                status=resp.status,
                                elapsed_ms=elapsed_ms,
                                attempt=attempt + 1,
                                success=False,
                                error="rate_limited_429",
                            )
                            logger.warning("http_istek_siniri_asildi", method=upper_method, url=url, bekleme_s=wait)
                            await asyncio.sleep(wait)
                            continue
                        else:
                            self._record_audit(
                                method=upper_method,
                                url=url,
                                status=resp.status,
                                elapsed_ms=elapsed_ms,
                                attempt=attempt + 1,
                                success=False,
                                error=f"http_status_{resp.status}",
                            )
                            logger.warning(
                                "http_basarisiz_durum_kodu",
                                method=upper_method,
                                url=url,
                                status=resp.status,
                                deneme=attempt + 1,
                            )
                            _http_errors_counter.add(1, {"method": upper_method, "status": str(resp.status)})

                except asyncio.CancelledError:
                    logger.warning("http_istek_iptal_edildi", method=upper_method, url=url)
                    raise
                except TimeoutError as exc:
                    elapsed_ms = (time.monotonic() - t0) * 1000.0
                    self._record_audit(
                        method=upper_method,
                        url=url,
                        status=0,
                        elapsed_ms=elapsed_ms,
                        attempt=attempt + 1,
                        success=False,
                        error=f"timeout: {exc}",
                    )
                    _http_errors_counter.add(1, {"method": upper_method, "error": "timeout"})
                    logger.warning("http_zaman_asimi", method=upper_method, url=url, deneme=attempt + 1, hata=str(exc))
                except aiohttp.ClientError as exc:
                    elapsed_ms = (time.monotonic() - t0) * 1000.0
                    self._record_audit(
                        method=upper_method,
                        url=url,
                        status=0,
                        elapsed_ms=elapsed_ms,
                        attempt=attempt + 1,
                        success=False,
                        error=f"client_error: {exc}",
                    )
                    _http_errors_counter.add(1, {"method": upper_method, "error": "client_error"})
                    logger.warning(
                        "http_istemci_hatasi",
                        method=upper_method,
                        url=url,
                        hata=str(exc),
                        deneme=attempt + 1,
                    )
                except Exception as exc:
                    elapsed_ms = (time.monotonic() - t0) * 1000.0
                    self._record_audit(
                        method=upper_method,
                        url=url,
                        status=0,
                        elapsed_ms=elapsed_ms,
                        attempt=attempt + 1,
                        success=False,
                        error=f"unexpected: {exc}",
                    )
                    _http_errors_counter.add(1, {"method": upper_method, "error": "unexpected"})
                    logger.error("http_beklenmeyen_hata", method=upper_method, url=url, hata=str(exc))

            if attempt < self._max_retries - 1:
                delay = self._jitter_delay(attempt)
                await asyncio.sleep(delay)

        logger.error(
            "http_istekleri_tukendi_basarisiz",
            method=upper_method,
            url=url,
            deneme_siniri=self._max_retries,
        )
        return None

    async def get_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str | None:
        """GET isteği gönderir ve yanıt gövdesini düz metin olarak döner.

        Args:
            url: İstek yapılacak hedef web adresi.
            params: İsteğe eklenecek sorgu parametreleri.
            headers: İsteğe özel ek HTTP başlıkları.

        Returns:
            str | None: Yanıt metni veya hata durumunda None.
        """
        return await self._request_with_retry("GET", url, params=params, headers=headers)

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any | None:
        """GET isteği gönderir ve yanıtı orjson ile ayrıştırarak döner.

        Args:
            url: İstek yapılacak hedef web adresi.
            params: İsteğe eklenecek sorgu parametreleri.
            headers: İsteğe özel ek HTTP başlıkları.

        Returns:
            Any | None: Ayrıştırılmış veri veya başarısızlık durumunda None.
        """
        text = await self.get_text(url, params=params, headers=headers)
        if text:
            try:
                return orjson.loads(text)
            except Exception as exc:
                logger.warning("http_json_ayristirma_hatasi", url=url, hata=str(exc))
        return None

    async def get_bytes(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes | None:
        """GET isteği gönderir ve yanıt gövdesini ham ikili veri (bytes) olarak döner.

        Args:
            url: İstek yapılacak hedef web adresi.
            params: İsteğe eklenecek sorgu parametreleri.
            headers: İsteğe özel ek HTTP başlıkları.

        Returns:
            bytes | None: İndirilen ham bayt verisi veya başarısızlık durumunda None.
        """
        for attempt in range(self._max_retries):
            t0 = time.monotonic()
            with tracer.start_as_current_span("http.get_bytes") as span:
                span.set_attribute("http.url", url)
                span.set_attribute("http.method", "GET")
                span.set_attribute("http.attempt", attempt + 1)
                try:
                    session = await self._get_session()
                    req_kwargs: dict[str, Any] = {"params": params}
                    if headers:
                        req_kwargs["headers"] = headers

                    async with session.get(url, **req_kwargs) as resp:
                        elapsed = time.monotonic() - t0
                        elapsed_ms = elapsed * 1000.0
                        _http_latency_histogram.record(elapsed, {"method": "GET"})
                        _http_requests_counter.add(1, {"method": "GET", "status": str(resp.status)})
                        span.set_attribute("http.status_code", resp.status)

                        if 200 <= resp.status < 300:
                            content = await resp.read()
                            self._record_audit(
                                method="GET",
                                url=url,
                                status=resp.status,
                                elapsed_ms=elapsed_ms,
                                attempt=attempt + 1,
                                success=True,
                            )
                            return content
                        elif resp.status == 429:
                            default_wait = self._jitter_delay(attempt)
                            wait = self._parse_retry_after(resp.headers.get("Retry-After"), default_wait)
                            await asyncio.sleep(wait)
                            continue
                        else:
                            _http_errors_counter.add(1, {"method": "GET", "status": str(resp.status)})
                except Exception as exc:
                    _http_errors_counter.add(1, {"method": "GET", "error": "client_error"})
                    logger.warning("http_get_bytes_hatasi", url=url, hata=str(exc), deneme=attempt + 1)

            if attempt < self._max_retries - 1:
                await asyncio.sleep(self._jitter_delay(attempt))

        return None

    async def post_json(
        self,
        url: str,
        data: Any = None,
        json_data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any | None:
        """POST isteği gönderir ve yanıtı JSON veya metin olarak döndürür.

        Args:
            url: İstek yapılacak hedef adres.
            data: Ham gövde verisi (bytes veya str).
            json_data: Serileştirilecek JSON gövdesi.
            headers: İsteğe özel ek HTTP başlıkları.

        Returns:
            Any | None: Ayrıştırılmış yanıt verisi veya None.
        """
        text = await self._request_with_retry("POST", url, data=data, json_data=json_data, headers=headers)
        if text is not None:
            if not text.strip():
                return {}
            try:
                return orjson.loads(text)
            except Exception:
                return text
        return None

    async def post_form(
        self,
        url: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> Any | None:
        """Form kodlamalı (application/x-www-form-urlencoded) POST isteği gönderir.

        Args:
            url: Hedef adres.
            data: Form anahtar-değer verileri.
            headers: İsteğe özel ek başlıklar.

        Returns:
            Any | None: Yanıt nesnesi veya None.
        """
        form_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if headers:
            form_headers.update(headers)
        return await self.post_json(url, data=data, headers=form_headers)

    async def put_json(
        self,
        url: str,
        data: Any = None,
        json_data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any | None:
        """PUT isteği gönderir ve yanıtı JSON veya metin olarak döndürür.

        Args:
            url: İstek yapılacak hedef adres.
            data: Ham gövde verisi (bytes veya str).
            json_data: Serileştirilecek JSON gövdesi.
            headers: İsteğe özel ek HTTP başlıkları.

        Returns:
            Any | None: Ayrıştırılmış yanıt verisi veya None.
        """
        text = await self._request_with_retry("PUT", url, data=data, json_data=json_data, headers=headers)
        if text is not None:
            if not text.strip():
                return {}
            try:
                return orjson.loads(text)
            except Exception:
                return text
        return None

    async def delete_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any | None:
        """DELETE isteği gönderir ve yanıtı JSON veya metin olarak döndürür.

        Args:
            url: İstek yapılacak hedef adres.
            params: İsteğe eklenecek sorgu parametreleri.
            headers: İsteğe özel ek HTTP başlıkları.

        Returns:
            Any | None: Ayrıştırılmış yanıt verisi veya None.
        """
        text = await self._request_with_retry("DELETE", url, params=params, headers=headers)
        if text is not None:
            if not text.strip():
                return {}
            try:
                return orjson.loads(text)
            except Exception:
                return text
        return None

    async def patch_json(
        self,
        url: str,
        data: Any = None,
        json_data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any | None:
        """PATCH isteği gönderir ve yanıtı JSON veya metin olarak döndürür.

        Args:
            url: İstek yapılacak hedef adres.
            data: Ham gövde verisi (bytes veya str).
            json_data: Serileştirilecek JSON gövdesi.
            headers: İsteğe özel ek HTTP başlıkları.

        Returns:
            Any | None: Ayrıştırılmış yanıt verisi veya None.
        """
        text = await self._request_with_retry("PATCH", url, data=data, json_data=json_data, headers=headers)
        if text is not None:
            if not text.strip():
                return {}
            try:
                return orjson.loads(text)
            except Exception:
                return text
        return None

    @otel_trace("async_http.export_metrics_to_polars")
    def export_metrics_to_polars(self) -> pl.DataFrame:
        """Son isteklerin gecikme ve durum metriklerini Polars DataFrame olarak döndürür."""
        with self._lock_guard:
            records = list(self._request_history)

        schema = {
            "timestamp": pl.String,
            "method": pl.String,
            "url": pl.String,
            "status": pl.Int64,
            "elapsed_ms": pl.Float64,
            "attempt": pl.Int64,
            "success": pl.Boolean,
            "error": pl.String,
        }

        if not records:
            return pl.DataFrame([], schema=schema)

        return pl.DataFrame(records, schema=schema)

    @otel_trace("async_http.export_metrics_to_duckdb")
    def export_metrics_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """İstek geçmişi metriklerini kalıcı DuckDB tablosuna aktarır."""
        target_path = Path(db_path or DEFAULT_HTTP_METRICS_DB_PATH)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock_guard:
            records = list(self._request_history)

        if not records:
            return 0

        conn = duckdb.connect(str(target_path))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bist_http_metrics (
                    timestamp VARCHAR,
                    method VARCHAR,
                    url VARCHAR,
                    status BIGINT,
                    elapsed_ms DOUBLE,
                    attempt BIGINT,
                    success BOOLEAN,
                    error VARCHAR,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            data_tuples = [
                (
                    r["timestamp"],
                    r["method"],
                    r["url"],
                    r["status"],
                    r["elapsed_ms"],
                    r["attempt"],
                    r["success"],
                    r["error"],
                )
                for r in records
            ]
            conn.executemany(
                """
                INSERT INTO bist_http_metrics (
                    timestamp, method, url, status, elapsed_ms, attempt, success, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                data_tuples,
            )
            return len(records)
        finally:
            conn.close()

    def get_metrics_summary(self) -> dict[str, Any]:
        """İstemcinin çalışma metriklerinin özet istatistiğini döner."""
        with self._lock_guard:
            records = list(self._request_history)

        if not records:
            return {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "success_rate_pct": 0.0,
                "avg_latency_ms": 0.0,
            }

        total = len(records)
        successes = sum(1 for r in records if r["success"])
        latencies = [r["elapsed_ms"] for r in records]
        avg_latency = sum(latencies) / total if total > 0 else 0.0

        return {
            "total_requests": total,
            "successful_requests": successes,
            "failed_requests": total - successes,
            "success_rate_pct": round((successes / total) * 100.0, 2) if total > 0 else 0.0,
            "avg_latency_ms": round(avg_latency, 2),
        }

    async def close(self) -> None:
        """Aktif HTTP oturumunu kapatır ve bağlantı kaynaklarını serbest bırakır."""
        lock = self._get_lock()
        async with lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

    async def __aenter__(self) -> AsyncHTTPClient:
        """Asenkron context manager giriş metodu."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Asenkron context manager çıkış metodu; oturumu güvenle kapatır."""
        await self.close()


# =====================================================
# SINGLETON KAYIT DEFTERİ (THREAD-SAFE)
# =====================================================

_clients: dict[str, AsyncHTTPClient] = {}
_registry_lock = threading.RLock()


def get_client(name: str = "default", **kwargs: Any) -> AsyncHTTPClient:
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
    """Kayıt defterindeki tüm HTTP istemcilerinin oturumlarını eşzamanlı ve güvenle kapatır."""
    with _registry_lock:
        clients_to_close = list(_clients.values())
        _clients.clear()

    if clients_to_close:
        await asyncio.gather(*(c.close() for c in clients_to_close), return_exceptions=True)


# =====================================================
# MODÜL DÜZEYİ KOLAYLIK FONKSİYONLARI (CONVENIENCE API)
# =====================================================


async def async_get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    client_name: str = "default",
    **kwargs: Any,
) -> Any | None:
    """Varsayılan veya belirtilen istemci ile GET JSON isteği gönderir."""
    client = get_client(name=client_name, **kwargs)
    return await client.get_json(url=url, params=params, headers=headers)


async def async_get_text(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    client_name: str = "default",
    **kwargs: Any,
) -> str | None:
    """Varsayılan veya belirtilen istemci ile GET düz metin isteği gönderir."""
    client = get_client(name=client_name, **kwargs)
    return await client.get_text(url=url, params=params, headers=headers)


async def async_get_bytes(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    client_name: str = "default",
    **kwargs: Any,
) -> bytes | None:
    """Varsayılan veya belirtilen istemci ile GET ikili veri (bytes) isteği gönderir."""
    client = get_client(name=client_name, **kwargs)
    return await client.get_bytes(url=url, params=params, headers=headers)


async def async_post_json(
    url: str,
    data: Any = None,
    json_data: Any = None,
    headers: dict[str, str] | None = None,
    client_name: str = "default",
    **kwargs: Any,
) -> Any | None:
    """Varsayılan veya belirtilen istemci ile POST JSON isteği gönderir."""
    client = get_client(name=client_name, **kwargs)
    return await client.post_json(url=url, data=data, json_data=json_data, headers=headers)


def export_http_metrics_to_polars(client_name: str = "default") -> pl.DataFrame:
    """İstemci metriklerini Polars DataFrame olarak döner."""
    client = get_client(name=client_name)
    return client.export_metrics_to_polars()


def export_http_metrics_to_duckdb(
    db_path: str | Path | None = None, client_name: str = "default"
) -> int:
    """İstemci metriklerini DuckDB tablosuna yazar."""
    client = get_client(name=client_name)
    return client.export_metrics_to_duckdb(db_path=db_path)


__all__: list[str] = [
    "DEFAULT_BASE_RETRY_DELAY_S",
    "DEFAULT_HTTP_METRICS_DB_PATH",
    "DEFAULT_MAX_METRICS_HISTORY",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_RETRY_DELAY_S",
    "DEFAULT_TIMEOUT",
    "DEFAULT_USER_AGENT",
    "AsyncHTTPClient",
    "async_get_bytes",
    "async_get_json",
    "async_get_text",
    "async_post_json",
    "close_all_clients",
    "export_http_metrics_to_duckdb",
    "export_http_metrics_to_polars",
    "get_client",
]
