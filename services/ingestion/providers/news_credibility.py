"""
ALPHA BIST - News Credibility Weighting

Kaynak güvenilirlik ağırlıkları:
KAP: 1.00
BIST: 1.00
Güvenilir haber: 0.80
Google News: 0.50
Sosyal medya: 0.20-0.50
"""

from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class NewsSource:
    """Haber kaynağı bilgisi."""

    name: str
    credibility: float  # 0-1
    category: str  # official, reliable, general, social
    language: str = "tr"


# Kaynak tanımları
NEWS_SOURCES: dict[str, NewsSource] = {
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

    def get_credibility(self, source: str) -> float:
        """Kaynak güvenilirlik skoru (0-1)."""
        source_lower = source.lower().strip()

        # Doğrudan eşleşme
        if source_lower in NEWS_SOURCES:
            return NEWS_SOURCES[source_lower].credibility

        # Kısmi eşleşme
        for key, src in NEWS_SOURCES.items():
            if key in source_lower or source_lower in key:
                return src.credibility

        # Bilinmeyen kaynak
        logger.debug("Unknown news source", source=source)
        return 0.40  # Varsayılan

    def get_category(self, source: str) -> str:
        """Kaynak kategorisi."""
        source_lower = source.lower().strip()
        for key, src in NEWS_SOURCES.items():
            if key in source_lower or source_lower in key:
                return src.category
        return "unknown"

    def weighted_importance(self, raw_importance: float, source: str) -> float:
        """
        Ağırlıklandırılmış önem skoru.

        raw_importance: Ham önem (0-1)
        source: Kaynak adı
        Returns: Ağırlıklandırılmış önem (0-1)
        """
        credibility = self.get_credibility(source)
        return raw_importance * credibility

    def should_process(self, source: str, importance: float) -> bool:
        """
        Bu haber işlenmeli mi?

        Düşük güvenilirlik + düşük önem = atla
        """
        credibility = self.get_credibility(source)
        weighted = importance * credibility

        # Eşik: ağırlıklandırılmış önem > 0.3
        return weighted > 0.3

    def get_source_report(self) -> dict[str, dict]:
        """Tüm kaynakların raporu."""
        return {
            key: {
                "name": src.name,
                "credibility": src.credibility,
                "category": src.category,
            }
            for key, src in NEWS_SOURCES.items()
        }


# Singleton
news_credibility = NewsCredibility()
