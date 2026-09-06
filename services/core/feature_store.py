"""ALPHA BIST — Feature Store v1.0 (In-Memory + Redis Cache).

F-024: Özellikler (features) her seferinde yeniden hesaplanmak yerine iki katmanlı olarak önbelleğe alınır:
- Bellek içi (In-Memory) LRU önbellek (hızlı yol - mikrosaniye seviyesi)
- Redis önbellek (süreçler arası paylaşım ve dayanıklılık)
- TTL tabanlı otomatik geçersiz kılma (invalidation)
- Özellik kümesine duyarlı hash anahtarlama
- Polars entegrasyonu ile analitik izleme ve sıfır kopya veri aktarımı
- Çoklu hisse (batch) okuma/yazma desteği

Kullanım:
    from services.core.feature_store import feature_store

    features = feature_store.get("THYAO", "2026-09-06", ["rsi_14", "macd"])
    feature_store.set("THYAO", "2026-09-06", {"rsi_14": 56.4, "macd": 1.25}, ttl=3600)
    batch_features = feature_store.get_batch(["THYAO", "GARAN"], "2026-09-06", ["rsi_14", "pe_ratio"])
"""

from __future__ import annotations

import functools
import hashlib
import math
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

import orjson
import polars as pl
import structlog
from opentelemetry import trace

from . import redis_helper

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.feature_store")

DEFAULT_MAX_CACHE_SIZE: int = 10000
DEFAULT_CACHE_TTL_SECONDS: int = 3600
REDIS_DELETE_CHUNK_SIZE: int = 1000


def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Metotları OpenTelemetry span'i ile sarmalayan kurumsal izleme dekoratörü.

    Args:
        span_name: Üretilecek span için benzersiz izleme adı.

    Returns:
        Dekoratör fonksiyonu.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


def _clean_feature_val(val: Any) -> float:
    """Özellik değerini güvenli bir şekilde float tipine dönüştürür.

    None veya geçersiz değerlerde TypeError fırlatmak yerine NaN döndürür.
    """
    if val is None:
        return float("nan")
    try:
        f_val = float(val)
        return f_val if not math.isinf(f_val) else float("nan")
    except (ValueError, TypeError):
        return float("nan")


class FeatureStore:
    """İki katmanlı özellik önbellek motoru — bellek içi LRU + opsiyonel Redis."""

    def __init__(
        self,
        max_size: int = DEFAULT_MAX_CACHE_SIZE,
        default_ttl: int = DEFAULT_CACHE_TTL_SECONDS,
        redis_url: str | None = None,
    ) -> None:
        """FeatureStore nesnesini ilklendirir.

        Args:
            max_size: Bellek içi tutulabilecek azami özellik kümesi adedi.
            default_ttl: Saniye cinsinden varsayılan geçerlilik süresi.
            redis_url: Opsiyonel özel Redis bağlantı adresi (None ise merkezi havuz kullanılır).
        """
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size: int = max(1, int(max_size))
        self._default_ttl: int = max(1, int(default_ttl))
        self._hits: int = 0
        self._misses: int = 0
        self._lock: threading.RLock = threading.RLock()

        # Redis bağlantısı ilklendirmesi
        if redis_url:
            try:
                import redis

                self._redis: Any = redis.Redis.from_url(redis_url, decode_responses=False)
                logger.info("ozellik_deposu_ozel_redis_aktif", url=redis_url)
            except Exception as e:
                logger.warning(
                    "ozellik_deposu_ozel_redis_baglanti_hatasi",
                    url=redis_url,
                    hata=str(e),
                )
                self._redis = redis_helper.get_client()
        else:
            self._redis = redis_helper.get_client()

        if self._redis:
            logger.info("özellik_deposu_redis_aktif", mod="paylasimli_redis_havuzu")
        else:
            logger.info("özellik_deposu_yalnizca_bellek_modunda", mod="in_memory_lru")

    def __repr__(self) -> str:
        with self._lock:
            total = self._hits + self._misses
            rate = round((self._hits / total) * 100, 1) if total > 0 else 0.0
            return (
                f"FeatureStore(boyut={len(self._cache)}/{self._max_size}, "
                f"isabet={self._hits}, iska={self._misses}, basari=%{rate}, "
                f"redis={'aktif' if self._redis is not None else 'pasif'})"
            )

    def _make_key(self, ticker: str, date: str, features: list[str]) -> str:
        """Belirtilen hisse, tarih ve özellik listesi için deterministik önbellek anahtarı üretir.

        Args:
            ticker: BIST hisse sembolü (örn. 'THYAO').
            date: İşlem tarihi (örn. '2026-09-06').
            features: İstenen özellik adları listesi.

        Returns:
            Benzersiz önbellek anahtarı metni.
        """
        feat_hash = hashlib.md5(",".join(sorted(features)).encode("utf-8")).hexdigest()[:8]
        return f"feat:{ticker.upper()}:{date}:{feat_hash}"

    @otel_trace("feature_store.get")
    def get(
        self,
        ticker: str,
        date: str,
        feature_names: list[str],
    ) -> dict[str, float] | None:
        """Önbellekten hisse özelliklerini çeker (önce L1 bellek içi, sonra L2 Redis).

        Args:
            ticker: BIST hisse sembolü.
            date: İlgili tarih formatı.
            feature_names: İstenen özellik isimleri listesi.

        Returns:
            Özellik adı ve sayısal değer sözlüğü ya da bulunamazsa None.
        """
        key = self._make_key(ticker, date, feature_names)
        now = time.time()

        # 1. Aşama: Bellek İçi LRU Önbellek (L1)
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if now < entry["expires_at"]:
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return dict(entry["features"])
                del self._cache[key]

        # 2. Aşama: Redis Paylaşımlı Önbellek (L2)
        if self._redis:
            try:
                data = self._redis.get(key)
                if data:
                    raw_features = orjson.loads(data)
                    features = {str(k): _clean_feature_val(v) for k, v in raw_features.items()}
                    with self._lock:
                        self._cache[key] = {
                            "features": features,
                            "expires_at": now + self._default_ttl,
                        }
                        self._cache.move_to_end(key)
                        self._hits += 1
                    return features
            except Exception as e:
                logger.debug("ozellik_deposu_redis_okuma_hatasi", anahtar=key, hata=str(e))

        with self._lock:
            self._misses += 1
        return None

    @otel_trace("feature_store.get_batch")
    def get_batch(
        self,
        tickers: list[str],
        date: str,
        feature_names: list[str],
    ) -> dict[str, dict[str, float]]:
        """Birden çok hisse için özellikleri toplu (batch) olarak sorgular.

        L1'de bulunamayanları tek bir Redis mget çağrısıyla getirir.

        Args:
            tickers: Hisse sembolleri listesi.
            date: İşlem tarihi.
            feature_names: İstenen özellikler listesi.

        Returns:
            {ticker: {özellik_adı: değer}} eşlemesi (bulunamayanlar içermez).
        """
        results: dict[str, dict[str, float]] = {}
        missing_tickers: list[str] = []
        key_to_ticker: dict[str, str] = {}
        now = time.time()

        # 1. Aşama: Toplu L1 Kontrolü
        with self._lock:
            for ticker in tickers:
                key = self._make_key(ticker, date, feature_names)
                key_to_ticker[key] = ticker
                if key in self._cache:
                    entry = self._cache[key]
                    if now < entry["expires_at"]:
                        self._cache.move_to_end(key)
                        self._hits += 1
                        results[ticker] = dict(entry["features"])
                        continue
                    del self._cache[key]
                missing_tickers.append(ticker)

        if not missing_tickers:
            return results

        # 2. Aşama: L2 Redis Toplu Okuma (MGET)
        if self._redis:
            try:
                missing_keys = [self._make_key(t, date, feature_names) for t in missing_tickers]
                raw_values = self._redis.mget(missing_keys)
                with self._lock:
                    for key, val in zip(missing_keys, raw_values, strict=False):
                        ticker = key_to_ticker.get(key)
                        if val and ticker:
                            parsed = orjson.loads(val)
                            features = {str(k): _clean_feature_val(v) for k, v in parsed.items()}
                            self._cache[key] = {
                                "features": features,
                                "expires_at": now + self._default_ttl,
                            }
                            self._cache.move_to_end(key)
                            self._hits += 1
                            results[ticker] = features
                        else:
                            self._misses += 1
            except Exception as e:
                logger.debug("ozellik_deposu_redis_mget_hatasi", hata=str(e))
                with self._lock:
                    self._misses += len(missing_tickers)
        else:
            with self._lock:
                self._misses += len(missing_tickers)

        return results

    @otel_trace("feature_store.set")
    def set(
        self,
        ticker: str,
        date: str,
        features: dict[str, Any],
        ttl: int | None = None,
        feature_names: list[str] | None = None,
    ) -> None:
        """Hesaplanan özellikleri iki katmanlı önbelleğe kaydeder.

        Args:
            ticker: BIST hisse sembolü.
            date: İşlem tarihi.
            features: Özellik adları ve sayısal değerleri sözlüğü.
            ttl: Saniye cinsinden geçerlilik süresi (None ise varsayılan uygulanır).
            feature_names: İsteğe bağlı anahtar için baz alınacak özellik isimleri.
        """
        if feature_names is None:
            feature_names = list(features.keys())
        key = self._make_key(ticker, date, feature_names)
        effective_ttl = max(1, int(ttl or self._default_ttl))
        now = time.time()
        clean_features = {str(k): _clean_feature_val(v) for k, v in features.items()}

        # 1. Aşama: Bellek İçi (L1)
        with self._lock:
            self._cache[key] = {
                "features": clean_features,
                "expires_at": now + effective_ttl,
            }
            self._cache.move_to_end(key)

            # LRU tahliyesi (eviction)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

        # 2. Aşama: Redis (L2)
        if self._redis:
            try:
                self._redis.setex(key, effective_ttl, orjson.dumps(clean_features).decode("utf-8"))
            except Exception as e:
                logger.debug("ozellik_deposu_redis_yazma_hatasi", anahtar=key, hata=str(e))

    @otel_trace("feature_store.set_batch")
    def set_batch(
        self,
        date: str,
        batch_features: dict[str, dict[str, Any]],
        ttl: int | None = None,
    ) -> None:
        """Birden çok hisse için hesaplanan özellikleri toplu olarak önbelleğe yazar.

        Args:
            date: İşlem tarihi.
            batch_features: {ticker: {özellik_adı: değer}} sözlüğü.
            ttl: Saniye cinsinden geçerlilik süresi.
        """
        if not batch_features:
            return

        effective_ttl = max(1, int(ttl or self._default_ttl))
        now = time.time()
        redis_entries: dict[str, str] = {}

        with self._lock:
            for ticker, features in batch_features.items():
                clean_features = {str(k): _clean_feature_val(v) for k, v in features.items()}
                key = self._make_key(ticker, date, list(features.keys()))
                self._cache[key] = {
                    "features": clean_features,
                    "expires_at": now + effective_ttl,
                }
                self._cache.move_to_end(key)
                if self._redis:
                    redis_entries[key] = orjson.dumps(clean_features).decode("utf-8")

            # LRU tahliyesi
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

        if self._redis and redis_entries:
            try:
                pipeline = self._redis.pipeline()
                for key, val in redis_entries.items():
                    pipeline.setex(key, effective_ttl, val)
                pipeline.execute()
            except Exception as e:
                logger.debug("ozellik_deposu_redis_toplu_yazma_hatasi", hata=str(e))

    @otel_trace("feature_store.invalidate")
    def invalidate(self, ticker: str, date: str | None = None) -> int:
        """Belirtilen hisse veya hisse+tarih için önbelleği temizler.

        Args:
            ticker: Temizlenecek BIST sembolü.
            date: Belirtilirse yalnızca o tarihteki kayıtlar temizlenir; None ise tüm tarihler temizlenir.

        Returns:
            Temizlenen bellek içi anahtar sayısı.
        """
        symbol = ticker.upper()
        prefix = f"feat:{symbol}:{date}:" if date else f"feat:{symbol}:"

        deleted_count = 0
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]
                deleted_count += 1

        if self._redis:
            try:
                pattern = f"feat:{symbol}:{date}:*" if date else f"feat:{symbol}:*"
                matching_keys = list(self._redis.scan_iter(match=pattern))
                if matching_keys:
                    for i in range(0, len(matching_keys), REDIS_DELETE_CHUNK_SIZE):
                        chunk = matching_keys[i : i + REDIS_DELETE_CHUNK_SIZE]
                        self._redis.delete(*chunk)
            except Exception as e:
                logger.debug(
                    "ozellik_deposu_redis_gecersiz_kilma_hatasi",
                    sembol=symbol,
                    tarih=date,
                    hata=str(e),
                )

        return deleted_count

    def get_stats(self) -> dict[str, Any]:
        """Önbellek çalışma istatistiklerini döndürür.

        Returns:
            Önbellek boyutu, isabet ve ıskalama metriklerini içeren sözlük.
        """
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0.0,
                "redis_connected": self._redis is not None,
            }

    def export_stats_to_polars(self) -> pl.DataFrame:
        """Önbellek performans metriklerini Polars DataFrame olarak dışa aktarır (GEMINI.md Kural 2).

        Returns:
            Tek satırlık metrik Polars DataFrame'i.
        """
        stats = self.get_stats()
        return pl.DataFrame(
            {
                "size": pl.Series([stats["size"]], dtype=pl.Int64),
                "max_size": pl.Series([stats["max_size"]], dtype=pl.Int64),
                "hits": pl.Series([stats["hits"]], dtype=pl.Int64),
                "misses": pl.Series([stats["misses"]], dtype=pl.Int64),
                "hit_rate_pct": pl.Series([stats["hit_rate"]], dtype=pl.Float64),
                "redis_connected": pl.Series([stats["redis_connected"]], dtype=pl.Boolean),
            }
        )

    def export_cached_keys_to_polars(self) -> pl.DataFrame:
        """Bellekte aktif olarak bulunan anahtarları Polars DataFrame olarak dışa aktarır.

        Returns:
            Önbellekteki anahtar, son kullanma zamanı ve kalan süreyi içeren Polars DataFrame.
        """
        empty_schema = {
            "key": pl.Utf8,
            "expires_at": pl.Float64,
            "remaining_seconds": pl.Float64,
        }
        with self._lock:
            now = time.time()
            records: list[dict[str, Any]] = []
            for k, entry in self._cache.items():
                exp = float(entry.get("expires_at", 0.0))
                records.append(
                    {
                        "key": k,
                        "expires_at": exp,
                        "remaining_seconds": max(0.0, exp - now),
                    }
                )
        if not records:
            return pl.DataFrame(schema=empty_schema)
        return pl.DataFrame(records)

    def export_features_to_polars(
        self,
        ticker: str,
        date: str,
        feature_names: list[str],
    ) -> pl.DataFrame:
        """Belirtilen hisse ve tarih için özellikleri doğrudan Polars DataFrame olarak döndürür.

        Args:
            ticker: BIST hisse sembolü.
            date: İşlem tarihi.
            feature_names: Özellikler listesi.

        Returns:
            Hisse, tarih ve sütun bazında özellikleri içeren Polars DataFrame'i.
        """
        feats = self.get(ticker, date, feature_names)
        if not feats:
            schema = {"ticker": pl.Utf8, "date": pl.Utf8, **{f: pl.Float64 for f in feature_names}}
            return pl.DataFrame(schema=schema)

        data = {"ticker": [ticker.upper()], "date": [date], **{k: [v] for k, v in feats.items()}}
        return pl.DataFrame(data)


# Global tekil nesne
feature_store: FeatureStore = FeatureStore()

__all__ = [
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_MAX_CACHE_SIZE",
    "REDIS_DELETE_CHUNK_SIZE",
    "FeatureStore",
    "feature_store",
    "otel_trace",
]
