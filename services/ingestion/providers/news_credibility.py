"""
ALPHA BIST — News Credibility Weighting

Kaynak güvenilirlik ağırlıkları:
KAP: 1.00
BIST: 1.00
Güvenilir haber: 0.80
Google News: 0.50
Sosyal medya: 0.20-0.50
"""

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()

# Varsayılan sabitler
DEFAULT_UNKNOWN_CREDIBILITY: float = 0.40
DEFAULT_MIN_WEIGHTED_IMPORTANCE: float = 0.30


@dataclass
class NewsSource:
    """Haber kaynağı bilgisi.

    Attributes:
        name: Kaynak adı.
        credibility: Güvenilirlik skoru (0.0-1.0).
        category: Kategori (official, reliable, general, social).
        language: Dil kodu.
    """

    name: str
    credibility: float
    category: str
    language: str = "tr"

    def __repr__(self) -> str:
        """NewsSource string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return (
            f"NewsSource(name={self.name!r}, "
            f"credibility={self.credibility}, category={self.category!r})"
        )


# Kaynak tanımları
DEFAULT_NEWS_SOURCES: dict[str, NewsSource] = {
    # Resmi kaynaklar (1.00)
    "kap": NewsSource("KAP", 1.00, "official"),
    "bist": NewsSource("BIST", 1.00, "official"),
    "tcmb": NewsSource("TCMB", 1.00, "official"),
    "spk": NewsSource("SPK", 1.00, "official"),
    # Güvenilir haber (0.80)
    "aa": NewsSource("Anadolu Ajansı", 0.85, "reliable"),
    "reuters": NewsSource("Reuters", 0.90, "reliable"),
    "bloomberg": NewsSource("Bloomberg", 0.90, "reliable"),
    "dunya": NewsSource("Dünya", 0.80, "reliable"),
    "paraanaliz": NewsSource("ParaAnaliz", 0.75, "reliable"),
    "borsagundem": NewsSource("Borsa Gündem", 0.70, "reliable"),
    "investing": NewsSource("Investing.com", 0.70, "reliable"),
    # Genel haber (0.50)
    "google_news": NewsSource("Google News", 0.50, "general"),
    "yahoo": NewsSource("Yahoo Finance", 0.60, "general"),
    "cnbc": NewsSource("CNBC", 0.70, "general"),
    # Sosyal medya (0.20-0.50)
    "x": NewsSource("X (Twitter)", 0.30, "social"),
    "reddit": NewsSource("Reddit", 0.25, "social"),
    "stocktwits": NewsSource("StockTwits", 0.35, "social"),
    "forum": NewsSource("Forum", 0.20, "social"),
}


class NewsCredibility:
    """Haber güvenilirlik ağırlıklandırma sistemi."""

    def __repr__(self) -> str:
        """NewsCredibility string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return f"NewsCredibility(sources={len(DEFAULT_NEWS_SOURCES)})"

    def get_credibility(self, source: str) -> float:
        """Kaynak güvenilirlik skorunu döndürür (0-1).

        Args:
            source: Kaynak adı.

        Returns:
            Güvenilirlik skoru (0.0-1.0).
        """
        source_lower = source.lower().strip()

        # Doğrudan eşleşme
        if source_lower in DEFAULT_NEWS_SOURCES:
            return DEFAULT_NEWS_SOURCES[source_lower].credibility

        # Kısmi eşleşme
        for key, src in DEFAULT_NEWS_SOURCES.items():
            if key in source_lower or source_lower in key:
                return src.credibility

        # Bilinmeyen kaynak
        logger.warning("Bilinmeyen haber kaynağı, varsayılan güvenilirlik kullanılıyor", source=source)
        return DEFAULT_UNKNOWN_CREDIBILITY

    def get_category(self, source: str) -> str:
        """Kaynak kategorisini döndürür.

        Args:
            source: Kaynak adı.

        Returns:
            Kategori string'i (official, reliable, general, social, unknown).
        """
        source_lower = source.lower().strip()
        for key, src in DEFAULT_NEWS_SOURCES.items():
            if key in source_lower or source_lower in key:
                return src.category
        return "unknown"

    def weighted_importance(self, raw_importance: float, source: str) -> float:
        """Ağırlıklandırılmış önem skoru hesaplar.

        Args:
            raw_importance: Ham önem skoru (0-1).
            source: Kaynak adı.

        Returns:
            Ağırlıklandırılmış önem (0-1).
        """
        credibility = self.get_credibility(source)
        return raw_importance * credibility

    def should_process(self, source: str, importance: float) -> bool:
        """Bu haber işlenmeli mi kontrol eder.

        Düşük güvenilirlik + düşük önem = atla.

        Args:
            source: Kaynak adı.
            importance: Ham önem skoru (0-1).

        Returns:
            True: İşlenmeli, False: Atlanmalı.
        """
        credibility = self.get_credibility(source)
        weighted = importance * credibility

        return weighted > DEFAULT_MIN_WEIGHTED_IMPORTANCE

    def get_source_report(self) -> dict[str, dict[str, Any]]:
        """Tüm kaynakların raporunu döndürür.

        Returns:
            {kaynak_key: rapor_sözlüğü} yapısı.
        """
        return {
            key: {
                "name": src.name,
                "credibility": src.credibility,
                "category": src.category,
            }
            for key, src in DEFAULT_NEWS_SOURCES.items()
        }


# Singleton
news_credibility = NewsCredibility()


__all__ = ["NewsSource", "NewsCredibility", "news_credibility"]
