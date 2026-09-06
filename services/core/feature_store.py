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

import asyncio
import contextlib
import functools
import hashlib
import math
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Final

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import trace

from services.core.debounce import configure_duckdb_wal

from . import redis_helper

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.feature_store")

DEFAULT_MAX_CACHE_SIZE: int = 10000
DEFAULT_CACHE_TTL_SECONDS: int = 3600
REDIS_DELETE_CHUNK_SIZE: int = 1000
DEFAULT_FEATURE_STORE_DB_PATH: str = "data/feature_store_cache.duckdb"


def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Metotları OpenTelemetry span'i ile sarmalayan kurumsal izleme dekoratörü.

    Senkron ve asenkron fonksiyonları otomatik algılayarak span yaşam döngüsünü
    korur.

    Args:
        span_name: Üretilecek span için benzersiz izleme adı.

    Returns:
        Dekoratör fonksiyonu.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
                with tracer.start_as_current_span(span_name):
                    return await func(self, *args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
                with tracer.start_as_current_span(span_name):
                    return func(self, *args, **kwargs)

            return sync_wrapper

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
    """İki katmanlı özellik önbellek motoru — bellek içi LRU + opsiyonel Redis + DuckDB kalıcılık."""

    def __init__(
        self,
        max_size: int = DEFAULT_MAX_CACHE_SIZE,
        default_ttl: int = DEFAULT_CACHE_TTL_SECONDS,
        redis_url: str | None = None,
        db_path: str = DEFAULT_FEATURE_STORE_DB_PATH,
    ) -> None:
        """FeatureStore nesnesini ilklendirir.

        Args:
            max_size: Bellek içi tutulabilecek azami özellik kümesi adedi.
            default_ttl: Saniye cinsinden varsayılan geçerlilik süresi.
            redis_url: Opsiyonel özel Redis bağlantı adresi (None ise merkezi havuz kullanılır).
            db_path: Kalıcı yerel yedekleme için DuckDB dosya yolu.
        """
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._master_cache: dict[str, dict[str, Any]] = {}  # "ticker:date" -> {features, expires_at}
        self._max_size: int = max(1, int(max_size))
        self._default_ttl: int = max(1, int(default_ttl))
        self._db_path: str = str(db_path)
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

    def _make_master_key(self, ticker: str, date: str) -> str:
        """Hisse ve tarih bazlı ana birleştirilmiş özellik havuzu anahtarı üretir."""
        return f"feat_master:{ticker.upper()}:{date}"

    @otel_trace("feature_store.get")
    def get(
        self,
        ticker: str,
        date: str,
        feature_names: list[str],
    ) -> dict[str, float] | None:
        """Önbellekten hisse özelliklerini çeker (L1 bellek içi, L1 master alt küme, L2 Redis).

        Args:
            ticker: BIST hisse sembolü.
            date: İlgili tarih formatı.
            feature_names: İstenen özellik isimleri listesi.

        Returns:
            Özellik adı ve sayısal değer sözlüğü ya da bulunamazsa None.
        """
        symbol = ticker.upper()
        key = self._make_key(symbol, date, feature_names)
        master_key = self._make_master_key(symbol, date)
        now = time.time()

        # 1. Aşama: Tam Anahtar Eşleşmesi (L1 Bellek İçi LRU)
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if now < entry["expires_at"]:
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return dict(entry["features"])
                del self._cache[key]

            # 1.1 Aşama: Ana Havuz (Master Cache) Alt Küme Çözümleme (Kural 6 Optimizasyonu)
            if master_key in self._master_cache:
                master_entry = self._master_cache[master_key]
                if now < master_entry["expires_at"]:
                    master_feats = master_entry["features"]
                    if all(fname in master_feats for fname in feature_names):
                        subset = {fname: master_feats[fname] for fname in feature_names}
                        self._cache[key] = {
                            "features": subset,
                            "expires_at": master_entry["expires_at"],
                        }
                        self._cache.move_to_end(key)
                        self._hits += 1
                        return subset
                else:
                    del self._master_cache[master_key]

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

                # Redis Master Key Kontrolü
                master_data = self._redis.get(master_key)
                if master_data:
                    raw_master = orjson.loads(master_data)
                    master_feats = {str(k): _clean_feature_val(v) for k, v in raw_master.items()}
                    if all(fname in master_feats for fname in feature_names):
                        subset = {fname: master_feats[fname] for fname in feature_names}
                        with self._lock:
                            self._master_cache[master_key] = {
                                "features": master_feats,
                                "expires_at": now + self._default_ttl,
                            }
                            self._cache[key] = {
                                "features": subset,
                                "expires_at": now + self._default_ttl,
                            }
                            self._cache.move_to_end(key)
                            self._hits += 1
                        return subset
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
                symbol = ticker.upper()
                key = self._make_key(symbol, date, feature_names)
                master_key = self._make_master_key(symbol, date)
                key_to_ticker[key] = symbol

                if key in self._cache:
                    entry = self._cache[key]
                    if now < entry["expires_at"]:
                        self._cache.move_to_end(key)
                        self._hits += 1
                        results[symbol] = dict(entry["features"])
                        continue
                    del self._cache[key]

                # Alt küme kontrolü
                if master_key in self._master_cache:
                    m_entry = self._master_cache[master_key]
                    if now < m_entry["expires_at"]:
                        m_feats = m_entry["features"]
                        if all(fn in m_feats for fn in feature_names):
                            subset = {fn: m_feats[fn] for fn in feature_names}
                            self._cache[key] = {
                                "features": subset,
                                "expires_at": m_entry["expires_at"],
                            }
                            self._cache.move_to_end(key)
                            self._hits += 1
                            results[symbol] = subset
                            continue
                    else:
                        del self._master_cache[master_key]

                missing_tickers.append(symbol)

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
        symbol = ticker.upper()
        if feature_names is None:
            feature_names = list(features.keys())
        key = self._make_key(symbol, date, feature_names)
        master_key = self._make_master_key(symbol, date)
        effective_ttl = max(1, int(ttl or self._default_ttl))
        now = time.time()
        clean_features = {str(k): _clean_feature_val(v) for k, v in features.items()}

        # 1. Aşama: Bellek İçi (L1) - Hem spesifik anahtar hem master havuz güncellenir
        with self._lock:
            expires_at = now + effective_ttl
            self._cache[key] = {
                "features": clean_features,
                "expires_at": expires_at,
            }
            self._cache.move_to_end(key)

            # Master havuz birleştirme
            if master_key in self._master_cache and now < self._master_cache[master_key]["expires_at"]:
                self._master_cache[master_key]["features"].update(clean_features)
                self._master_cache[master_key]["expires_at"] = max(
                    self._master_cache[master_key]["expires_at"], expires_at
                )
            else:
                self._master_cache[master_key] = {
                    "features": dict(clean_features),
                    "expires_at": expires_at,
                }

            # LRU tahliyesi (eviction)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

            if len(self._master_cache) > self._max_size:
                # Master havuzdan en eski süresi dolmuşları temizle
                cutoff_keys = [mk for mk, val in self._master_cache.items() if now >= val["expires_at"]]
                for mk in cutoff_keys:
                    del self._master_cache[mk]

        # 2. Aşama: Redis (L2)
        if self._redis:
            try:
                payload = orjson.dumps(clean_features).decode("utf-8")
                self._redis.setex(key, effective_ttl, payload)
                # Master Redis anahtarını da güncelle
                with self._lock:
                    master_payload = orjson.dumps(self._master_cache[master_key]["features"]).decode("utf-8")
                self._redis.setex(master_key, effective_ttl, master_payload)
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
                symbol = ticker.upper()
                clean_features = {str(k): _clean_feature_val(v) for k, v in features.items()}
                key = self._make_key(symbol, date, list(features.keys()))
                master_key = self._make_master_key(symbol, date)
                exp = now + effective_ttl

                self._cache[key] = {
                    "features": clean_features,
                    "expires_at": exp,
                }
                self._cache.move_to_end(key)

                if master_key in self._master_cache and now < self._master_cache[master_key]["expires_at"]:
                    self._master_cache[master_key]["features"].update(clean_features)
                    self._master_cache[master_key]["expires_at"] = max(
                        self._master_cache[master_key]["expires_at"], exp
                    )
                else:
                    self._master_cache[master_key] = {
                        "features": dict(clean_features),
                        "expires_at": exp,
                    }

                if self._redis:
                    redis_entries[key] = orjson.dumps(clean_features).decode("utf-8")
                    redis_entries[master_key] = orjson.dumps(self._master_cache[master_key]["features"]).decode("utf-8")

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
        master_prefix = f"feat_master:{symbol}:{date}" if date else f"feat_master:{symbol}:"

        deleted_count = 0
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]
                deleted_count += 1

            master_keys_to_remove = [mk for mk in self._master_cache if mk.startswith(master_prefix)]
            for mk in master_keys_to_remove:
                del self._master_cache[mk]

        if self._redis:
            try:
                pattern = f"feat:{symbol}:{date}:*" if date else f"feat:{symbol}:*"
                master_pattern = f"feat_master:{symbol}:{date}*" if date else f"feat_master:{symbol}:*"
                matching_keys = list(self._redis.scan_iter(match=pattern)) + list(
                    self._redis.scan_iter(match=master_pattern)
                )
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
                "master_size": len(self._master_cache),
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
                "master_size": pl.Series([stats["master_size"]], dtype=pl.Int64),
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
            "key": pl.String,
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
        return pl.DataFrame(records, schema=empty_schema)

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
            schema = {"ticker": pl.String, "date": pl.String, **{f: pl.Float64 for f in feature_names}}
            return pl.DataFrame(schema=schema)

        data = {"ticker": [ticker.upper()], "date": [date], **{k: [v] for k, v in feats.items()}}
        return pl.DataFrame(data)

    def export_to_duckdb(
        self,
        db_path: str | None = None,
        table_name: str = "feature_store_snapshot",
    ) -> int:
        """Bellekteki tüm master özellikleri yerel DuckDB tablosuna anlık görüntü olarak kaydeder.

        Args:
            db_path: DuckDB dosya yolu (None ise varsayılan kullanılır).
            table_name: Hedef tablo adı.

        Returns:
            Kaydedilen toplam hisse-tarih kayıt adedi.
        """
        target_path = str(db_path or self._db_path)
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
            raise ValueError(f"Geçersiz tablo adı: {table_name}")

        records: list[dict[str, Any]] = []
        with self._lock:
            for master_key, entry in self._master_cache.items():
                parts = master_key.split(":")
                if len(parts) >= 3:
                    symbol = parts[1]
                    date_val = parts[2]
                    records.append({
                        "ticker": symbol,
                        "date": date_val,
                        "features_json": orjson.dumps(entry["features"], default=str).decode("utf-8"),
                        "expires_at": entry["expires_at"],
                    })

        if not records:
            return 0

        df = pl.DataFrame(records)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size == 0:
            with contextlib.suppress(OSError):
                target.unlink()

        with duckdb.connect(target_path) as conn:
            configure_duckdb_wal(conn)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    ticker VARCHAR,
                    date VARCHAR,
                    features_json VARCHAR,
                    expires_at DOUBLE,
                    PRIMARY KEY (ticker, date)
                )
            """)
            conn.register("df_features_view", df.to_arrow())
            conn.execute(f"""
                INSERT INTO {table_name}
                SELECT * FROM df_features_view
                ON CONFLICT (ticker, date) DO UPDATE SET
                    features_json = EXCLUDED.features_json,
                    expires_at = EXCLUDED.expires_at
            """)

        return df.height

    def load_from_duckdb(
        self,
        db_path: str | None = None,
        table_name: str = "feature_store_snapshot",
    ) -> int:
        """DuckDB anlık görüntüsünden süresi dolmamış özellikleri bellek içi önbelleğe geri yükler.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Kaynak tablo adı.

        Returns:
            Yüklenen toplam hisse-tarih kayıt adedi.
        """
        target_path = str(db_path or self._db_path)
        target = Path(target_path)
        if not target.exists() or target.stat().st_size == 0:
            return 0

        now = time.time()
        loaded = 0
        try:
            with duckdb.connect(target_path, read_only=True) as conn:
                rows = conn.execute(
                    f"SELECT ticker, date, features_json, expires_at FROM {table_name} WHERE expires_at > ?",
                    [now],
                ).fetchall()

                with self._lock:
                    for ticker, date_val, feat_json, expires_at in rows:
                        try:
                            raw = orjson.loads(feat_json)
                            clean = {str(k): _clean_feature_val(v) for k, v in raw.items()}
                            master_key = self._make_master_key(ticker, date_val)
                            self._master_cache[master_key] = {
                                "features": clean,
                                "expires_at": float(expires_at),
                            }
                            loaded += 1
                        except Exception:
                            continue
        except Exception as exc:
            logger.warning("feature_store_duckdb_yukleme_hatasi", hata=str(exc))

        return loaded


# Global tekil nesne
feature_store: Final[FeatureStore] = FeatureStore()


def export_feature_stats_to_polars() -> pl.DataFrame:
    """Önbellek performans metriklerini Polars DataFrame olarak dışa aktarır."""
    return feature_store.export_stats_to_polars()


def export_features_to_polars(
    ticker: str,
    date: str,
    feature_names: list[str],
) -> pl.DataFrame:
    """Belirtilen hisse ve tarih için özellikleri doğrudan Polars DataFrame olarak döndürür."""
    return feature_store.export_features_to_polars(ticker, date, feature_names)


def export_features_to_duckdb(
    db_path: str = DEFAULT_FEATURE_STORE_DB_PATH,
    table_name: str = "feature_store_snapshot",
) -> int:
    """Bellekteki özellikleri yerel DuckDB tablosuna anlık görüntü olarak kaydeder."""
    return feature_store.export_to_duckdb(db_path=db_path, table_name=table_name)


def load_features_from_duckdb(
    db_path: str = DEFAULT_FEATURE_STORE_DB_PATH,
    table_name: str = "feature_store_snapshot",
) -> int:
    """DuckDB anlık görüntüsünden özellikleri bellek içi önbelleğe geri yükler."""
    return feature_store.load_from_duckdb(db_path=db_path, table_name=table_name)


__all__: Final[list[str]] = [
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_FEATURE_STORE_DB_PATH",
    "DEFAULT_MAX_CACHE_SIZE",
    "REDIS_DELETE_CHUNK_SIZE",
    "FeatureStore",
    "export_feature_stats_to_polars",
    "export_features_to_duckdb",
    "export_features_to_polars",
    "feature_store",
    "load_features_from_duckdb",
    "otel_trace",
]


