"""ALPHA BIST — Feature Store Engine (Feast-Compatible Point-in-Time Architecture)

Kurumsal seviye Feature Store modülü. Feast prensiplerine uyumlu,
BIST-100 ölçeğinde Point-in-Time (PIT) feature yönetimi sağlar.

Modül bileşenleri:
    1. Entity tanımları (ticker, timestamp)
    2. Feature View & Schema tanımları (teknik, mikro-yapı, makro, model skorları)
    3. Point-in-Time (PIT / ASOF) tarihsel birleştirme (data leakage önleme)
    4. Online Store senkronizasyonu (düşük gecikmeli gerçek zamanlı çıkarım)
    5. Offline Store (DuckDB / Parquet depolama)
    6. Feature TTL, metadata ve versiyonlama

Kullanım:
    from services.features.feature_store_feast import feature_store

    # Online feature yaz
    feature_store.write_online_features("GARAN", {"rsi_14": 65.3})

    # Online feature oku
    results = feature_store.get_online_features(["GARAN"], ["bist_technical_fv:rsi_14"])

    # PIT-safe tarihsel feature
    response = feature_store.get_historical_features(
        entity_df={"ticker": ["GARAN"], "timestamp": [datetime.now(UTC)]},
        feature_refs=["bist_technical_fv:rsi_14"],
    )

    # Feature lookup
    specs = feature_store.get_feature_specs("bist_technical_fv")
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

try:
    import polars as pl
except ImportError:
    pl = None

try:
    import pandas as pd
except ImportError:
    pd = None

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

_DEFAULT_TTL_SECONDS: int = 3600
_DEFAULT_MAX_CACHE_TICKERS: int = 2000
_VALID_DTYPES: frozenset[str] = frozenset({"FLOAT", "INT", "STRING", "VECTOR"})
_NAN_LIKE: frozenset[str] = frozenset({"nan", "none", "null", "inf", "-inf"})
_OFFLINE_TABLE_NAME: str = "feature_historical"


# ---------------------------------------------------------------------------
# Veri sınıfları
# ---------------------------------------------------------------------------


@dataclass
class Entity:
    """Feature Store Entity tanımı.

    Feature'ların bağlı olduğu varlık tipini tanımlar (örn: hisse senedi).

    Args:
        name: Entity adı (örn: "ticker")
        join_key: Join anahtarı (örn: "ticker")
        description: İnsan tarafından okunabilir açıklama
        value_type: Veri tipi (STRING, INT, FLOAT)
    """

    name: str
    join_key: str
    description: str = ""
    value_type: str = "STRING"

    def __repr__(self) -> str:
        """Entity'nin kısa temsilini döndürür.

        Returns:
            Entity adı ve join key içeren字符串.
        """
        return f"Entity(name={self.name!r}, join_key={self.join_key!r})"


@dataclass
class FeatureSpec:
    """Tekil feature spesifikasyonu.

    Bir feature'ın adını, veri tipini ve açıklamasını tanımlar.

    Args:
        name: Feature adı (örn: "rsi_14")
        dtype: Veri tipi (FLOAT, INT, STRING, VECTOR)
        description: İnsan tarafından okunabilir açıklama
        tags: Ek etiketler
    """

    name: str
    dtype: str
    description: str = ""
    tags: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        """FeatureSpec'in kısa temsilini döndürür.

        Returns:
            Feature adı ve dtype içeren字符串.
        """
        return f"FeatureSpec(name={self.name!r}, dtype={self.dtype!r})"

    def validate_value(self, value: Any) -> bool:
        """Verilen değerin bu feature'ın dtype'ına uygun olup olmadığını kontrol eder.

        Args:
            value: Kontrol edilecek değer.

        Returns:
            True ise değer geçerli, False ise geçersiz.
        """
        if value is None:
            return True  # None = eksik veri, geçerli

        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return True  # NaN/Inf = eksik/uygunsuz veri, geçerli (işaretçi)

        if self.dtype == "FLOAT":
            return isinstance(value, (int, float))
        if self.dtype == "INT":
            return isinstance(value, int) or (isinstance(value, float) and value == int(value))
        if self.dtype == "STRING":
            return isinstance(value, str)
        if self.dtype == "VECTOR":
            return isinstance(value, (list, tuple))

        return True  # Bilinmeyen dtype — geçerli say


@dataclass
class FeatureView:
    """Mantıksal feature grubu.

    İlgili feature'ları bir arada tutan, TTL ve kaynak bilgisi içeren yapı.
    Örn: momentum_features, microstructure_features.

    Args:
        name: Feature View adı
        entities: Bu view'a ait entity listesi
        features: Feature spesifikasyon listesi
        ttl_days: Feature'ların geçerlilik süresi (gün)
        source: Veri kaynağı (timescaledb, parquet, duckdb)
        online_enabled: Online store'a senkronize edilsin mi
        tags: Ek etiketler
    """

    name: str
    entities: list[str]
    features: list[FeatureSpec]
    ttl_days: int = 365
    source: str = "timescaledb"
    online_enabled: bool = True
    tags: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        """FeatureView'in kısa temsilini döndürür.

        Returns:
            View adı ve feature sayısı içeren字符串.
        """
        return f"FeatureView(name={self.name!r}, features={len(self.features)})"

    def get_feature(self, name: str) -> FeatureSpec | None:
        """View içindeki feature'ı adına göre bulur.

        Args:
            name: Feature adı.

        Returns:
            FeatureSpec bulunduysa, None değilse.
        """
        for feat in self.features:
            if feat.name == name:
                return feat
        return None

    def ttl_seconds(self) -> int:
        """TTL'yi saniye cinsinden döndürür.

        Returns:
            ttl_days × 86400.
        """
        return self.ttl_days * 86400


@dataclass
class HistoricalFeatureResponse:
    """Point-in-time join sonrası dönen feature matrisi.

    Args:
        feature_names: Feature adları listesi
        entity_keys: Entity key listesi
        num_rows: Satır sayısı
        data: Feature verisi (column-oriented dict)
        timestamp_column: Timestamp kolon adı
        is_pit_clean: PIT-safety doğrulandı mı
    """

    feature_names: list[str]
    entity_keys: list[str]
    num_rows: int
    data: dict[str, list[Any]]
    timestamp_column: str = "timestamp"
    is_pit_clean: bool = True

    def __repr__(self) -> str:
        """HistoricalFeatureResponse'un kısa temsilini döndürür.

        Returns:
            Satır sayısı ve feature sayısı içeren字符串.
        """
        return (
            f"HistoricalFeatureResponse(rows={self.num_rows}, "
            f"features={len(self.feature_names)}, pit_clean={self.is_pit_clean})"
        )

    def to_polars(self) -> Any:
        """Polars DataFrame'e çevirir.

        Returns:
            Feature verisini içeren Polars DataFrame.

        Raises:
            ImportError: polars yüklü değilse.
        """
        if pl is None:
            raise ImportError("polars yüklü değil — pip install polars")
        return pl.DataFrame(self.data)

    def to_pandas(self) -> Any:
        """Pandas DataFrame'e çevirir.

        Returns:
            Feature verisini içeren Pandas DataFrame.

        Raises:
            ImportError: pandas yüklü değilse.
        """
        if pd is None:
            raise ImportError("pandas yüklü değil — pip install pandas")
        return pd.DataFrame(self.data)

    def to_dict(self) -> dict[str, list[Any]]:
        """Ham veriyi dict olarak döndürür.

        Returns:
            Column-oriented data dict'i.
        """
        return dict(self.data)


# ---------------------------------------------------------------------------
# Ana sınıf
# ---------------------------------------------------------------------------


class BISTFeatureStore:
    """Feast prensiplerine uyumlu, BIST-100 ölçeğinde Point-in-Time Feature Store.

    Entity-FeatureView mimarisi ile çalışır. Online store (in-memory cache)
    ve offline store (DuckDB) arasında senkronizasyon sağlar.

    Sınıf, modül sonundaki ``feature_store`` singleton örneği üzerinden kullanılır.

    Args:
        offline_store_path: DuckDB dosya yolu. None ise offline store devre dışı.

    Özellikler:
        - Entity ve FeatureView kayıt/yonetimi
        - Online feature yazma/okuma (düşük gecikmeli)
        - Point-in-time tarihsel feature birleştirme (DuckDB ASOF join)
        - Online cache TTL mekanizması
        - Feature dtype validasyonu
        - Feature lookup ve schema sorgulama
    """

    def __init__(self, offline_store_path: str | None = None) -> None:
        """BISTFeatureStore başlatıcısı.

        Args:
            offline_store_path: DuckDB dosya yolu. None ise offline store devre dışı.

        Returns:
            None.

        Raises:
            Yok — başlatma hatası oluşmaz.
        """
        self.offline_store_path = offline_store_path
        self._entities: dict[str, Entity] = {}
        self._feature_views: dict[str, FeatureView] = {}
        self._online_cache: dict[str, dict[str, Any]] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._metadata_registry: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._register_default_bist_definitions()

    def __repr__(self) -> str:
        """BISTFeatureStore'un kısa temsilini döndürür.

        Returns:
            Entity ve feature view sayılarını içeren字符串.
        """
        return (
            f"BISTFeatureStore(entities={len(self._entities)}, "
            f"views={len(self._feature_views)}, "
            f"offline={'enabled' if self.offline_store_path else 'disabled'})"
        )

    # ------------------------------------------------------------------
    # Tanım kayıt
    # ------------------------------------------------------------------

    def _register_default_bist_definitions(self) -> None:
        """BIST-100 standart entity ve feature view tanımlarını kaydeder.

        Idempotent: aynı isimle tekrar kayıt yapmaz, mevcut tanımın üzerine yazmaz.
        Ticker entity'si ve üç standart feature view (teknik, mikro-yapı, makro/rejim) oluşturulur.

        Returns:
            None.
        """
        # 1. Entity — idempotent
        if "ticker" not in self._entities:
            ticker_entity = Entity(
                name="ticker",
                join_key="ticker",
                description="BIST Hisse Senedi Kodu",
            )
            self.register_entity(ticker_entity)

        # 2. Technical Feature View
        if "bist_technical_fv" not in self._feature_views:
            tech_view = FeatureView(
                name="bist_technical_fv",
                entities=["ticker"],
                features=[
                    FeatureSpec("rsi_14", "FLOAT", "14 Günlük Göreceli Güç Endeksi"),
                    FeatureSpec("macd_diff", "FLOAT", "MACD Histogram Farkı"),
                    FeatureSpec("momentum_20d", "FLOAT", "20 Günlük Fiyat Momentumu"),
                    FeatureSpec("volatility_20d", "FLOAT", "20 Günlük Yıllıklandırılmış Volatilite"),
                    FeatureSpec("bb_pct_b", "FLOAT", "Bollinger Bandı Konum Yüzdesi"),
                ],
                ttl_days=730,
                tags={"domain": "technical", "frequency": "daily"},
            )
            self.register_feature_view(tech_view)

        # 3. Microstructure Feature View
        if "bist_microstructure_fv" not in self._feature_views:
            micro_view = FeatureView(
                name="bist_microstructure_fv",
                entities=["ticker"],
                features=[
                    FeatureSpec("amihud_illiquidity", "FLOAT", "Amihud Fiyat Etkisi / Likidite Oranı"),
                    FeatureSpec("corwin_schultz_spread", "FLOAT", "Corwin-Schultz Alış-Satış Makası Tahmini"),
                    FeatureSpec("order_flow_imbalance", "FLOAT", "Emir Akışı Dengesizliği (OFI)"),
                    FeatureSpec("garman_klass_vol", "FLOAT", "Garman-Klass Ekstremum Volatilitesi"),
                    FeatureSpec("volume_ratio_5d_20d", "FLOAT", "5G / 20G Hacim Oranı"),
                ],
                ttl_days=365,
                tags={"domain": "microstructure", "frequency": "daily"},
            )
            self.register_feature_view(micro_view)

        # 4. Macro & Regime Feature View
        if "bist_macro_regime_fv" not in self._feature_views:
            macro_view = FeatureView(
                name="bist_macro_regime_fv",
                entities=["ticker"],
                features=[
                    FeatureSpec("usdtry_momentum_5d", "FLOAT", "USD/TRY 5 Günlük Değişim"),
                    FeatureSpec("bist_beta_60d", "FLOAT", "BIST-100 Endeks Betası"),
                    FeatureSpec("cds_spread_change", "FLOAT", "Türkiye 5Y CDS Değişimi"),
                    FeatureSpec("market_regime_id", "INT", "Tespit Edilen Piyasa Rejim Kodu"),
                ],
                ttl_days=730,
                tags={"domain": "macro", "frequency": "daily"},
            )
            self.register_feature_view(macro_view)

    def register_entity(self, entity: Entity) -> bool:
        """Yeni bir Entity kaydeder.

        Aynı isimle kayıt varsa üzerine yazar ve False döndürür.

        Args:
            entity: Kaydedilecek Entity örneği.

        Returns:
            True ise yeni kayıt, False ise mevcut kayıt güncellendi.
        """
        is_new = entity.name not in self._entities
        with self._lock:
            self._entities[entity.name] = entity
        logger.info(
            "entity_registered",
            name=entity.name,
            join_key=entity.join_key,
            is_new=is_new,
        )
        return is_new

    def register_feature_view(self, fv: FeatureView) -> bool:
        """Yeni bir Feature View kaydeder ve metadata registry'yi günceller.

        Aynı isimle kayıt varsa üzerine yazar ve False döndürür.

        Args:
            fv: Kaydedilecek FeatureView örneği.

        Returns:
            True ise yeni kayıt, False ise mevcut kayıt güncellendi.
        """
        is_new = fv.name not in self._feature_views
        with self._lock:
            self._feature_views[fv.name] = fv
            # Eski metadata girişlerini temizle
            stale_keys = [k for k in self._metadata_registry if k.startswith(f"{fv.name}:")]
            for k in stale_keys:
                del self._metadata_registry[k]
            # Yeni metadata'yı kaydet
            for feat in fv.features:
                self._metadata_registry[f"{fv.name}:{feat.name}"] = {
                    "dtype": feat.dtype,
                    "description": feat.description,
                    "view": fv.name,
                    "tags": fv.tags,
                }
        logger.info(
            "feature_view_registered",
            view_name=fv.name,
            num_features=len(fv.features),
            is_new=is_new,
        )
        return is_new

    # ------------------------------------------------------------------
    # Feature Lookup
    # ------------------------------------------------------------------

    def get_feature_specs(self, view_name: str) -> list[FeatureSpec]:
        """View adına göre feature spesifikasyonlarını döndürür.

        Args:
            view_name: Feature View adı.

        Returns:
            FeatureSpec listesi.

        Raises:
            KeyError: View bulunamazsa.
        """
        with self._lock:
            fv = self._feature_views.get(view_name)
        if fv is None:
            raise KeyError(f"Feature View bulunamadı: {view_name}")
        return list(fv.features)

    def get_feature_spec(self, view_name: str, feature_name: str) -> FeatureSpec:
        """Tek bir feature spesifikasyonunu döndürür.

        Args:
            view_name: Feature View adı.
            feature_name: Feature adı.

        Returns:
            FeatureSpec.

        Raises:
            KeyError: View veya feature bulunamazsa.
        """
        with self._lock:
            fv = self._feature_views.get(view_name)
        if fv is None:
            raise KeyError(f"Feature View bulunamadı: {view_name}")
        feat = fv.get_feature(feature_name)
        if feat is None:
            raise KeyError(f"Feature bulunamadı: {view_name}:{feature_name}")
        return feat

    def get_entity(self, name: str) -> Entity:
        """Entity'yi adına göre döndürür.

        Args:
            name: Entity adı.

        Returns:
            Entity.

        Raises:
            KeyError: Entity bulunamazsa.
        """
        with self._lock:
            entity = self._entities.get(name)
        if entity is None:
            raise KeyError(f"Entity bulunamadı: {name}")
        return entity

    def list_views(self) -> list[str]:
        """Kayıtlı tüm feature view adlarını döndürür.

        Returns:
            Feature view adları listesi.
        """
        with self._lock:
            return list(self._feature_views.keys())

    def list_entities(self) -> list[str]:
        """Kayıtlı tüm entity adlarını döndürür.

        Returns:
            Entity adları listesi.
        """
        with self._lock:
            return list(self._entities.keys())

    # ------------------------------------------------------------------
    # Online Store
    # ------------------------------------------------------------------

    def write_online_features(self, entity_key: str, features: dict[str, Any]) -> None:
        """Online Store'a güncel feature yazar.

        Düşük gecikmeli inference için feature'ları in-memory cache'e yazar.
        Cache TTL mekanizması ile eski veriler otomatik temizlenir.
        Feature değerleri dtype uyumluluğu açısından doğrulanır.

        Args:
            entity_key: Entity anahtarı (örn: "GARAN").
            features: Feature adı → değer sözlüğü.

        Returns:
            None.

        Raises:
            ValueError: entity_key boş string ise.
        """
        if not entity_key:
            raise ValueError("entity_key boş olamaz")

        # Feature dtype validasyonu
        validated_features = self._validate_features(features)

        now = time.monotonic()
        with self._lock:
            # TTL temizliği — eski cache girişlerini kaldır
            self._evict_expired(now)

            # Cache boyut kontrolü
            if (
                entity_key not in self._online_cache
                and len(self._online_cache) >= _DEFAULT_MAX_CACHE_TICKERS
            ):
                # En eski girişi kaldır (LRU benzeri)
                oldest_key = min(self._cache_timestamps, key=self._cache_timestamps.get)
                del self._online_cache[oldest_key]
                del self._cache_timestamps[oldest_key]
                logger.warning(
                    "cache_evicted_oldest",
                    evicted_key=oldest_key,
                    reason="max_tickers_reached",
                )

            if entity_key not in self._online_cache:
                self._online_cache[entity_key] = {}
            self._online_cache[entity_key].update(validated_features)
            self._cache_timestamps[entity_key] = now

        logger.debug(
            "online_features_written",
            entity_key=entity_key,
            feature_count=len(validated_features),
        )

    def _validate_features(self, features: dict[str, Any]) -> dict[str, Any]:
        """Feature değerlerini dtype uyumluluğu açısından doğrular.

        Uyuşmayan değerler için warning loglanır ve değer korunur (fail-open).
        None/NaN/Inf değerleri korunur — eksik veri işaretçisi olarak kabul edilir.

        Args:
            features: Feature adı → değer sözlüğü.

        Returns:
            Doğranmış feature sözlüğü (orijinal değerler korunur).
        """
        validated: dict[str, Any] = {}
        for name, value in features.items():
            # Metadata anahtarlarını atla
            if name.startswith("__"):
                validated[name] = value
                continue

            # Metadata registry'den dtype'ı bul
            meta = self._metadata_registry.get(name)
            if meta is None:
                # Bilinmeyen feature — doğrulama yapma
                validated[name] = value
                continue

            # None/NaN/Inf kontrolü — eksik veri olarak kabul et
            if value is None:
                validated[name] = value
                continue
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                validated[name] = value
                continue

            # Dtype doğrulama
            expected_dtype = meta.get("dtype", "FLOAT")
            spec = FeatureSpec(name=name, dtype=expected_dtype)
            if not spec.validate_value(value):
                logger.warning(
                    "feature_dtype_mismatch",
                    feature=name,
                    expected=expected_dtype,
                    actual_type=type(value).__name__,
                    value=str(value)[:100],
                )

            validated[name] = value

        return validated

    def get_online_features(
        self,
        entity_keys: list[str],
        feature_refs: list[str],
    ) -> list[dict[str, Any]]:
        """Online Store'dan düşük gecikmeli canlı çıkarım feature'larını getirir.

        Args:
            entity_keys: Entity key listesi (örn: ["GARAN", "AKBNK"]).
            feature_refs: Feature referans listesi
                (örn: ["bist_technical_fv:rsi_14"]).

        Returns:
            Her entity için feature değerlerini içeren dict listesi.
            Cache'de bulunamayan feature'lar float("nan") olarak döner.

        Raises:
            Yok — bulunamayan feature'lar NaN döner.
        """
        now = time.monotonic()
        results: list[dict[str, Any]] = []

        with self._lock:
            self._evict_expired(now)

            for key in entity_keys:
                record: dict[str, Any] = {"ticker": key}
                cached = self._online_cache.get(key, {})
                for ref in feature_refs:
                    feat_name = ref.split(":")[-1] if ":" in ref else ref
                    record[feat_name] = cached.get(feat_name, float("nan"))
                results.append(record)

        return results

    def _evict_expired(self, now: float) -> None:
        """TTL süresi dolmuş cache girişlerini temizler.

        Args:
            now: Şu anki monotonic timestamp.

        Returns:
            None.
        """
        expired_keys: list[str] = []
        for key, ts in self._cache_timestamps.items():
            if now - ts > _DEFAULT_TTL_SECONDS:
                expired_keys.append(key)

        for key in expired_keys:
            del self._online_cache[key]
            del self._cache_timestamps[key]
            logger.debug("cache_entry_expired", entity_key=key)

    # ------------------------------------------------------------------
    # Offline Store (PIT-Safe Tarihsel)
    # ------------------------------------------------------------------

    def get_historical_features(
        self,
        entity_df: dict[str, list[Any]],
        feature_refs: list[str],
    ) -> HistoricalFeatureResponse:
        """Point-in-Time (ASOF) gelecek verisi sızdırmaz tarihsel feature birleştirme.

        Her entity-timestamp çifti için, o timestamp'te bilinen en son feature
        değerlerini döndürür. Gelecekteki veri sızıntısı (leakage) kesinlikle önlenir.

        Offline store mevcut değilse NaN döndürülür — SAHTE VERİ ÜRETİLMEZ.

        Args:
            entity_df: Entity ve timestamp çiftleri.
                Örn: {"ticker": ["GARAN", "THYAO"], "timestamp": [datetime(...), datetime(...)]}
            feature_refs: İstenen feature referans listesi.
                Örn: ["bist_technical_fv:rsi_14"]

        Returns:
            HistoricalFeatureResponse: PIT-clean feature matrisi.

        Raises:
            Yok — boş entity_df için boş response döner.
        """
        tickers = entity_df.get("ticker", [])
        timestamps = entity_df.get("timestamp", [])
        n_rows = len(tickers)

        if n_rows == 0:
            logger.warning(
                "get_historical_features_empty_entity",
                entity_df_keys=list(entity_df.keys()),
            )
            return HistoricalFeatureResponse(
                feature_names=[],
                entity_keys=[],
                num_rows=0,
                data={},
                is_pit_clean=True,
            )

        feat_names = [f.split(":")[-1] if ":" in f else f for f in feature_refs]
        data_out: dict[str, list[Any]] = {
            "ticker": list(tickers),
            "timestamp": list(timestamps),
        }

        # Offline store'dan PIT-safe tarihsel veri çekimi.
        # Her (ticker, timestamp) çifti için, o timestamp'te bilinen
        # en son feature değeri ASOF join ile alınır.
        # Offline store mevcut değilse NaN döndürülür — SAHTE VERİ ÜRETİLMEZ.
        if self.offline_store_path is not None:
            self._query_offline_store(tickers, timestamps, feat_names, n_rows, data_out)
        else:
            # Offline store tanımlı değil — NaN döndür.
            # SAHTE VERİ ÜRETİLMEZ.
            logger.warning(
                "offline_store_not_configured",
                message="Offline store path tanımlı değil. NaN değerler döndürülüyor.",
            )
            for feat in feat_names:
                data_out[feat] = [float("nan")] * n_rows

        return HistoricalFeatureResponse(
            feature_names=feat_names,
            entity_keys=tickers,
            num_rows=n_rows,
            data=data_out,
            is_pit_clean=True,
        )

    def _query_offline_store(
        self,
        tickers: list[str],
        timestamps: list[Any],
        feat_names: list[str],
        n_rows: int,
        data_out: dict[str, list[Any]],
    ) -> None:
        """DuckDB offline store'dan PIT-safe ASOF sorgusu çalıştırır.

        Batch sorgu ile tüm feature'ları tek seferde çeker — performans optimizasyonu.

        Args:
            tickers: Ticker listesi.
            timestamps: Timestamp listesi.
            feat_names: Feature adları listesi.
            n_rows: Satır sayısı.
            data_out: Sonuçların yazılacağı dict (in-place güncellenir).

        Returns:
            None — data_out in-place güncellenir.

        Raises:
            Yok — hatalar loglanır ve NaN döndürülür.
        """
        if not feat_names:
            return

        try:
            import duckdb

            con = duckdb.connect(self.offline_store_path, read_only=True)

            # Batch sorgu: tüm feature'ları tek seferde çek
            placeholders = ", ".join(["?"] * len(feat_names))
            query = f"""
                SELECT ticker, feature_name, feature_value, timestamp
                FROM {_OFFLINE_TABLE_NAME}
                WHERE feature_name IN ({placeholders})
                ORDER BY ticker, feature_name, timestamp
            """
            try:
                all_rows = con.execute(query, feat_names).fetchall()
            except Exception as e:
                logger.debug("batch_query_failed", error=str(e))
                all_rows = []

            # Sonuçları indexle: (ticker, feature_name) → [(timestamp, value), ...]
            indexed: dict[tuple[str, str], list[tuple[Any, float]]] = {}
            for row in all_rows:
                key = (row[0], row[1])
                if key not in indexed:
                    indexed[key] = []
                indexed[key].append((row[3], float(row[2])))

            # Her (ticker, timestamp) çifti için ASOF lookup
            for feat in feat_names:
                values: list[Any] = []
                for i in range(n_rows):
                    ticker = tickers[i] if i < len(tickers) else None
                    ts = timestamps[i] if i < len(timestamps) else None
                    if ticker is None or ts is None:
                        values.append(float("nan"))
                        continue

                    entries = indexed.get((ticker, feat), [])
                    # Binary search ile ASOF: timestamp'ten önceki en son kayıt
                    best = float("nan")
                    for entry_ts, entry_val in reversed(entries):
                        if entry_ts <= ts:
                            best = entry_val
                            break
                    values.append(best)

                data_out[feat] = values

            con.close()
        except Exception as e:
            logger.error(
                "offline_store_query_failed",
                path=self.offline_store_path,
                error=str(e),
            )
            for feat in feat_names:
                data_out[feat] = [float("nan")] * n_rows

    # ------------------------------------------------------------------
    # Şema & Metadata
    # ------------------------------------------------------------------

    def get_schema_summary(self) -> dict[str, Any]:
        """Feature Store'un tüm şema ve view özetini döndürür.

        Her view için feature listesi, dtype'lar, entity'ler, TTL, source
        ve online_enabled durumunu içerir.

        Returns:
            Entity sayısı, view sayısı, feature sayısı ve
            view detaylarını içeren sözlük.

        Raises:
            Yok.
        """
        with self._lock:
            return {
                "total_entities": len(self._entities),
                "total_views": len(self._feature_views),
                "total_features": len(self._metadata_registry),
                "views": {
                    name: {
                        "features": [
                            {"name": f.name, "dtype": f.dtype, "description": f.description}
                            for f in fv.features
                        ],
                        "entities": fv.entities,
                        "ttl_days": fv.ttl_days,
                        "source": fv.source,
                        "online_enabled": fv.online_enabled,
                    }
                    for name, fv in self._feature_views.items()
                },
            }

    def get_metadata(self, feature_ref: str) -> dict[str, Any] | None:
        """Tek bir feature'ın metadata'sını döndürür.

        Args:
            feature_ref: "view_name:feature_name" formatında referans.

        Returns:
            Metadata dict'i veya None.
        """
        with self._lock:
            return self._metadata_registry.get(feature_ref)


# Singleton
feature_store = BISTFeatureStore()
