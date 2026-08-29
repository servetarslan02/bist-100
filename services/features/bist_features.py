from typing import Any
"""
ALPHA BIST — BIST-Specific Feature Definitions

BIST piyasasına özgü feature tanımları.
ML pipeline'ında kullanılacak BIST-specific features.

Kaynak: Borsa İstanbul kuralları, SPK mevzuatı
# Features include: momentum_10d
"""

from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class BISTFeatureDef:
    """BIST-specific feature tanımı."""

    name: str
    description: str
    category: str  # "session", "circuit_breaker", "settlement", "compliance", "microstructure"
    dtype: str = "float"  # "float", "int", "bool"
    default_value: float = 0.0
    importance: str = "high"  # "high", "medium", "low"


# BIST-specific feature tanımları
BIST_FEATURE_DEFINITIONS: list[BISTFeatureDef] = [
    # === SEANS FAZI FEATURES ===
    BISTFeatureDef(
        name="is_opening_auction",
        description="Açılış açık artırma seansında mı? (09:40-10:00)",
        category="session",
        dtype="bool",
        importance="high",
    ),
    BISTFeatureDef(
        name="is_closing_auction",
        description="Kapanış açık artırma seansında mı? (18:01-18:10)",
        category="session",
        dtype="bool",
        importance="high",
    ),
    BISTFeatureDef(
        name="is_continuous_auction",
        description="Sürekli müzayede seansında mı? (10:00-18:00)",
        category="session",
        dtype="bool",
        importance="high",
    ),
    BISTFeatureDef(
        name="is_half_day",
        description="Yarım gün mü? (resmi tatil arifesi)",
        category="session",
        dtype="bool",
        importance="medium",
    ),
    BISTFeatureDef(
        name="minutes_to_close",
        description="Kapanışa kalan dakika",
        category="session",
        dtype="float",
        importance="medium",
    ),
    BISTFeatureDef(
        name="session_progress",
        description="Seansın % kaçı tamamlandı (0.0-1.0)",
        category="session",
        dtype="float",
        importance="medium",
    ),
    # === DEVRE KESICI FEATURES ===
    BISTFeatureDef(
        name="circuit_breaker_count_today",
        description="Bugün kaç kez pay bazında devre kesici tetiklendi",
        category="circuit_breaker",
        dtype="int",
        importance="high",
    ),
    BISTFeatureDef(
        name="time_since_last_circuit_breaker",
        description="Son devre kesiciden bu yana geçen dakika",
        category="circuit_breaker",
        dtype="float",
        importance="high",
    ),
    BISTFeatureDef(
        name="ebdks_active",
        description="Endekse bağlı devre kesici aktif mi?",
        category="circuit_breaker",
        dtype="bool",
        importance="high",
    ),
    BISTFeatureDef(
        name="ebdks_triggered_today",
        description="Bugün EBDKS kaç kez tetiklendi",
        category="circuit_breaker",
        dtype="int",
        importance="high",
    ),
    BISTFeatureDef(
        name="price_distance_to_circuit_breaker",
        description="Fiyatın devre kesiciye mesafesi (%) — negatif = düşüş yönünde yakın",
        category="circuit_breaker",
        dtype="float",
        importance="high",
    ),
    BISTFeatureDef(
        name="bist100_change_pct",
        description="BIST-100 günlük değişim yüzdesi",
        category="circuit_breaker",
        dtype="float",
        importance="high",
    ),
    BISTFeatureDef(
        name="bist100_distance_to_ebdks",
        description="BIST-100'ün EBDKS tetikleme eşiğine mesafesi (%)",
        category="circuit_breaker",
        dtype="float",
        importance="high",
    ),
    # === TAKAS VE UYUMLULUK FEATURES ===
    BISTFeatureDef(
        name="is_gross_settlement",
        description="Brüt takaslı mı? (T+0, açığa satış yasak)",
        category="settlement",
        dtype="bool",
        importance="high",
    ),
    BISTFeatureDef(
        name="days_to_settlement",
        description="Takas gününe kalan gün (T+N)",
        category="settlement",
        dtype="int",
        importance="medium",
    ),
    BISTFeatureDef(
        name="spk_notification_proximity",
        description="SPK %5 bildirim eşiğine yakınlık (0-1, 1 = eşikte)",
        category="compliance",
        dtype="float",
        importance="medium",
    ),
    BISTFeatureDef(
        name="spk_mandatory_bid_proximity",
        description="SPK %10 zorunlu teklif eşiğine yakınlık (0-1)",
        category="compliance",
        dtype="float",
        importance="medium",
    ),
    BISTFeatureDef(
        name="short_sale_eligible",
        description="Açığa satışa uygun mu? (BIST-50)",
        category="compliance",
        dtype="bool",
        importance="high",
    ),
    BISTFeatureDef(
        name="uptick_rule_active",
        description="Uptick rule aktif mi? (BIST-100 %2+ düştü)",
        category="compliance",
        dtype="bool",
        importance="high",
    ),
    # === PİYASA MİKRO YAPI FEATURES ===
    BISTFeatureDef(
        name="bid_ask_spread",
        description="Alım-satım spreadi (%)",
        category="microstructure",
        dtype="float",
        importance="high",
    ),
    BISTFeatureDef(
        name="order_book_imbalance",
        description="Emir defteri dengesizliği (alım/satım oranı)",
        category="microstructure",
        dtype="float",
        importance="high",
    ),
    BISTFeatureDef(
        name="trade_size_avg",
        description="Son N işlemdeki ortalama işlem büyüklüğü",
        category="microstructure",
        dtype="float",
        importance="medium",
    ),
    BISTFeatureDef(
        name="volume_at_price_ratio",
        description="Fiyat seviyesindeki hacim / toplam hacim",
        category="microstructure",
        dtype="float",
        importance="medium",
    ),
    BISTFeatureDef(
        name="tick_direction",
        description="Son tick yönü (1 = yukarı, -1 = aşağı, 0 = değişmedi)",
        category="microstructure",
        dtype="int",
        importance="medium",
    ),
    # === PAZAR VE SEKTÖR FEATURES ===
    BISTFeatureDef(
        name="market_type",
        description="Pazar tipi (yildiz=3, ana=2, alt=1, diğer=0)",
        category="market",
        dtype="int",
        importance="medium",
    ),
    BISTFeatureDef(
        name="sector_relative_strength",
        description="Sektörel endekse göre göreli güç (son 20 gün)",
        category="market",
        dtype="float",
        importance="high",
    ),
    BISTFeatureDef(
        name="index_weight",
        description="BIST-100 endeks ağırlığı (%)",
        category="market",
        dtype="float",
        importance="medium",
    ),
    BISTFeatureDef(
        name="index_weight_change_5d",
        description="Son 5 günde endeks ağırlığı değişimi (%)",
        category="market",
        dtype="float",
        importance="medium",
    ),
    # === KURUMSAL FEATURES ===
    BISTFeatureDef(
        name="institutional_ownership_pct",
        description="Kurumsal yatırımcı sahiplik oranı (%)",
        category="institutional",
        dtype="float",
        importance="high",
    ),
    BISTFeatureDef(
        name="institutional_ownership_change",
        description="Son rapor döneminde kurumsal sahiplik değişimi (%)",
        category="institutional",
        dtype="float",
        importance="high",
    ),
    BISTFeatureDef(
        name="insider_transaction_signal",
        description="İçerden öğrenenlerin ticareti sinyali (-1 ile +1)",
        category="institutional",
        dtype="float",
        importance="high",
    ),
    # === VİOP FEATURES ===
    BISTFeatureDef(
        name="viop_open_interest_change",
        description="VİOP açık pozisyon değişimi (%)",
        category="viop",
        dtype="float",
        importance="medium",
    ),
    BISTFeatureDef(
        name="viop_basis",
        description="VİOP-spot baz (vadeli fiyat - spot fiyat)",
        category="viop",
        dtype="float",
        importance="medium",
    ),
    BISTFeatureDef(
        name="viop_basis_pct",
        description="VİOP-spot baz yüzdesi (%)",
        category="viop",
        dtype="float",
        importance="medium",
    ),
]


def get_feature_names_by_category(category: str) -> list[str]:
    """Belirli kategorideki feature isimlerini döndür."""
    return [f.name for f in BIST_FEATURE_DEFINITIONS if f.category == category]


def get_high_importance_features() -> list[str]:
    """Yüksek önemdeki feature isimlerini döndür."""
    return [f.name for f in BIST_FEATURE_DEFINITIONS if f.importance == "high"]


def get_all_feature_names() -> list[str]:
    """Tüm BIST-specific feature isimlerini döndür."""
    return [f.name for f in BIST_FEATURE_DEFINITIONS]


def get_feature_count() -> dict[str, int]:
    """Kategori bazında feature sayısı."""
    counts: dict[str, int] = {}
    for f in BIST_FEATURE_DEFINITIONS:
        counts[f.category] = counts.get(f.category, 0) + 1
    return counts


def print_feature_summary() -> Any:
    """Feature özetini yazdır."""
    counts = get_feature_count()
    total = len(BIST_FEATURE_DEFINITIONS)
    high = len(get_high_importance_features())

    logger.info(f"BIST-Specific Features: {total} toplam, {high} yüksek önem")
    for cat, count in sorted(counts.items()):
        logger.info(f"  {cat}: {count}")
