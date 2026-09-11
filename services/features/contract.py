"""ALPHA BIST — Feature Contract System.

Her feature için metadata, validation ve PIT-safety garantisi.
Feature pipeline'ın standardizasyonu için temel yapı.

Kullanım:
    from services.features.contract import feature_registry

    # Feature kaydet
    feature_registry.register(FeatureContract(
        name="rsi_14",
        source="OHLCV",
        formula="100 - (100 / (1 + RS))",
        lookback=14,
        frequency="daily",
        available_at="close",
        pit_safe=True,
        version=1,
        owner="feature-engine",
        description="14 günlük RSI göstergesi",
        value_range=(0, 100),
        validation_rules={"min": 0, "max": 100, "null_threshold": 0.1},
    ))

    # Feature doğrula
    is_valid = feature_registry.validate("rsi_14", value=65.3)

    # Tüm feature'ları listele
    all_features = feature_registry.list_all()
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

logger = structlog.get_logger(__name__)

# Feature kaynak tipleri
FeatureSource = Literal[
    "OHLCV",
    "fundamental",
    "KAP",
    "macro",
    "cross_sectional",
    "market_session",
    "circuit_breaker",
    "multi",
]

# Feature frekans tipleri
FeatureFrequency = Literal["tick", "intraday", "daily", "weekly"]

# Feature kullanılabilirlik zamanı
FeatureAvailability = Literal["close", "open", "realtime"]

# Feature kategorileri
FeatureCategory = Literal[
    "technical",
    "fundamental",
    "sentiment",
    "microstructure",
    "session",
    "risk",
    "market",
]


@dataclass
class FeatureContract:
    """Feature metadata ve validation sözleşmesi.

    Her feature için tanımlayıcı bilgiler, validasyon kuralları
    ve PIT-safety garantisi içerir.

    Attributes:
        name: Feature adı (benzersiz, snake_case).
        source: Veri kaynağı.
        formula: Hesaplama formülü/açıklaması.
        lookback: Gerekli geçmiş veri penceresi (gün).
        frequency: Hesaplama frekansı.
        available_at: Ne zaman kullanılabilir.
        pit_safe: Point-in-time güvenli mi?
        version: Sözleşme versiyonu.
        owner: Sorumlu modül.
        description: Türkçe açıklama.
        value_range: Geçerli değer aralığı (min, max).
        validation_rules: Ek validasyon kuralları.
        dependencies: Bağımlı feature'lar.
        category: Feature kategorisi.
        created_at: Oluşturulma tarihi (ISO format).
    """

    name: str
    source: FeatureSource
    formula: str
    lookback: int
    frequency: FeatureFrequency
    available_at: FeatureAvailability
    pit_safe: bool
    version: int
    owner: str
    description: str = ""
    value_range: tuple[float, float] | None = None
    validation_rules: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    category: FeatureCategory = "technical"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def validate_value(self, value: float | None) -> bool:
        """Feature değerini doğrula.

        None değerler (eksik veri) geçerli kabul edilir.
        NaN ve Inf değerler geçersizdir.

        Args:
            value: Doğrulanacak değer.

        Returns:
            True: değer geçerli. False: değer geçersiz.
        """
        if value is None:
            return True  # None = eksik veri, geçerli

        if math.isnan(value) or math.isinf(value):
            return False

        # Range kontrolü
        if self.value_range:
            min_val, max_val = self.value_range
            if value < min_val or value > max_val:
                return False

        # Validation rules
        if "min" in self.validation_rules and value < self.validation_rules["min"]:
            return False
        if "max" in self.validation_rules and value > self.validation_rules["max"]:
            return False

        return True

    def to_dict(self) -> dict[str, Any]:
        """Contract'ı dict'e çevir.

        Returns:
            Tüm attribute'ları içeren dict.
        """
        return {
            "name": self.name,
            "source": self.source,
            "formula": self.formula,
            "lookback": self.lookback,
            "frequency": self.frequency,
            "available_at": self.available_at,
            "pit_safe": self.pit_safe,
            "version": self.version,
            "owner": self.owner,
            "description": self.description,
            "value_range": list(self.value_range) if self.value_range else None,
            "validation_rules": self.validation_rules,
            "dependencies": self.dependencies,
            "category": self.category,
            "created_at": self.created_at,
        }



    def __repr__(self) -> str:
        """FeatureContract kısa temsili.
    
        Returns:
            Sınıf bilgisi.
        """
        return f"FeatureContract()"
def __repr__(self) -> str:
        """FeatureContract kısa temsili.

        Returns:
            Feature adı, versiyon ve PIT-safe durumu.
        """
        return f"FeatureContract({self.name!r}, v{self.version}, pit_safe={self.pit_safe})"
class FeatureRegistry:
    """Feature kayıt ve yönetim merkezi.

    Tüm feature contract'larını merkezi olarak yönetir,
    doğrular ve sorgular. Singleton olarak kullanılır.
    """

    def __init__(self) -> None:
        """Feature Registry başlatıcısı.

        Varsayılan feature contract'larını kaydeder.
        """
        self._contracts: dict[str, FeatureContract] = {}
        self._register_defaults()

    def register(self, contract: FeatureContract) -> None:
        """Feature contract'ı kaydet.

        Aynı isimde ve daha düşük veya eşit version'da contract
        varsa kayıt gerçekleşmez ve warning loglanır.

        Args:
            contract: Kaydedilecek FeatureContract.
        """
        if contract.name in self._contracts:
            existing = self._contracts[contract.name]
            if existing.version >= contract.version:
                logger.warning(
                    "feature_contract_version_çelişkisi",
                    name=contract.name,
                    mevcut_version=existing.version,
                    yeni_version=contract.version,
                )
                return
        self._contracts[contract.name] = contract
        logger.debug(
            "feature_kayıt_edildi",
            name=contract.name,
            version=contract.version,
        )

    def get(self, name: str) -> FeatureContract | None:
        """Feature contract'ı adına göre getir.

        Args:
            name: Feature adı.

        Returns:
            FeatureContract veya None (bulunamazsa).
        """
        return self._contracts.get(name)

    def validate(self, name: str, value: float | None) -> bool:
        """Feature değerini doğrula.

        Args:
            name: Feature adı.
            value: Doğrulanacak değer.

        Returns:
            True: değer geçerli veya feature bulunamadı (warning).
        """
        contract = self._contracts.get(name)
        if not contract:
            logger.warning("bilinmeyen_feature", name=name)
            return False
        return contract.validate_value(value)

    def list_all(self) -> list[FeatureContract]:
        """Tüm feature contract'larını listele.

        Returns:
            Kayıtlı tüm FeatureContract'ların listesi.
        """
        return list(self._contracts.values())

    def list_by_category(self, category: FeatureCategory) -> list[FeatureContract]:
        """Kategoriye göre feature listele.

        Args:
            category: Feature kategorisi.

        Returns:
            Bu kategorideki FeatureContract'ların listesi.
        """
        return [c for c in self._contracts.values() if c.category == category]

    def list_by_owner(self, owner: str) -> list[FeatureContract]:
        """Owner'a göre feature listele.

        Args:
            owner: Sorumlu modül adı.

        Returns:
            Bu owner'a ait FeatureContract'ların listesi.
        """
        return [c for c in self._contracts.values() if c.owner == owner]

    def list_pit_safe(self) -> list[FeatureContract]:
        """PIT-safe feature'ları listele.

        Returns:
            pit_safe=True olan FeatureContract'ların listesi.
        """
        return [c for c in self._contracts.values() if c.pit_safe]

    def get_names(self) -> list[str]:
        """Tüm feature isimlerini döndür.

        Returns:
            Kayıtlı feature isimlerinin listesi.
        """
        return list(self._contracts.keys())

    def get_summary(self) -> dict[str, Any]:
        """Özet istatistikler döndür.

        Returns:
            Toplam, PIT-safe/unsafe sayıları, kategori ve
            owner dağılımlarını içeren dict.
        """
        categories: dict[str, int] = {}
        owners: dict[str, int] = {}
        pit_count = 0
        for c in self._contracts.values():
            categories[c.category] = categories.get(c.category, 0) + 1
            owners[c.owner] = owners.get(c.owner, 0) + 1
            if c.pit_safe:
                pit_count += 1

        return {
            "total": len(self._contracts),
            "pit_safe": pit_count,
            "pit_unsafe": len(self._contracts) - pit_count,
            "by_category": categories,
            "by_owner": owners,
        }

    def _register_defaults(self) -> None:
        """Varsayılan feature contract'larını kaydet.

        BIST-100 piyasası için standart teknik, risk, sentiment,
        cross-sectional ve BIST-specific feature'ları tanımlar.
        """
        defaults = [
            # === PRICE CONTEXT (FeatureEngine) ===
            FeatureContract(
                name="return_1d",
                source="OHLCV",
                formula="(close[-1] / close[-2]) - 1",
                lookback=2,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="feature-engine",
                description="1 günlük getiri",
                value_range=(-0.2, 0.2),
                category="technical",
            ),
            FeatureContract(
                name="return_5d",
                source="OHLCV",
                formula="(close[-1] / close[-6]) - 1",
                lookback=6,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="feature-engine",
                description="5 günlük getiri",
                value_range=(-0.5, 0.5),
                category="technical",
            ),
            FeatureContract(
                name="return_20d",
                source="OHLCV",
                formula="(close[-1] / close[-21]) - 1",
                lookback=21,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="feature-engine",
                description="20 günlük getiri",
                value_range=(-1.0, 1.0),
                category="technical",
            ),
            FeatureContract(
                name="rsi_14",
                source="OHLCV",
                formula="100 - (100 / (1 + RS))",
                lookback=14,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="feature-engine",
                description="14 günlük RSI",
                value_range=(0, 100),
                validation_rules={"min": 0, "max": 100},
                category="technical",
            ),
            FeatureContract(
                name="volatility_20d",
                source="OHLCV",
                formula="std(log_returns[-20:]) * sqrt(252)",
                lookback=20,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="feature-engine",
                description="20 günlük yıllık volatilite",
                value_range=(0, 5.0),
                category="risk",
            ),
            FeatureContract(
                name="momentum_10d",
                source="OHLCV",
                formula="(close[-1] / close[-11]) - 1",
                lookback=11,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="feature-engine",
                description="10 günlük momentum",
                value_range=(-1.0, 1.0),
                category="technical",
            ),
            # === SEVEN MOTORS ===
            FeatureContract(
                name="rs_5d",
                source="OHLCV+benchmark",
                formula="(stock[-1]/benchmark[-1]) / (stock[-5]/benchmark[-5]) - 1",
                lookback=5,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="seven-motors",
                description="5 günlük göreli güç (endekse göre)",
                category="technical",
            ),
            FeatureContract(
                name="rs_20d",
                source="OHLCV+benchmark",
                formula="(stock[-1]/benchmark[-1]) / (stock[-20]/benchmark[-20]) - 1",
                lookback=20,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="seven-motors",
                description="20 günlük göreli güç (endekse göre)",
                category="technical",
            ),
            FeatureContract(
                name="falling_is_temporary",
                source="multi",
                formula="temporary_score / (temporary_score + permanent_score)",
                lookback=20,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="seven-motors",
                description="Düşüşün geçici olma olasılığı (0-1)",
                value_range=(0, 1),
                category="sentiment",
            ),
            FeatureContract(
                name="catch_falling_knife_risk",
                source="multi",
                formula="company_specific + liquidity_event + high_vol_crash + deep_drawdown",
                lookback=20,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="seven-motors",
                description="Düşen bıçak risk skoru (0-100)",
                value_range=(0, 100),
                category="risk",
            ),
            # === CROSS-SECTIONAL ===
            FeatureContract(
                name="cs_rank_rsi_14",
                source="cross_sectional",
                formula="percentile_rank(rsi_14, universe)",
                lookback=14,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="cross-sectional",
                description="RSI'nın evren içindeki percentile sıralaması",
                value_range=(0, 1),
                category="technical",
            ),
            FeatureContract(
                name="breadth_advance_ratio",
                source="cross_sectional",
                formula="advancing / total",
                lookback=1,
                frequency="daily",
                available_at="close",
                pit_safe=True,
                version=1,
                owner="cross-sectional",
                description="Piyasa genişliği — yükselen oranı",
                value_range=(0, 1),
                category="market",
            ),
            # === BIST-SPECIFIC ===
            FeatureContract(
                name="is_opening_auction",
                source="market_session",
                formula="phase == OPENING_AUCTION",
                lookback=0,
                frequency="intraday",
                available_at="realtime",
                pit_safe=True,
                version=1,
                owner="feature-engine",
                description="Açılış açık artırma seansında mı?",
                value_range=(0, 1),
                category="session",
            ),
            FeatureContract(
                name="ebdks_active",
                source="circuit_breaker",
                formula="endekse bağlı devre kesici aktif mi?",
                lookback=0,
                frequency="intraday",
                available_at="realtime",
                pit_safe=True,
                version=1,
                owner="feature-engine",
                description="EBDKS aktif mi?",
                value_range=(0, 1),
                category="session",
            ),
        ]

        for contract in defaults:
            self.register(contract)



    def __repr__(self) -> str:
        """FeatureRegistry kısa temsili.
    
        Returns:
            Sınıf bilgisi.
        """
        return f"FeatureRegistry()"
def __repr__(self) -> str:
        """FeatureRegistry kısa temsili.

        Returns:
            Kayıtlı feature sayısı.
        """
        return f"FeatureRegistry(features={len(self._contracts)})"
# Singleton
feature_registry = FeatureRegistry()
