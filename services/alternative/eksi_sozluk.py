"""
ALPHA BIST — Ekşi Sözlük Sentiment Adapter v1.0

Ekşi Sözlük sentiment analizi.
Türk kamuoyu duyarlılığı için kullanılır.

Features:
- eksi_sentiment: Ortalama sentiment (-1 ile +1)
- eksi_volume: Entry sayısı
- eksi_positive_ratio: Pozitif entry oranı
- eksi_avg_favorites: Ortalama favori sayısı
- eksi_sentiment_momentum: Sentiment değişim hızı
"""

import re
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from .base import BaseAdapter

logger = structlog.get_logger()


class EksiSozlukAdapter(BaseAdapter):
    """Ekşi Sözlük sentiment adapter'ı."""

    source_name = "eksi_sozluk"
    rate_limit = 5

    # BIST ticker → Ekşi başlık mapping
    TICKER_TOPICS: dict[str, list[str]] = {
        "THYAO": ["thy", "türk hava yolları", "turkish airlines", "thyao"],
        "GARAN": ["garanti bankası", "garanti bbva", "garanti"],
        "AKBNK": ["akbank"],
        "ASELS": ["aselsan"],
        "BIMAS": ["bim", "bim mağazaları"],
        "EREGL": ["ereğli demir çelik", "erdemir"],
        "KCHOL": ["koç holding", "koç grubu"],
        "SAHOL": ["sabancı holding", "sabancı"],
        "SISE": ["şişe cam", "şisecam"],
        "TUPRS": ["tüpraş"],
        "TCELL": ["turkcell"],
        "TTKOM": ["türk telekom"],
        "FROTO": ["ford otosan"],
        "TOASO": ["tofaş", "togg"],
        "MGROS": ["migros"],
        "ULKER": ["ülker"],
        "ARCLK": ["arçelik"],
        "VESTL": ["vestel"],
    }

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """Ekşi Sözlük verisi çek.

        Args:
            ticker: Hisse sembolü (ör. THYAO, GARAN).
            **kwargs: Ek parametreler.

        Returns:
            Entry listesi ve metadata içeren sözlük veya None.
        """
        topics = self.TICKER_TOPICS.get(ticker.upper())
        if not topics:
            return None

        try:
            all_entries = []
            for topic in topics:
                entries = await self._scrape_topic(topic)
                all_entries.extend(entries)

            if not all_entries:
                return None

            return {
                "entries": all_entries,
                "total_count": len(all_entries),
                "ticker": ticker,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            logger.warning("Ekşi Sözlük scrape failed", ticker=ticker, error=str(e))
            return None

    async def _scrape_topic(self, topic: str) -> list[dict]:
        """Başlıktaki entry'leri scrape et.

        Args:
            topic: Ekşi Sözlük başlık adı.

        Returns:
            Entry sözlükleri listesi (text, favorites, date).
        """
        try:
            import aiohttp
            from bs4 import BeautifulSoup

            # URL-safe topic adı
            topic_slug = topic.lower().replace(" ", "-")
            topic_slug = re.sub(r"[^a-z0-9ğüşıöç-]", "", topic_slug)
            url = f"https://eksisozluk.com/{topic_slug}--sayfa=1"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return []

                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")

                    entries = []
                    entry_items = soup.select(".content, .entry-content, [data-entry-id]")

                    for item in entry_items[:30]:  # Max 30 entry
                        text = item.get_text(strip=True)
                        if len(text) < 10:
                            continue

                        # Favori sayısı
                        fav_elem = item.select_one(".favorite-count, .fav-count")
                        fav_count = 0
                        if fav_elem:
                            fav_match = re.search(r"(\d+)", fav_elem.text)
                            if fav_match:
                                fav_count = int(fav_match.group(1))

                        # Tarih
                        date_elem = item.select_one(".entry-date, time, .date")
                        entry_date = date_elem.text.strip() if date_elem else ""

                        entries.append(
                            {
                                "text": text[:500],  # İlk 500 karakter
                                "favorites": fav_count,
                                "date": entry_date,
                            }
                        )

                    return entries

        except ImportError as e:
            logger.warning("Missing dependency for Ekşi scraping", missing=str(e))
            return []
        except Exception as e:
            logger.debug("Ekşi scrape error", topic=topic, error=str(e))
            return []

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """Ekşi Sözlük feature'larını hesapla.

        Args:
            data: collect() ile döndürülen veri.
            ticker: Hisse sembolü.

        Returns:
            Feature sözlüğü.
        """
        if not data or not data.get("entries"):
            return {}

        entries = data["entries"]
        total = len(entries)
        if total == 0:
            return {}

        # Basit keyword-based sentiment (LLM sentiment ayrı modülde)
        sentiments = [self._basic_sentiment(e["text"]) for e in entries]
        favorites = [e.get("favorites", 0) for e in entries]

        positive_count = sum(1 for s in sentiments if s > 0.1)
        negative_count = sum(1 for s in sentiments if s < -0.1)

        features = {
            "eksi_sentiment": float(np.mean(sentiments)),
            "eksi_volume": float(total),
            "eksi_positive_ratio": positive_count / total,
            "eksi_negative_ratio": negative_count / total,
            "eksi_avg_favorites": float(np.mean(favorites)) if favorites else 0,
            "eksi_max_favorites": float(max(favorites)) if favorites else 0,
            "eksi_sentiment_std": float(np.std(sentiments)),
            "eksi_controversial": negative_count / max(positive_count, 1),  # Tartışma oranı
        }

        return features

    def _basic_sentiment(self, text: str) -> float:
        """Keyword tabanlı basit sentiment analizi (-1 ile +1 arası).

        Olumsuzluk ekleri (değil, yok, asla) ile birlikte çalışır.

        Args:
            text: Analiz edilecek metin.

        Returns:
            -1 (negatif) ile +1 (pozitif) arası sentiment skoru.
        """
        text_lower = text.lower()
        words = text_lower.split()

        positive_words = [
            "güzel",
            "harika",
            "mükemmel",
            "başarılı",
            "iyi",
            "yükseliş",
            "artış",
            "kâr",
            "büyüme",
            "kazanç",
            "olumlu",
            "destek",
            "güçlü",
            "parlak",
            "muhteşem",
            "süper",
            "devam",
            "potansiyel",
        ]

        negative_words = [
            "kötü",
            "berbat",
            "başarısız",
            "düşüş",
            "kayıp",
            "zarar",
            "olumsuz",
            "zayıf",
            "tehlike",
            "risk",
            "batmak",
            "çökmek",
            "iflas",
            "skandal",
            "düzenleme",
            "sorun",
            "kriz",
            "çöküş",
        ]

        pos_count = 0
        neg_count = 0
        negation_words = {"değil", "yok", "olmayan", "değildir", "olmaz", "hiç", "asla", "ne", "olmadı"}
        negate = False
        for word in words:
            if word in negation_words:
                negate = True
                continue
            if word in positive_words:
                if negate:
                    neg_count += 1
                else:
                    pos_count += 1
                negate = False
            elif word in negative_words:
                if negate:
                    pos_count += 1
                else:
                    neg_count += 1
                negate = False

        total = pos_count + neg_count
        if total == 0:
            return 0.0

        return (pos_count - neg_count) / total


# Singleton
eksi_sozluk_adapter = EksiSozlukAdapter()
