"""
ALPHA BIST — Kariyer.net Job Posting Adapter v1.0

Kariyer.net iş ilanları web scraping.
Şirket büyüme göstergesi olarak kullanılır.

Features:
- job_posting_count: Aktif ilan sayısı
- job_posting_growth_30d: 30 gün büyüme
- job_posting_growth_90d: 90 gün büyüme
- tech_hiring_ratio: Teknik pozisyon oranı
- management_hiring_ratio: Yönetim pozisyon oranı
- layoff_signal: İşten çıkarma sinyali
- avg_salary_range: Ortalama maaş aralığı
- remote_ratio: Uzaktan çalışma oranı
"""

from datetime import UTC, datetime
from typing import Any

import structlog

from .base import BaseAdapter

logger = structlog.get_logger()


class KariyerNetAdapter(BaseAdapter):
    """Kariyer.net iş ilanı adapter'ı."""

    source_name = "kariyer_net"
    rate_limit = 5  # Düşük limit — scraping koruması

    # BIST ticker → şirket adı mapping
    TICKER_COMPANY: dict[str, str] = {
        "THYAO": "Türk Hava Yolları",
        "GARAN": "Garanti BBVA",
        "AKBNK": "Akbank",
        "ASELS": "Aselsan",
        "BIMAS": "BİM",
        "EREGL": "Ereğli Demir Çelik",
        "KCHOL": "Koç Holding",
        "SAHOL": "Sabancı Holding",
        "SISE": "Şişecam",
        "TUPRS": "TÜPRAŞ",
        "PETKM": "Petkim",
        "TOASO": "Tofaş",
        "FROTO": "Ford Otosan",
        "TCELL": "Turkcell",
        "TTKOM": "Türk Telekom",
        "HALKB": "Halkbank",
        "VAKBN": "Vakıfbank",
        "ISCTR": "İş Bankası",
        "EKGYO": "Emlak Konut",
        "TAVHL": "TAV Havalimanları",
        "PGSUS": "Pegasus",
        "TABGD": "Tab Gıda",
        "MGROS": "Migros",
        "ULKER": "Ülker",
        "ARCLK": "Arçelik",
        "VESTL": "Vestel",
        "TTRAK": "Türk Traktör",
        "DOHOL": "Doğan Holding",
        "CIMSA": "Çimsa",
        "KRDMD": "Kardemir",
    }

    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """Kariyer.net verisi çek."""
        company = self.TICKER_COMPANY.get(ticker.upper())
        if not company:
            logger.debug("No company mapping for ticker", ticker=ticker)
            return None

        try:
            data = await self._scrape_postings(company, ticker)
            return data
        except Exception as e:
            logger.warning("Kariyer.net scrape failed", ticker=ticker, error=str(e))
            return None

    async def _scrape_postings(self, company: str, ticker: str) -> dict[str, Any]:
        """İlanları scrape et.

        Production'da: aiohttp + BeautifulSoup ile Kariyer.net'ten çekilecek.
        Şimdilik: Placeholder yapı — veri çekme mantığı eklenecek.
        """
        try:
            import aiohttp
            from bs4 import BeautifulSoup

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9",
            }

            # Kariyer.net şirket sayfası
            search_url = f"https://www.kariyer.net/isci/firma-ara?keyword={company}"

            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return {}

                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")

                    # İlanları parse et
                    postings = self._parse_postings(soup)

                    return {
                        "postings": postings,
                        "total_count": len(postings),
                        "company": company,
                        "ticker": ticker,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

        except ImportError:
            logger.warning("beautifulsoup4 not installed")
            return {}
        except Exception as e:
            logger.warning("Scraping error", error=str(e))
            return {}

    def _parse_postings(self, soup) -> list[dict]:
        """HTML'den ilan bilgilerini çıkar."""
        postings = []
        # Kariyer.net HTML yapısına göre parse
        job_cards = soup.select('.job-card, .listing-item, [data-testid="job-card"]')

        for card in job_cards[:50]:  # Max 50 ilan
            try:
                title = card.select_one(".job-title, .title, h3")
                location = card.select_one(".location, .city")
                department = card.select_one(".department, .category")

                postings.append(
                    {
                        "title": title.text.strip() if title else "",
                        "location": location.text.strip() if location else "",
                        "department": department.text.strip() if department else "",
                        "is_tech": self._is_tech_role(title.text if title else ""),
                        "is_management": self._is_management_role(title.text if title else ""),
                        "is_remote": "uzaktan" in (title.text if title else "").lower()
                        or "remote" in (title.text if title else "").lower(),
                    }
                )
            except Exception as e:
                logger.debug("Handled exception, continuing", error=str(e))
                continue

        return postings

    def _is_tech_role(self, title: str) -> bool:
        """Teknik pozisyon mu?"""
        tech_keywords = [
            "yazılım",
            "software",
            "developer",
            "mühendis",
            "engineer",
            "data",
            "veri",
            "analyst",
            "analist",
            "DevOps",
            "QA",
            "test",
            "backend",
            "frontend",
            "full stack",
            "mobile",
            "iOS",
            "Android",
            "python",
            "java",
            "react",
            "AI",
            "yapay zeka",
            "machine learning",
        ]
        title_lower = title.lower()
        return any(kw.lower() in title_lower for kw in tech_keywords)

    def _is_management_role(self, title: str) -> bool:
        """Yönetim pozisyonu mu?"""
        mgmt_keywords = [
            "müdür",
            "manager",
            "director",
            "başkan",
            "head",
            "lead",
            "CTO",
            "CEO",
            "CFO",
            "VP",
            "genel müdür",
            "koordinatör",
            "şef",
            "supervisor",
            "team lead",
        ]
        title_lower = title.lower()
        return any(kw.lower() in title_lower for kw in mgmt_keywords)

    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """İş ilanı feature'ları hesapla."""
        if not data or not data.get("postings"):
            return {}

        postings = data["postings"]
        total = len(postings)
        if total == 0:
            return {}

        tech_count = sum(1 for p in postings if p.get("is_tech"))
        mgmt_count = sum(1 for p in postings if p.get("is_management"))
        remote_count = sum(1 for p in postings if p.get("is_remote"))

        features = {
            "job_posting_count": float(total),
            "job_tech_ratio": tech_count / total,
            "job_management_ratio": mgmt_count / total,
            "job_remote_ratio": remote_count / total,
            "job_diversity": len(set(p.get("department", "") for p in postings)) / max(total, 1),
        }

        # Büyüme hesapla (geçmiş veri varsa)
        prev_count = data.get("previous_count", total)
        if prev_count > 0:
            features["job_posting_growth"] = (total - prev_count) / prev_count

        return features


# Singleton
kariyer_net_adapter = KariyerNetAdapter()
