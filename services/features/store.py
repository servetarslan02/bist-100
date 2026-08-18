"""
ALPHA BIST — Feature Store v2.0

Nihai mimari:
- Point-in-time correctness (look-ahead bias koruması)
- Feature versioning (v1, v2, v3 — geriye dönük uyumlu)
- Feature lineage (raw → transformed → stored)
- Feature snapshots (backtest için zaman noktasına geri dönme)
- Feature metadata (timestamp, version, source, confidence, TTL)
- Hot cache + persistent storage

FAZ 1: Feature Store Rewrite
"""

import json
import hashlib
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import structlog

logger = structlog.get_logger()


# =====================================================
# Enums & Data Classes
# =====================================================

class FeatureSource(str, Enum):
    """Feature veri kaynağı."""
    CALCULATOR = "calculator"
    MOTOR = "motor"
    FUNDAMENTAL = "fundamental"
    MACRO = "macro"
    SENTIMENT = "sentiment"
    CROSS_SECTIONAL = "cross_sectional"
    BIST_SPECIFIC = "bist_specific"
    KAP = "kap"
    NEWS = "news"
    SOCIAL = "social"
    INCREMENTAL = "incremental"
    MANUAL = "manual"


class LineageStage(str, Enum):
    """Feature yaşam döngüsü aşaması."""
    RAW = "raw"                    # Ham veri
    TRANSFORMED = "transformed"    # Dönüşürülmüş
    VALIDATED = "validated"        # Doğrulanmış
    STORED = "stored"              # Depolanmış
    SERVED = "served"              # Servis edilmiş


@dataclass
class FeatureMeta:
    """Tek bir feature'ın metadata'sı."""
    name: str
    value: float
    ticker: str
    version: str
    source: FeatureSource
    lineage_stage: LineageStage
    computed_at: str                          # ISO-8601
    available_at: str                         # PIT: modelin kullanabildiği en erken an
    confidence: float = 1.0
    ttl_seconds: Optional[int] = None        # Ne kadar süre geçerli
    parent_features: List[str] = field(default_factory=list)  # Lineage: hangi feature'lardan türetildi
    checksum: str = ""                        # Değişmezlik kontrolü

    def is_expired(self) -> bool:
        """TTL dolmuş mu?"""
        if self.ttl_seconds is None:
            return False
        computed = datetime.fromisoformat(self.computed_at)
        expiry = computed + timedelta(seconds=self.ttl_seconds)
        return datetime.now(timezone.utc) >= expiry

    def is_pit_valid(self, as_of: str) -> bool:
        """Point-in-time: as_of anında bu feature kullanılabilir mi?"""
        return self.available_at <= as_of

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "ticker": self.ticker,
            "version": self.version,
            "source": self.source.value,
            "lineage_stage": self.lineage_stage.value,
            "computed_at": self.computed_at,
            "available_at": self.available_at,
            "confidence": self.confidence,
            "ttl_seconds": self.ttl_seconds,
            "parent_features": self.parent_features,
            "checksum": self.checksum,
        }


@dataclass
class FeatureSnapshot:
    """Belirli bir zamandaki feature set'inin tam görüntüsü.
    Backtest'te zaman noktasına geri dönmek için kullanılır."""
    ticker: str
    timestamp: str                            # ISO-8601
    version: str
    features: Dict[str, FeatureMeta]
    snapshot_hash: str = ""

    def __post_init__(self):
        if not self.snapshot_hash:
            self.snapshot_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = json.dumps(
            {k: v.value for k, v in sorted(self.features.items())},
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def to_raw_dict(self) -> Dict[str, float]:
        """Backward compatible: sadece isim→değer dict."""
        return {k: v.value for k, v in self.features.items()}


@dataclass
class LineageRecord:
    """Feature lineage kaydı — bir feature'ın nasıl üretildiğini izler."""
    feature_name: str
    ticker: str
    stage: LineageStage
    timestamp: str
    source: FeatureSource
    parent_features: List[str] = field(default_factory=list)
    transformation: str = ""                  # Ne işlem yapıldı
    duration_ms: float = 0.0
    input_checksum: str = ""
    output_checksum: str = ""


# =====================================================
# Feature Store v2.0
# =====================================================

class FeatureStore:
    """Feature Store v2.0 — PIT correctness, versioning, lineage.

    Mimari:
    - _store: ticker → version → {name: FeatureMeta}
    - _snapshots: ticker → [FeatureSnapshot] (son N snapshot)
    - _lineage: [LineageRecord] (son N kayıt)
    - _version_registry: feature_group → {version: formula}
    - _baselines: ticker → {name: [historical_values]} (drift detection için)
    """

    def __init__(
        self,
        max_snapshots_per_ticker: int = 252,   # ~1 yıl günlük snapshot
        max_lineage_records: int = 10000,
        default_ttl_seconds: int = 86400,       # 1 gün
    ):
        self._store: Dict[str, Dict[str, Dict[str, FeatureMeta]]] = {}
        self._snapshots: Dict[str, List[FeatureSnapshot]] = {}
        self._lineage: List[LineageRecord] = []
        self._version_registry: Dict[str, Dict[str, str]] = {}
        self._baselines: Dict[str, Dict[str, List[float]]] = {}

        self._max_snapshots = max_snapshots_per_ticker
        self._max_lineage = max_lineage_records
        self._default_ttl = default_ttl_seconds

        # Stats
        self._stats = {
            "total_sets": 0,
            "total_features": 0,
            "pit_violations": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    # =====================================================
    # SET — Feature kaydetme
    # =====================================================

    def set(
        self,
        ticker: str,
        features: Dict[str, float],
        version: str = "v1",
        source: FeatureSource = FeatureSource.CALCULATOR,
        confidence: float = 1.0,
        computed_at: Optional[str] = None,
        available_at: Optional[str] = None,
        parent_features: Optional[Dict[str, List[str]]] = None,
        ttl_seconds: Optional[int] = None,
    ) -> FeatureSnapshot:
        """Feature'ları kaydet, snapshot oluştur, lineage kaydet.

        Args:
            ticker: Hisse kodu
            features: {feature_name: value}
            version: Feature version (v1, v2, ...)
            source: Veri kaynağı
            confidence: Güven skoru (0-1)
            computed_at: Hesaplanma zamanı (None=now)
            available_at: PIT: modelin kullanabildiği en erken an (None=computed_at)
            parent_features: Lineage bilgisi {feature: [parent_features]}
            ttl_seconds: Geçerlilik süresi

        Returns:
            FeatureSnapshot
        """
        now = computed_at or datetime.now(timezone.utc).isoformat()
        pit_time = available_at or now

        # Store yapısını hazırla
        if ticker not in self._store:
            self._store[ticker] = {}
        if version not in self._store[ticker]:
            self._store[ticker][version] = {}

        # Her feature için FeatureMeta oluştur
        meta_dict: Dict[str, FeatureMeta] = {}
        for name, value in features.items():
            # NaN ve Inf filtrele
            if isinstance(value, (int, float)):
                if value != value:  # NaN
                    continue
                if value == float('inf') or value == float('-inf'):
                    continue

            parents = (parent_features or {}).get(name, [])
            checksum = hashlib.sha256(
                f"{ticker}:{name}:{value}:{version}".encode()
            ).hexdigest()[:12]

            meta = FeatureMeta(
                name=name,
                value=float(value),
                ticker=ticker,
                version=version,
                source=source,
                lineage_stage=LineageStage.STORED,
                computed_at=now,
                available_at=pit_time,
                confidence=confidence,
                ttl_seconds=ttl_seconds if ttl_seconds is not None else self._default_ttl,
                parent_features=parents,
                checksum=checksum,
            )
            self._store[ticker][version][name] = meta
            meta_dict[name] = meta

            # Baseline güncelle (drift detection için)
            if ticker not in self._baselines:
                self._baselines[ticker] = {}
            if name not in self._baselines[ticker]:
                self._baselines[ticker][name] = []
            self._baselines[ticker][name].append(float(value))
            # Son 1000 değer tut
            self._baselines[ticker][name] = self._baselines[ticker][name][-1000:]

            # Lineage kaydet
            self._add_lineage(LineageRecord(
                feature_name=name,
                ticker=ticker,
                stage=LineageStage.STORED,
                timestamp=now,
                source=source,
                parent_features=parents,
                transformation="store.set()",
                input_checksum="",
                output_checksum=checksum,
            ))

        # Snapshot oluştur
        snapshot = FeatureSnapshot(
            ticker=ticker,
            timestamp=now,
            version=version,
            features=meta_dict,
        )
        self._add_snapshot(ticker, snapshot)

        # Stats
        self._stats["total_sets"] += 1
        self._stats["total_features"] = sum(
            sum(len(v) for v in versions.values())
            for versions in self._store.values()
        )

        logger.debug(
            "Features stored",
            ticker=ticker, version=version,
            count=len(meta_dict), source=source.value,
        )
        return snapshot

    # =====================================================
    # GET — Feature okuma (PIT-aware)
    # =====================================================

    def get(
        self,
        ticker: str,
        feature_name: str,
        version: str = "latest",
        as_of: Optional[str] = None,
    ) -> Optional[float]:
        """Feature değeri getir.

        Args:
            ticker: Hisse kodu
            feature_name: Feature adı
            version: "latest" veya spesifik version
            as_of: PIT: bu an itibarıyla kullanılabilir olanı getir
        """
        ticker_features = self._store.get(ticker, {})
        if not ticker_features:
            return None

        versions_to_check = (
            sorted(ticker_features.keys(), reverse=True)
            if version == "latest"
            else [version]
        )

        for v in versions_to_check:
            if v not in ticker_features:
                continue
            meta = ticker_features[v].get(feature_name)
            if meta is None:
                continue

            # PIT kontrolü
            if as_of and not meta.is_pit_valid(as_of):
                self._stats["pit_violations"] += 1
                logger.warning(
                    "PIT violation prevented",
                    ticker=ticker, feature=feature_name,
                    available_at=meta.available_at, as_of=as_of,
                )
                continue

            # TTL kontrolü (PIT-aware: as_of anında geçerli miydi?)
            if as_of:
                # Backtest: as_of anında bu feature hâlâ geçerli miydi?
                if meta.ttl_seconds is not None:
                    computed = datetime.fromisoformat(meta.computed_at)
                    expiry = computed + timedelta(seconds=meta.ttl_seconds)
                    as_of_dt = datetime.fromisoformat(as_of)
                    if as_of_dt >= expiry:
                        logger.debug("Feature expired at as_of", ticker=ticker, feature=feature_name)
                        continue
            else:
                # Canlı sorgu: şu an geçerli mi?
                if meta.is_expired():
                    logger.debug("Feature expired", ticker=ticker, feature=feature_name)
                    continue

            self._stats["cache_hits"] += 1
            return meta.value

        self._stats["cache_misses"] += 1
        return None

    def get_all(
        self,
        ticker: str,
        version: str = "latest",
        as_of: Optional[str] = None,
        include_expired: bool = False,
    ) -> Dict[str, float]:
        """Tüm feature'ları getir.

        Args:
            ticker: Hisse kodu
            version: "latest" veya spesifik version
            as_of: PIT kontrolü
            include_expired: Süresi dolmuş feature'ları dahil et
        """
        ticker_features = self._store.get(ticker, {})
        if not ticker_features:
            return {}

        result = {}
        versions_to_check = (
            sorted(ticker_features.keys())
            if version == "latest"
            else [version]
        )

        for v in versions_to_check:
            if v not in ticker_features:
                continue
            for name, meta in ticker_features[v].items():
                # PIT kontrolü
                if as_of and not meta.is_pit_valid(as_of):
                    continue
                # TTL kontrolü (PIT-aware: get() ile tutarlı)
                if not include_expired:
                    if as_of:
                        if meta.ttl_seconds is not None:
                            computed = datetime.fromisoformat(meta.computed_at)
                            expiry = computed + timedelta(seconds=meta.ttl_seconds)
                            as_of_dt = datetime.fromisoformat(as_of)
                            if as_of_dt >= expiry:
                                continue
                    else:
                        if meta.is_expired():
                            continue
                result[name] = meta.value

        return result

    def get_meta(
        self,
        ticker: str,
        feature_name: str,
        version: str = "latest",
    ) -> Optional[FeatureMeta]:
        """Feature metadata'sını getir."""
        ticker_features = self._store.get(ticker, {})
        versions_to_check = (
            sorted(ticker_features.keys(), reverse=True)
            if version == "latest"
            else [version]
        )
        for v in versions_to_check:
            if v in ticker_features and feature_name in ticker_features[v]:
                return ticker_features[v][feature_name]
        return None

    # =====================================================
    # RANGE — Tarih aralığı sorgusu
    # =====================================================

    def get_range(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        version: str = "v1",
        feature_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Tarih aralığındaki feature'ları getir.

        Backtest'te belirli bir dönem için feature geçmişi oluşturur.
        Spec gereksinimi: get_range(ticker, start_date, end_date, version)

        Args:
            ticker: Hisse kodu
            start_date: Başlangıç tarihi (ISO-8601)
            end_date: Bitiş tarihi (ISO-8601)
            version: Feature version
            feature_name: Spesifik feature (None=tümü)

        Returns:
            [{"date": ..., "features": {name: value}}]
        """
        snapshots = self._snapshots.get(ticker, [])
        results = []

        for snap in snapshots:
            # Tarih aralığı kontrolü
            if snap.timestamp < start_date or snap.timestamp > end_date:
                continue
            # Version kontrolü
            if version != "latest" and snap.version != version:
                continue

            if feature_name:
                # Tek feature
                meta = snap.features.get(feature_name)
                if meta:
                    results.append({
                        "date": snap.timestamp,
                        "feature": feature_name,
                        "value": meta.value,
                        "version": snap.version,
                    })
            else:
                # Tüm feature'lar
                results.append({
                    "date": snap.timestamp,
                    "features": snap.to_raw_dict(),
                    "version": snap.version,
                    "snapshot_hash": snap.snapshot_hash,
                })

        return sorted(results, key=lambda x: x["date"])

    # =====================================================
    # SNAPSHOT — Zaman noktasına geri dönme
    # =====================================================

    def get_snapshot(
        self,
        ticker: str,
        timestamp: str,
        version: str = "latest",
    ) -> Optional[FeatureSnapshot]:
        """Belirli bir zamandaki snapshot'ı getir.

        Backtest'te: "2025-03-15'teki feature'lar neydi?" sorusunu cevaplar.
        """
        snapshots = self._snapshots.get(ticker, [])
        if not snapshots:
            return None

        # Timestamp'e en yakın olanı bul (veya tam eşleşme)
        best = None
        for snap in snapshots:
            if snap.timestamp <= timestamp:
                if version == "latest" or snap.version == version:
                    best = snap

        return best

    def get_latest_snapshot(self, ticker: str) -> Optional[FeatureSnapshot]:
        """En son snapshot'ı getir."""
        snapshots = self._snapshots.get(ticker, [])
        return snapshots[-1] if snapshots else None

    def _add_snapshot(self, ticker: str, snapshot: FeatureSnapshot):
        """Snapshot ekle, limit aşılırsa eskiyi at."""
        if ticker not in self._snapshots:
            self._snapshots[ticker] = []
        self._snapshots[ticker].append(snapshot)
        if len(self._snapshots[ticker]) > self._max_snapshots:
            self._snapshots[ticker] = self._snapshots[ticker][-self._max_snapshots:]

    # =====================================================
    # LINEAGE — Feature izlenebilirliği
    # =====================================================

    def get_lineage(
        self,
        ticker: Optional[str] = None,
        feature_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Feature lineage kayıtlarını getir.

        Args:
            ticker: Filtre (None=tümü)
            feature_name: Filtre (None=tümü)
            limit: Son N kayıt
        """
        records = self._lineage
        if ticker:
            records = [r for r in records if r.ticker == ticker]
        if feature_name:
            records = [r for r in records if r.feature_name == feature_name]
        return [
            {
                "feature": r.feature_name,
                "ticker": r.ticker,
                "stage": r.stage.value,
                "timestamp": r.timestamp,
                "source": r.source.value,
                "parents": r.parent_features,
                "transformation": r.transformation,
                "duration_ms": r.duration_ms,
            }
            for r in records[-limit:]
        ]

    def _add_lineage(self, record: LineageRecord):
        """Lineage kaydı ekle."""
        self._lineage.append(record)
        if len(self._lineage) > self._max_lineage:
            self._lineage = self._lineage[-self._max_lineage:]

    # =====================================================
    # VERSION REGISTRY
    # =====================================================

    def register_version(self, feature_group: str, version: str, formula: str):
        """Feature version formülünü kaydet."""
        if feature_group not in self._version_registry:
            self._version_registry[feature_group] = {}
        self._version_registry[feature_group][version] = formula
        logger.info("Feature version registered", group=feature_group, version=version)

    def get_version_info(self, feature_group: str) -> Dict[str, str]:
        """Feature version bilgisi."""
        return self._version_registry.get(feature_group, {})

    def get_all_versions(self, ticker: str) -> List[str]:
        """Ticker için mevcut tüm version'ları listele."""
        return sorted(self._store.get(ticker, {}).keys())

    # =====================================================
    # BASELINE — Drift detection için
    # =====================================================

    def get_baseline(
        self,
        ticker: str,
        feature_name: str,
        last_n: Optional[int] = None,
    ) -> List[float]:
        """Feature'ın historical baseline değerlerini getir (drift detection için)."""
        values = self._baselines.get(ticker, {}).get(feature_name, [])
        if last_n:
            return values[-last_n:]
        return values

    def get_all_baselines(self, ticker: str) -> Dict[str, List[float]]:
        """Ticker için tüm baseline'ları getir."""
        return self._baselines.get(ticker, {})

    # =====================================================
    # UTILITY
    # =====================================================

    def get_feature_hash(self, ticker: str, version: str = "latest") -> str:
        """Feature set hash (cache invalidation)."""
        features = self.get_all(ticker, version)
        data = json.dumps(features, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def get_stats(self) -> Dict[str, Any]:
        """Store istatistikleri."""
        total_tickers = len(self._store)
        total_features = sum(
            sum(len(v) for v in versions.values())
            for versions in self._store.values()
        )
        total_snapshots = sum(len(s) for s in self._snapshots.values())
        return {
            "total_tickers": total_tickers,
            "total_features": total_features,
            "total_versions": sum(len(v) for v in self._version_registry.values()),
            "total_snapshots": total_snapshots,
            "total_lineage_records": len(self._lineage),
            "pit_violations_prevented": self._stats["pit_violations"],
            "cache_hit_rate": round(
                self._stats["cache_hits"]
                / max(self._stats["cache_hits"] + self._stats["cache_misses"], 1),
                4,
            ),
        }

    def clear(self, ticker: Optional[str] = None):
        """Store temizle."""
        if ticker:
            self._store.pop(ticker, None)
            self._snapshots.pop(ticker, None)
            self._baselines.pop(ticker, None)
            # Bu ticker'ın lineage kayıtlarını da temizle
            self._lineage = [r for r in self._lineage if r.ticker != ticker]
        else:
            self._store.clear()
            self._snapshots.clear()
            self._baselines.clear()
            self._lineage.clear()
            self._stats = {
                "total_sets": 0, "total_features": 0,
                "pit_violations": 0, "cache_hits": 0, "cache_misses": 0,
            }


# Singleton
feature_store = FeatureStore()
