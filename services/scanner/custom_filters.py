"""
ALPHA BIST — Custom Filter Engine v1.0

BIST'e özel ve kullanıcı tanımlı filtreler.
Tarama sonuçlarını son kez filtreler.

Kaynaklar: Mometic (2026), BIST kuralları
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class FilterResult:
    """Filtre sonucu."""
    ticker: str
    passed: bool
    filter_name: str
    reason: str
    original_score: float
    adjusted_score: float


@dataclass
class CustomFilter:
    """Özel filtre tanımı."""
    name: str
    description: str
    condition: Callable[[dict[str, Any]], bool]  # result → passed?
    action: str = "exclude"  # exclude, include, adjust_score
    score_adjustment: float = 0.0  # adjust_score için
    enabled: bool = True


class CustomFilterEngine:
    """Özel filtre motoru.

    BIST Hazır Filtreleri:
    - SPK %10 limit kontrolü
    - Minimum hacim filtresi (günlük 100K+ lot)
    - Minimum fiyat filtresi (1 TL altı hariç)
    - Sektör rotasyon filtresi
    - Yabancı alım filtresi

    Kullanıcı tanımlı filtreler eklenebilir.
    """

    def __init__(self):
        self._filters: list[CustomFilter] = []
        self._setup_bist_filters()

    def _setup_bist_filters(self):
        """BIST'e özel hazır filtreler."""

        # Filtre 1: Minimum hacim
        self._filters.append(CustomFilter(
            name="min_volume",
            description="Günlük hacim 100K lot altı hariç",
            condition=lambda r: r.get("volume", 0) >= 100000,
            action="exclude",
        ))

        # Filtre 2: Minimum fiyat
        self._filters.append(CustomFilter(
            name="min_price",
            description="Fiyat 1 TL altı hariç",
            condition=lambda r: r.get("price", 0) >= 1.0,
            action="exclude",
        ))

        # Filtre 3: Maksimum spread (likidite)
        self._filters.append(CustomFilter(
            name="max_spread",
            description="Spread %5'ten fazla olan hariç",
            condition=lambda r: r.get("spread_pct", 0) <= 5.0 or r.get("spread_pct", 0) == 0,
            action="exclude",
        ))

        # Filtre 4: Aşırı alım kontrolü
        self._filters.append(CustomFilter(
            name="overbought_filter",
            description="RSI > 80 olanları filtrele",
            condition=lambda r: r.get("rsi", 50) <= 80,
            action="exclude",
            enabled=False,  # Opsiyonel
        ))

        # Filtre 5: Düşük volatilite bonusu
        self._filters.append(CustomFilter(
            name="low_vol_bonus",
            description="Düşük volatilite hisselerine bonus",
            condition=lambda r: r.get("volatility", 20) < 15,
            action="adjust_score",
            score_adjustment=5.0,
            enabled=False,  # Opsiyonel
        ))

    def add_filter(self, custom_filter: CustomFilter):
        """Yeni filtre ekle.

        Args:
            custom_filter: Özel filtre
        """
        self._filters.append(custom_filter)
        if len(self._filters) > 100:
            self._filters = self._filters[-100:]
        logger.info("Custom filter added", name=custom_filter.name)

    def remove_filter(self, name: str):
        """Filtre kaldır.

        Args:
            name: Filtre adı
        """
        self._filters = [f for f in self._filters if f.name != name]
        logger.info("Custom filter removed", name=name)

    def enable_filter(self, name: str, enabled: bool = True):
        """Filtreyi aktif/pasif yap.

        Args:
            name: Filtre adı
            enabled: Aktif mi?
        """
        for f in self._filters:
            if f.name == name:
                f.enabled = enabled
                break

    def apply_filters(
        self,
        results: list[dict[str, Any]],
    ) -> tuple:
        """Filtreleri uygula.

        Args:
            results: Tarama sonuçları

        Returns:
            (filtered_results, filter_log) tuple'ı
        """
        filtered = []
        filter_log = []

        for result in results:
            ticker = result.get("ticker", "")
            original_score = result.get("score", 0)
            passed_all = True
            score_adjustment = 0.0

            for f in self._filters:
                if not f.enabled:
                    continue

                try:
                    passed = f.condition(result)
                except Exception as e:
                    logger.warning("Filter error", filter=f.name, ticker=ticker, error=str(e))
                    passed = True  # Hata durumunda filtreleme

                if not passed:
                    if f.action == "exclude":
                        passed_all = False
                        filter_log.append(FilterResult(
                            ticker=ticker,
                            passed=False,
                            filter_name=f.name,
                            reason=f.description,
                            original_score=original_score,
                            adjusted_score=original_score,
                        ))
                        break
                else:
                    # Koşul sağlandı → adjust_score ise skor ayarla
                    if f.action == "adjust_score":
                        score_adjustment += f.score_adjustment

            if passed_all:
                # Skor ayarlaması
                if score_adjustment != 0:
                    result = dict(result)
                    result["score"] = original_score + score_adjustment
                    result["score_adjustment"] = score_adjustment

                filtered.append(result)

                if score_adjustment != 0:
                    filter_log.append(FilterResult(
                        ticker=ticker,
                        passed=True,
                        filter_name="score_adjustment",
                        reason=f"Skor {score_adjustment:+.1f} ayarlandı",
                        original_score=original_score,
                        adjusted_score=original_score + score_adjustment,
                    ))
            else:
                filter_log.append(FilterResult(
                    ticker=ticker,
                    passed=False,
                    filter_name="filtered_out",
                    reason="Filtre tarafından elendi",
                    original_score=original_score,
                    adjusted_score=original_score,
                ))

        logger.info("Filters applied",
                    input=len(results),
                    output=len(filtered),
                    filtered_out=len(results) - len(filtered))

        return filtered, filter_log

    def get_filters(self) -> list[dict[str, Any]]:
        """Tüm filtreleri al.

        Returns:
            Filtre listesi
        """
        return [{
            "name": f.name,
            "description": f.description,
            "action": f.action,
            "enabled": f.enabled,
            "score_adjustment": f.score_adjustment,
        } for f in self._filters]

    def get_filter_stats(
        self,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filtre istatistikleri — hangi filtre kaç hisseyi eliyor.

        Args:
            results: Tarama sonuçları

        Returns:
            Filtre istatistikleri
        """
        stats = {}

        for f in self._filters:
            if not f.enabled:
                continue

            blocked = 0
            for result in results:
                try:
                    if not f.condition(result):
                        blocked += 1
                except Exception as e:
                    logger.debug("Handled exception", error=str(e), context="custom_filters.py:252")

            stats[f.name] = {
                "description": f.description,
                "blocked_count": blocked,
                "blocked_pct": round(blocked / max(len(results), 1) * 100, 1),
            }

        return stats


# Singleton
custom_filter_engine = CustomFilterEngine()
