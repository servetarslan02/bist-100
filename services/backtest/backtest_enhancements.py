"""ALPHA BIST — Backtest Geliştirmeleri v1.0

Backtest motoru geliştirmeleri:
- Delisted hisse çıkışı yönetimi
- IPO (halka arz) yönetimi
- T+1 execution (gerçek takas)
- Market impact modeli
- Likidite kısıtlamaları
- Şirket olayları (temettü, bölünme)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# =====================================================================
# SABİTLER (MAGIC NUMBER TEMİZLİĞİ)
# =====================================================================
DEFAULT_MAX_PARTICIPATION_RATE: float = 0.10  # ADV'nin %10'u
DEFAULT_MARKET_IMPACT_COEFF: float = 0.1      # Square-root impact katsayısı
DEFAULT_MIN_ADV_THRESHOLD: float = 1_000_000.0  # 1M TL minimum hacim
DEFAULT_MIN_POST_IPO_DAYS: int = 30           # Halka arz sonrası min gün


@dataclass
class MarketImpact:
    """Market impact sonucu."""

    ticker: str
    trade_size: float
    adv: float  # Average Daily Volume
    participation_rate: float
    temporary_impact_pct: float
    permanent_impact_pct: float
    total_impact_pct: float
    is_feasible: bool

    def __repr__(self) -> str:
        """Market impact sonucunu okunabilir formatta döndürür."""
        return (
            f"MarketImpact(ticker={self.ticker}, impact={self.total_impact_pct:.2f}%, "
            f"participation={self.participation_rate:.2%}, feasible={self.is_feasible})"
        )


@dataclass
class ExecutionResult:
    """T+1 execution sonucu."""

    ticker: str
    signal_date: str
    execution_date: str
    delay_days: int
    price_change_pct: float
    can_execute: bool
    reason: str

    def __repr__(self) -> str:
        """T+1 execution sonucunu okunabilir formatta döndürür."""
        return (
            f"ExecutionResult(ticker={self.ticker}, {self.signal_date}→{self.execution_date}, "
            f"execute={self.can_execute}, reason={self.reason})"
        )


@dataclass
class CorporateAction:
    """Şirket olayı (temettü, bölünme, hak kullanımı, delist)."""

    ticker: str
    action_type: str  # dividend, split, rights, delisting
    ex_date: str
    value: float
    description: str

    def __repr__(self) -> str:
        """Şirket olayını okunabilir formatta döndürür."""
        return f"CorporateAction(ticker={self.ticker}, type={self.action_type}, ex_date={self.ex_date})"


class BacktestEnhancements:
    """Backtest motoru geliştirmeleri.

    Özellikler:
    - T+1 execution (BIST takas kuralı)
    - Market impact modeli (participation rate)
    - Delisted stock handling
    - IPO handling
    - Liquidity constraints
    - Corporate actions
    """

    def __init__(
        self,
        max_participation_rate: float = DEFAULT_MAX_PARTICIPATION_RATE,
        market_impact_coefficient: float = DEFAULT_MARKET_IMPACT_COEFF,
        min_adv_threshold: float = DEFAULT_MIN_ADV_THRESHOLD,
    ):
        """Backtest geliştirmelerini başlatır."""
        self.max_participation_rate = max_participation_rate
        self.market_impact_coefficient = market_impact_coefficient
        self.min_adv_threshold = min_adv_threshold
        self._delisted_stocks: dict[str, str] = {}  # ticker → delist_date
        self._ipo_dates: dict[str, str] = {}  # ticker → ipo_date
        self._corporate_actions: list[CorporateAction] = []
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        """BacktestEnhancements nesnesini okunabilir formatta döndürür."""
        return (
            f"BacktestEnhancements(max_participation={self.max_participation_rate:.1%}, "
            f"min_adv={self.min_adv_threshold:,.0f} TL, delisted={len(self._delisted_stocks)}, "
            f"ipos={len(self._ipo_dates)}, actions={len(self._corporate_actions)})"
        )

    # T+1 TAKAS

    def check_t_plus_1(
        self,
        ticker: str,
        signal_date: str,
        last_trade_date: str | None = None,
    ) -> ExecutionResult:
        """T+1 execution kontrolü.

        BIST'te alım/satım emirleri T+1 gününde gerçekleşir.
        Sinyal bugün oluştuysa, işlem yarın yapılabilir.

        Args:
            ticker: Hisse kodu
            signal_date: Sinyal tarihi (YYYY-MM-DD)
            last_trade_date: Son işlem tarihi (opsiyonel)

        Returns:
            ExecutionResult
        """
        try:
            signal_dt = datetime.strptime(signal_date, "%Y-%m-%d")
        except ValueError:
            return ExecutionResult(
                ticker=ticker,
                signal_date=signal_date,
                execution_date=signal_date,
                delay_days=0,
                price_change_pct=0.0,
                can_execute=False,
                reason="Geçersiz tarih formatı",
            )

        # T+1: Bir sonraki iş günü
        execution_dt = signal_dt + timedelta(days=1)

        # Hafta sonu kontrolü
        while execution_dt.weekday() >= 5:  # Cumartesi=5, Pazar=6
            execution_dt += timedelta(days=1)

        delay_days = (execution_dt - signal_dt).days

        # Delisted kontrolü
        if self.is_delisted(ticker, execution_dt.strftime("%Y-%m-%d")):
            return ExecutionResult(
                ticker=ticker,
                signal_date=signal_date,
                execution_date=execution_dt.strftime("%Y-%m-%d"),
                delay_days=delay_days,
                price_change_pct=0.0,
                can_execute=False,
                reason=f"{ticker} bu tarihte delisted",
            )

        return ExecutionResult(
            ticker=ticker,
            signal_date=signal_date,
            execution_date=execution_dt.strftime("%Y-%m-%d"),
            delay_days=delay_days,
            price_change_pct=0.0,
            can_execute=True,
            reason=f"T+1 execution: {delay_days} gün gecikme",
        )

    # PİYASA ETKİSİ

    def estimate_market_impact(
        self,
        ticker: str,
        trade_size: float,
        adv: float,
    ) -> MarketImpact:
        """Market impact tahmini.

        Participation rate modeli:
        - Temporary impact = coefficient * sqrt(participation_rate)
        - Permanent impact = coefficient * participation_rate / 2

        Args:
            ticker: Hisse kodu
            trade_size: İşlem büyüklüğü (TL)
            adv: Average Daily Volume (TL)

        Returns:
            MarketImpact
        """
        if adv <= 0:
            return MarketImpact(
                ticker=ticker,
                trade_size=trade_size,
                adv=adv,
                participation_rate=0.0,
                temporary_impact_pct=0.0,
                permanent_impact_pct=0.0,
                total_impact_pct=0.0,
                is_feasible=False,
            )

        participation_rate = trade_size / adv

        # Limit kontrolü
        is_feasible = participation_rate <= self.max_participation_rate

        # Temporary impact (geçici — işlem sonrası düzelir)
        temporary_impact = self.market_impact_coefficient * np.sqrt(participation_rate) * 100

        # Permanent impact (kalıcı — fiyat kalıcı olarak etkilenir)
        permanent_impact = (self.market_impact_coefficient * participation_rate / 2) * 100

        total_impact = temporary_impact + permanent_impact

        if not is_feasible:
            logger.warning("market_impact_asimi: ticker=%s, katilim_orani=%s, max=%s", ticker, round(participation_rate, 4), self.max_participation_rate)

        return MarketImpact(
            ticker=ticker,
            trade_size=trade_size,
            adv=adv,
            participation_rate=round(participation_rate, 4),
            temporary_impact_pct=round(temporary_impact, 4),
            permanent_impact_pct=round(permanent_impact, 4),
            total_impact_pct=round(total_impact, 4),
            is_feasible=is_feasible,
        )

    # DELİSTED HİSSE

    def register_delisted(self, ticker: str, delist_date: str) -> None:
        """Delisted hisse kaydet.

        Args:
            ticker: Hisse kodu
            delist_date: Delist tarihi (YYYY-MM-DD)
        """
        with self._lock:
            self._delisted_stocks[ticker] = delist_date
        logger.info("delisted_kaydedildi: ticker=%s, tarih=%s", ticker, delist_date)

    def is_delisted(self, ticker: str, date: str) -> bool:
        """Hisse bu tarihte delisted mi?

        Args:
            ticker: Hisse kodu
            date: Kontrol tarihi (YYYY-MM-DD)

        Returns:
            Delisted mi?
        """
        with self._lock:
            delist_date = self._delisted_stocks.get(ticker)
        if delist_date is None:
            return False

        try:
            check_dt = datetime.strptime(date, "%Y-%m-%d")
            delist_dt = datetime.strptime(delist_date, "%Y-%m-%d")
            return check_dt >= delist_dt
        except ValueError:
            return False

    # IPO YÖNETİMİ

    def register_ipo(self, ticker: str, ipo_date: str) -> None:
        """IPO tarihi kaydet.

        Args:
            ticker: Hisse kodu
            ipo_date: IPO tarihi (YYYY-MM-DD)
        """
        with self._lock:
            self._ipo_dates[ticker] = ipo_date
        logger.info("ipo_kaydedildi: ticker=%s, tarih=%s", ticker, ipo_date)

    def is_post_ipo(
        self,
        ticker: str,
        date: str,
        min_days: int = DEFAULT_MIN_POST_IPO_DAYS,
    ) -> bool:
        """IPO'dan sonra yeterli gün geçti mi?

        Args:
            ticker: Hisse kodu
            date: Kontrol tarihi
            min_days: Minimum gün sayısı

        Returns:
            Yeterli gün geçti mi?
        """
        with self._lock:
            ipo_date = self._ipo_dates.get(ticker)
        if ipo_date is None:
            return True  # IPO kaydı yoksa işlem yapılabilir

        try:
            check_dt = datetime.strptime(date, "%Y-%m-%d")
            ipo_dt = datetime.strptime(ipo_date, "%Y-%m-%d")
            days_since = (check_dt - ipo_dt).days
            return days_since >= min_days
        except ValueError:
            return True

    # ŞİRKET OLAYLARI

    def register_corporate_action(self, action: CorporateAction) -> None:
        """Şirket olayı kaydet."""
        with self._lock:
            self._corporate_actions.append(action)
        logger.info("sirket_olayi_kaydedildi: ticker=%s, tip=%s, tarih=%s", action.ticker, action.action_type, action.ex_date)

    def get_corporate_actions(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[CorporateAction]:
        """Belirli tarih aralığındaki şirket olaylarını döndür.

        Args:
            ticker: Hisse kodu
            start_date: Başlangıç tarihi
            end_date: Bitiş tarihi

        Returns:
            CorporateAction listesi
        """
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            return []

        with self._lock:
            actions_snapshot = list(self._corporate_actions)

        result: list[CorporateAction] = []
        for action in actions_snapshot:
            if action.ticker != ticker:
                continue

            try:
                action_dt = datetime.strptime(action.ex_date, "%Y-%m-%d")
                if start_dt <= action_dt <= end_dt:
                    result.append(action)
            except ValueError:
                continue

        return result

    def adjust_for_dividend(
        self,
        price: float,
        dividend: float,
    ) -> float:
        """Temettü düzeltmesi.

        Ex-date'te fiyat temettü kadar düşer.

        Args:
            price: Fiyat
            dividend: Temettü miktarı

        Returns:
            Düzeltilmiş fiyat
        """
        if np.isnan(price) or price <= 0.0:
            return 0.0
        if np.isnan(dividend) or dividend <= 0.0:
            return price
        return max(0.0, price - dividend)

    def adjust_for_split(
        self,
        price: float,
        ratio: float,
    ) -> float:
        """Bölünme düzeltmesi.

        Args:
            price: Fiyat
            ratio: Bölünme oranı (2 = 1'e 2 bölünme)

        Returns:
            Düzeltilmiş fiyat
        """
        if np.isnan(price) or price <= 0.0:
            return 0.0
        if np.isnan(ratio) or ratio <= 0.0:
            return price
        return price / ratio

    # LİKİDİTE KONTROLÜ

    def check_liquidity(
        self,
        ticker: str,
        adv: float,
        trade_size: float,
    ) -> tuple[bool, str]:
        """Likidite kontrolü.

        Args:
            ticker: Hisse kodu
            adv: Average Daily Volume (TL)
            trade_size: İşlem büyüklüğü (TL)

        Returns:
            (is_liquid, reason)
        """
        if np.isnan(adv) or adv < self.min_adv_threshold:
            return False, f"ADV ({adv:,.0f}) minimum eşiğin ({self.min_adv_threshold:,.0f}) altında"

        participation = trade_size / adv if adv > 0 else 1.0
        if participation > self.max_participation_rate:
            return False, (
                f"Katılım oranı ({participation:.1%}) maksimumun ({self.max_participation_rate:.1%}) üzerinde"
            )

        return True, "Likidite yeterli"

    # ÖZET

    def get_summary(self) -> dict[str, Any]:
        """Geliştirme özetini döndürür."""
        with self._lock:
            return {
                "delisted_stocks": len(self._delisted_stocks),
                "ipo_dates": len(self._ipo_dates),
                "corporate_actions": len(self._corporate_actions),
                "max_participation_rate": self.max_participation_rate,
                "min_adv_threshold": self.min_adv_threshold,
            }


# Singleton
backtest_enhancements = BacktestEnhancements()

__all__ = [
    "CorporateAction",
    "ExecutionResult",
    "MarketImpact",
    "BacktestEnhancements",
    "backtest_enhancements",
    "DEFAULT_MAX_PARTICIPATION_RATE",
    "DEFAULT_MARKET_IMPACT_COEFF",
    "DEFAULT_MIN_ADV_THRESHOLD",
    "DEFAULT_MIN_POST_IPO_DAYS",
]
