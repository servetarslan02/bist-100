"""ALPHA BIST — Estimation Window Manager (MacKinlay, 1997).

Estimation window, event öncesi veriyi kullanarak expected return modelinin
parametrelerini (α, β) tahmin etmek için kullanılır. Look-ahead bias'ı önler.

Trading Day Düzeltmesi (v2.0):
═══════════════════════════════
MacKinlay (1997): Estimation window trading day cinsinden tanımlanmalıdır.

Calendar day kullanımının sorunları:
1. 120 calendar gün ≈ 85 trading gün → OLS tahmininde veri kaybı
2. Hafta sonu/tatil günleri return = 0 olarak eklenir → σ(AR) şişer
3. t-statistic'in paydası büyüyüş → false negative artar

Çözüm: Tüm uzunluklar trading day cinsinden, BIST takvimi ile dönüştürülür.
"""

from datetime import datetime

import numpy as np
import structlog

logger = structlog.get_logger()

# Event type → estimation window uzunluğu (TRADING DAY)
# Not: Eski calendar day değerleri trading day olarak yeniden yorumlandı
# 120 calendar gün ≈ 85 trading gün, ama burada doğrudan trading day veriyoruz
ESTIMATION_WINDOWS = {
    "FINANCIAL_RESULTS": 120,  # ~6 ay trading data
    "DIVIDEND": 60,  # ~3 ay
    "BUYBACK": 60,
    "CAPITAL_INCREASE": 90,  # ~4.5 ay
    "MERGER": 120,
    "MANAGEMENT_CHANGE": 60,
    "LEGAL": 90,
    "CONTRACT": 60,
    "GUIDANCE": 60,
    "TCMB_RATE": 90,
    "INFLATION": 60,
    "GDP": 90,
    "CPI": 60,
    "PPI": 60,
    "CURRENT_ACCOUNT": 60,
    "UNEMPLOYMENT": 60,
    "INDUSTRIAL_PRODUCTION": 60,
    "DEFAULT": 60,
}

# Event tarihinden kaç trading gün önce estimation window bitsin
# Look-ahead bias'ı önlemek için minimum 5 trading gün boşluk
GAP_TRADING_DAYS = 6


def _get_calendar():
    """Trading calendar'ı lazy import et."""
    from .trading_calendar import get_trading_calendar

    return get_trading_calendar()


class EstimationWindowManager:
    """Estimation window yönetimi — TRADING DAY bazlı, look-ahead bias önleme.

    v2.0: Artık tüm uzunluklar trading day cinsinden hesaplanır.
    BIST takvimi (hafta sonları + resmi tatiller) otomatik uygulanır.
    """

    def __init__(self, gap_trading_days: int = GAP_TRADING_DAYS, gap_days: int | None = None):
        self.gap_trading_days = gap_days if gap_days is not None else gap_trading_days

    def get_window(self, event_date: datetime, event_type: str = "DEFAULT") -> tuple[datetime, datetime]:
        """Event type'a göre estimation window döndür (TRADING DAY bazlı).

        Args:
            event_date: Event tarihi
            event_type: Event tipi (KAP/macro)

        Returns:
            (start_date, end_date) tuple — calendar tarihleri
        """
        cal = _get_calendar()
        trading_days = ESTIMATION_WINDOWS.get(event_type, ESTIMATION_WINDOWS["DEFAULT"])

        # Estimation window bitişi = event'ten gap_trading_days önce
        end_date = cal.trading_day_offset(event_date, -self.gap_trading_days)
        # Estimation window başlangıcı = bitişten trading_days gün önce
        start_date = cal.add_trading_days(end_date, -trading_days)

        logger.debug(
            "estimation_window_calculated",
            event_date=event_date.isoformat() if isinstance(event_date, datetime) else str(event_date),
            event_type=event_type,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            trading_days=trading_days,
            gap=self.gap_trading_days,
            method="trading_day",
        )
        return (
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.min.time()),
        )

    def get_window_trading_days(self, event_type: str = "DEFAULT") -> int:
        """Estimation window uzunluğunu trading gün olarak döndür."""
        return ESTIMATION_WINDOWS.get(event_type, ESTIMATION_WINDOWS["DEFAULT"])

    def validate_data(
        self,
        returns: np.ndarray,
        event_type: str = "DEFAULT",
        min_coverage: float = 0.7,
    ) -> bool:
        """Veri kalitesi kontrolü — yeterli trading günü var mı?

        Trading day kullanıldığı için artık 5/7 düzeltmesi gereksiz.
        Doğrudan beklenen trading gün sayısı ile karşılaştırılır.
        """
        expected_trading_days = self.get_window_trading_days(event_type)
        min_required = int(expected_trading_days * min_coverage)

        if len(returns) < min_required:
            logger.warning(
                "estimation_window_insufficient_data",
                event_type=event_type,
                expected=expected_trading_days,
                actual=len(returns),
                min_required=min_required,
                method="trading_day",
            )
            return False
        return True

    def extract_window_data(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: datetime,
        event_type: str = "DEFAULT",
    ) -> tuple[np.ndarray, np.ndarray]:
        """Estimation window verisini çıkar (TRADING DAY bazlı).

        Trading calendar kullanarak sadece iş günlerini seçer.
        Bu, OLS tahmininin kalitesini artırır çünkü:
        1. Boş günler (return=0) artık dahil edilmez
        2. σ(AR) daha doğru hesaplanır
        3. t-statistic daha güvenilir olur

        Args:
            returns: Tüm getiri serisi
            dates: Tarih dizisi
            event_date: Event tarihi
            event_type: Event tipi

        Returns:
            (window_returns, window_dates) tuple — sadece trading günleri
        """
        cal = _get_calendar()
        start, end = self.get_window(event_date, event_type)

        # Takvim bazlı filtreleme (geniş aralık)
        mask = (dates >= start) & (dates <= end)
        window_returns = returns[mask]
        window_dates = dates[mask]

        # Sadece trading günleri filtrele
        trading_mask = np.array([cal.is_trading_day(d.date() if isinstance(d, datetime) else d) for d in window_dates])
        window_returns = window_returns[trading_mask]
        window_dates = window_dates[trading_mask]

        if not self.validate_data(window_returns, event_type):
            logger.warning(
                "estimation_window_data_warning",
                event_type=event_type,
                data_points=len(window_returns),
                method="trading_day",
            )

        return window_returns, window_dates

    def get_estimation_window_size_calendar_days(self, event_date: datetime, event_type: str = "DEFAULT") -> int:
        """Estimation window'un takvim günleri cinsinden uzunluğunu döndür.

        Bilgi amaçlı — trading day → calendar day dönüşümü.
        """
        start, end = self.get_window(event_date, event_type)
        return (end - start).days + 1
