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
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Event type → estimation window uzunluğu (TRADING DAY)
# Not: Eski calendar day değerleri trading day olarak yeniden yorumlandı
# 120 calendar gün ≈ 85 trading gün, ama burada doğrudan trading day veriyoruz
ESTIMATION_WINDOWS: dict[str, int] = {
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
GAP_TRADING_DAYS: int = 6

# Varsayılan sabitler
DEFAULT_EVENT_TYPE: str = "DEFAULT"
MIN_COVERAGE_MIN: float = 0.0
MIN_COVERAGE_MAX: float = 1.0
DEFAULT_MIN_COVERAGE: float = 0.7
ARRAY_DIM: int = 1
MIN_ARRAY_LENGTH: int = 1

# Cache'lenmiş takvim referansı
_calendar_cache: Any = None


def _get_calendar() -> Any:
    """Trading calendar'ı lazy import et (cache'li).

    Returns:
        BISTTradingCalendar örneği
    """
    global _calendar_cache
    if _calendar_cache is None:
        from .trading_calendar import get_trading_calendar

        _calendar_cache = get_trading_calendar()
    return _calendar_cache


def _validate_datetime(value: datetime, name: str) -> None:
    """Datetime doğrulama.

    Args:
        value: Doğrulanacak değer
        name: Değer adı

    Raises:
        TypeError: datetime değilse
        ValueError: None ise
    """
    if value is None:
        logger.error("tahmin_penceresi_none_hatasi", deger_ad=name)
        raise ValueError(f"{name} None olamaz.")
    if not isinstance(value, datetime):
        logger.error("tahmin_penceresi_tip_hatasi", deger_ad=name, tip=type(value).__name__)
        raise TypeError(f"{name} datetime olmalı, gelen tip: {type(value).__name__}")


def _validate_array(arr: np.ndarray, name: str, min_len: int = MIN_ARRAY_LENGTH) -> None:
    """Array doğrulama.

    Args:
        arr: Doğrulanacak array
        name: Array adı
        min_len: Minimum uzunluk

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş, NaN/Inf içeriyorsa veya yanlış boyuttaysa
    """
    if not isinstance(arr, np.ndarray):
        logger.error("tahmin_penceresi_dizi_tip_hatasi", beklenti="np.ndarray", gercek=type(arr).__name__, dizi=name)
        raise TypeError(f"{name} numpy array olmalı, gelen tip: {type(arr).__name__}")

    if arr.ndim != ARRAY_DIM:
        logger.error("tahmin_penceresi_dizi_boyut_hatasi", beklenti=ARRAY_DIM, gercek=arr.ndim, dizi=name)
        raise ValueError(f"{name} tek boyutlu olmalı, gelen boyut: {arr.ndim}")

    if len(arr) < min_len:
        logger.error("tahmin_penceresi_dizi_bos", dizi=name, uzunluk=len(arr))
        raise ValueError(f"{name} boş olamaz (minimum {min_len} eleman gerekli).")

    # NaN/Inf kontrolü — sadece numerik array'lerde
    if np.issubdtype(arr.dtype, np.number):
        if np.any(np.isnan(arr)):
            logger.error("tahmin_penceresi_dizi_nan", dizi=name)
            raise ValueError(f"{name} dizisinde NaN değeri var.")
        if np.any(np.isinf(arr)):
            logger.error("tahmin_penceresi_dizi_inf", dizi=name)
            raise ValueError(f"{name} dizisinde Inf değeri var.")


class EstimationWindowManager:
    """Estimation window yönetimi — TRADING DAY bazlı, look-ahead bias önleme.

    v2.0: Artık tüm uzunluklar trading day cinsinden hesaplanır.
    BIST takvimi (hafta sonları + resmi tatiller) otomatik uygulanır.
    """

    def __init__(self, gap_trading_days: int = GAP_TRADING_DAYS, gap_days: int | None = None) -> None:
        """EstimationWindowManager başlatıcı.

        Args:
            gap_trading_days: Event'ten önceki boşluk (trading gün)
            gap_days: Eski API uyumluluğu için (None ise gap_trading_days kullanılır)

        Raises:
            ValueError: gap_trading_days negatif ise
        """
        resolved_gap = gap_days if gap_days is not None else gap_trading_days
        if resolved_gap < 0:
            logger.error("tahmin_penceresi_negatif_bosluk", gap=resolved_gap)
            raise ValueError(f"gap_trading_days negatif olamaz: {resolved_gap}")
        self.gap_trading_days: int = resolved_gap

    def get_window(self, event_date: datetime, event_type: str = DEFAULT_EVENT_TYPE) -> tuple[datetime, datetime]:
        """Event type'a göre estimation window döndür (TRADING DAY bazlı).

        Args:
            event_date: Event tarihi
            event_type: Event tipi (KAP/macro)

        Returns:
            (start_date, end_date) tuple — calendar tarihleri

        Raises:
            TypeError: event_date datetime değilse
            ValueError: event_date None ise
        """
        _validate_datetime(event_date, "event_date")

        cal = _get_calendar()
        trading_days = ESTIMATION_WINDOWS.get(event_type)
        if trading_days is None:
            logger.warning(
                "tahmin_penceresi_bilinmeyen_tip",
                event_type=event_type,
                varsayilan=DEFAULT_EVENT_TYPE,
            )
            trading_days = ESTIMATION_WINDOWS[DEFAULT_EVENT_TYPE]

        # Estimation window bitişi = event'ten gap_trading_days önce
        end_date = cal.trading_day_offset(event_date, -self.gap_trading_days)
        # Estimation window başlangıcı = bitişten trading_days gün önce
        start_date = cal.add_trading_days(end_date, -trading_days)

        logger.debug(
            "tahmin_penceresi_hesaplandi",
            event_tarihi=event_date.isoformat(),
            event_tipi=event_type,
            baslangic=start_date.isoformat(),
            bitis=end_date.isoformat(),
            trading_gunleri=trading_days,
            bosluk=self.gap_trading_days,
            yontem="trading_gun",
        )

        start_dt = start_date if isinstance(start_date, datetime) else datetime.combine(start_date, datetime.min.time())
        end_dt = end_date if isinstance(end_date, datetime) else datetime.combine(end_date, datetime.min.time())

        return (start_dt, end_dt)

    def get_window_trading_days(self, event_type: str = DEFAULT_EVENT_TYPE) -> int:
        """Estimation window uzunluğunu trading gün olarak döndür.

        Args:
            event_type: Event tipi

        Returns:
            Trading gün sayısı
        """
        return ESTIMATION_WINDOWS.get(event_type, ESTIMATION_WINDOWS[DEFAULT_EVENT_TYPE])

    def validate_data(
        self,
        returns: np.ndarray,
        event_type: str = DEFAULT_EVENT_TYPE,
        min_coverage: float = DEFAULT_MIN_COVERAGE,
    ) -> bool:
        """Veri kalitesi kontrolü — yeterli trading günü var mı?

        Args:
            returns: Getiri dizisi
            event_type: Event tipi
            min_coverage: Minimum kapama oranı (0.0-1.0 arası)

        Returns:
            True: yeterli veri var, False: yetersiz

        Raises:
            TypeError: returns numpy array değilse
            ValueError: min_coverage aralık dışı ise
        """
        if not isinstance(returns, np.ndarray):
            logger.error("tahmin_penceresi_validate_tip_hatasi", tip=type(returns).__name__)
            raise TypeError(f"returns numpy array olmalı, gelen tip: {type(returns).__name__}")

        if len(returns) < MIN_ARRAY_LENGTH:
            logger.error("tahmin_penceresi_validate_bos_dizi")
            raise ValueError("returns dizisi boş olamaz.")

        if not (MIN_COVERAGE_MIN <= min_coverage <= MIN_COVERAGE_MAX):
            logger.error(
                "tahmin_penceresi_validate_kapsama_hatasi",
                min_coverage=min_coverage,
                min=MIN_COVERAGE_MIN,
                max=MIN_COVERAGE_MAX,
            )
            raise ValueError(f"min_coverage {MIN_COVERAGE_MIN}-{MIN_COVERAGE_MAX} aralığında olmalı: {min_coverage}")

        expected_trading_days = self.get_window_trading_days(event_type)
        min_required = int(expected_trading_days * min_coverage)

        if len(returns) < min_required:
            logger.warning(
                "tahmin_penceresi_yetersiz_veri",
                event_tipi=event_type,
                beklenen=expected_trading_days,
                mevcut=len(returns),
                minimum_gerekli=min_required,
                yontem="trading_gun",
            )
            return False
        return True

    def extract_window_data(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: datetime,
        event_type: str = DEFAULT_EVENT_TYPE,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Estimation window verisini çıkar (TRADING DAY bazlı).

        Trading calendar kullanarak sadece iş günlerini seçer.
        Bu, OLS tahmininin kalitesini artırır çünkü:
        1. Boş günler (return=0) artık dahil edilmez
        2. σ(AR) daha doğru hesaplanır
        3. t-statistic daha güvenilir olur

        Args:
            returns: Tüm getiri serisi (numpy array)
            dates: Tarih dizisi (numpy array, datetime dtype)
            event_date: Event tarihi
            event_type: Event tipi

        Returns:
            (window_returns, window_dates) tuple — sadece trading günleri

        Raises:
            TypeError: returns/dates numpy array değilse veya event_date datetime değilse
            ValueError: Boş array, uzunluk uyuşmazlığı, NaN/Inf varsa
        """
        _validate_array(returns, "returns")
        _validate_array(dates, "dates")
        _validate_datetime(event_date, "event_date")

        if len(returns) != len(dates):
            logger.error(
                "tahmin_penceresi_cikarim_uzunluk_uyusmazligi",
                returns_uzunluk=len(returns),
                dates_uzunluk=len(dates),
            )
            raise ValueError(
                f"returns ve dates uzunlukları eşit olmalı: "
                f"returns={len(returns)}, dates={len(dates)}"
            )

        cal = _get_calendar()
        start, end = self.get_window(event_date, event_type)

        # Takvim bazlı filtreleme (geniş aralık)
        mask = (dates >= start) & (dates <= end)
        if not np.any(mask):
            logger.warning(
                "tahmin_penceresi_veri_bulunamadi",
                baslangic=start.isoformat(),
                bitis=end.isoformat(),
            )
            return np.array([], dtype=np.float64), np.array([], dtype="datetime64[ns]")

        window_returns = returns[mask]
        window_dates = dates[mask]

        # Sadece trading günleri filtrele
        trading_mask = np.array([cal.is_trading_day(d.date() if isinstance(d, datetime) else d) for d in window_dates])
        if not np.any(trading_mask):
            logger.warning("tahmin_penceresi_trading_gun_yok")
            return np.array([], dtype=np.float64), np.array([], dtype="datetime64[ns]")

        window_returns = window_returns[trading_mask]
        window_dates = window_dates[trading_mask]

        if not self.validate_data(window_returns, event_type):
            logger.warning(
                "tahmin_penceresi_veri_uyarisi",
                event_tipi=event_type,
                veri_noktasi=len(window_returns),
                yontem="trading_gun",
            )

        return window_returns, window_dates

    def get_estimation_window_size_calendar_days(
        self, event_date: datetime, event_type: str = DEFAULT_EVENT_TYPE
    ) -> int:
        """Estimation window'un takvim günleri cinsinden uzunluğunu döndür.

        Bilgi amaçlı — trading day → calendar day dönüşümü.

        Args:
            event_date: Event tarihi
            event_type: Event tipi

        Returns:
            Takvim gün sayısı

        Raises:
            TypeError: event_date datetime değilse
        """
        _validate_datetime(event_date, "event_date")
        start, end = self.get_window(event_date, event_type)
        return (end - start).days + 1
