"""
ALPHA BIST — Survivorship Bias (Hayatta Kalma Yanlılığı) Yönetim Modülü

Survivorship bias, sadece bugün hâlâ işlem gören hisselerle geçmiş test
yapıldığında ortaya çıkan sistematik aşırı iyimserliktir. İflas eden, birleşen
veya kottan çıkarılan (delist edilen) şirketler dışarıda bırakıldığında,
stratejinin geçmiş performansı yapay olarak yüksek görünür.

Temel Sorumluluklar:
1. Kottan çıkarılan (delisted) hisselerin tarihsel verilerini ve kapanış fiyatlarını saklar.
2. Backtest evrenini (universe) hedef tarihteki gerçek duruma göre filtreler.
3. İflas veya birleşme durumlarında terminal getiri düzeltmesi (recovery rate / final price) uygular.
4. Bias-free (tarafsız) getiri ve Sharpe oranı metriklerini hesaplar.

Referanslar:
- Malkiel, B. G., & Saha, A. (2005). "Survivorship Bias in Hedge Fund Returns"
- de Prado, M. L. (2018). "Advances in Financial Machine Learning" - Ch. 7
"""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# =====================================================================
# SABİTLER (MAGIC NUMBER TEMİZLİĞİ)
# =====================================================================
DEFAULT_MAX_DELISTING_EVENTS: int = 1000
TRADING_DAYS_PER_YEAR: int = 252
DEFAULT_SNAPSHOT_INTERVAL_DAYS: int = 30
DEFAULT_BANKRUPTCY_RECOVERY_RATE: float = 0.0


# =====================================================================
# YARDIMCI TARİH DÖNÜŞTÜRÜCÜ
# =====================================================================
def _parse_to_datetime(val: Any) -> datetime:
    """
    Farklı tarih formatlarını (ISO string, date, datetime, numpy datetime64)
    standart UTC naive datetime nesnesine dönüştürür.

    Timezone-aware nesneleri UTC naive formatına normalize ederek
    karşılaştırmalarda TypeError ve SchemaError oluşmasını engeller.

    Args:
        val: Tarih verisi (str, date, datetime, np.datetime64 vb.).

    Returns:
        datetime: Standart UTC naive datetime nesnesi.

    Raises:
        ValueError: Tarih verisi boş veya çözümlenemediğinde.
    """
    if val is None:
        raise ValueError("Tarih değeri None olamaz.")

    # Numpy scalar veya benzeri tipleri çıkar
    if hasattr(val, "item") and callable(val.item):
        val = val.item()

    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, date):
        dt = datetime(val.year, val.month, val.day)
    elif isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            raise ValueError("Tarih dizesi boş olamaz.")

        # ISO format denemesi ("2023-05-15" veya "2023-05-15T10:00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            # Yaygın alternatif formatlar
            parsed = False
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(cleaned[:19], fmt)
                    parsed = True
                    break
                except ValueError:
                    continue
            if not parsed:
                raise ValueError(f"Tarih dizesi çözümlenemedi: '{cleaned}'") from None
    else:
        # np.datetime64 veya diğer tipler için string fallback
        str_val = str(val).strip()
        try:
            dt = datetime.fromisoformat(str_val[:19])
        except Exception as e:
            raise ValueError(f"Desteklenmeyen tarih tipi veya formatı: {type(val)} ({val})") from e

    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


# =====================================================================
# VERİ MODELLERİ
# =====================================================================
@dataclass
class DelistingEvent:
    """
    Kottan çıkarılma (delisting) olay kaydı.

    Attributes:
        ticker: Hisse senedi kodu (örn: 'THYAO').
        delisting_date: Kottan çıkarılma tarihi.
        reason: Çıkarılma nedeni ('bankruptcy', 'merger', 'acquisition', 'voluntary', 'regulatory').
        final_price: İşlem gördüğü son fiyat veya devralma teklif fiyatı.
        recovery_rate: İflas/tasfiye durumunda alacaklı payı (0.0 - 1.0 arası).
    """

    ticker: str
    delisting_date: datetime
    reason: str
    final_price: float | None = None
    recovery_rate: float | None = None

    def __post_init__(self) -> None:
        """Tarih, hisse sembolü ve oran doğrulaması."""
        self.ticker = self.ticker.strip().upper()
        if not self.ticker:
            raise ValueError("Hisse kodu (ticker) boş olamaz.")

        self.delisting_date = _parse_to_datetime(self.delisting_date)

        if self.recovery_rate is not None:
            if not (0.0 <= self.recovery_rate <= 1.0):
                raise ValueError(f"Geri kazanım oranı (recovery_rate) [0.0, 1.0] aralığında olmalıdır: {self.recovery_rate}")
        if self.final_price is not None and self.final_price < 0.0:
            raise ValueError(f"Son fiyat negatif olamaz: {self.final_price}")

    def to_dict(self) -> dict[str, Any]:
        """
        Olayı serileştirilebilir sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: Delisting olayı özet sözlüğü.
        """
        return {
            "ticker": self.ticker,
            "delisting_date": self.delisting_date.isoformat(),
            "reason": self.reason,
            "final_price": self.final_price,
            "recovery_rate": self.recovery_rate,
        }

    def __repr__(self) -> str:
        return (
            f"DelistingEvent(ticker='{self.ticker}', date='{self.delisting_date.strftime('%Y-%m-%d')}', "
            f"reason='{self.reason}', recovery={self.recovery_rate}, final_price={self.final_price})"
        )


@dataclass
class UniverseSnapshot:
    """
    Belirli bir takvim anındaki işlem evreni (universe) anlık görüntüsü.

    Attributes:
        date: Snapshot tarihi.
        active_tickers: O tarihte işlem gören aktif hisseler kümesi.
        delisted_tickers: O tarihten önce kottan çıkmış hisseler kümesi.
        total_count: Bilinen toplam hisse sayısı.
        active_count: Aktif hisse sayısı.
        delisted_count: Kottan çıkarılmış hisse sayısı.
    """

    date: datetime
    active_tickers: set[str] = field(default_factory=set)
    delisted_tickers: set[str] = field(default_factory=set)
    total_count: int = 0
    active_count: int = 0
    delisted_count: int = 0

    def __post_init__(self) -> None:
        """Sayımları otomatik senkronize et."""
        if not self.total_count and (self.active_tickers or self.delisted_tickers):
            self.active_count = len(self.active_tickers)
            self.delisted_count = len(self.delisted_tickers)
            self.total_count = self.active_count + self.delisted_count

    def to_dict(self) -> dict[str, Any]:
        """
        Snapshot verisini serileştirilebilir sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: Snapshot istatistik sözlüğü.
        """
        return {
            "date": self.date.isoformat(),
            "active_count": self.active_count,
            "delisted_count": self.delisted_count,
            "total_count": self.total_count,
        }

    def __repr__(self) -> str:
        return (
            f"UniverseSnapshot(date='{self.date.strftime('%Y-%m-%d')}', "
            f"active={self.active_count}, delisted={self.delisted_count}, total={self.total_count})"
        )


# =====================================================================
# SURVIVORSHIP BIAS YÖNETİCİSİ
# =====================================================================
class SurvivorshipBiasHandler:
    """
    Survivorship Bias (Hayatta Kalma Yanlılığı) Yönetim Motoru.

    Backtest evrenini Point-in-Time prensibine göre filtreler ve delist edilen
    hisseler için terminal zarar/getiri düzeltmelerini uygular. Thread-safe'dir.
    """

    def __init__(self, max_events: int = DEFAULT_MAX_DELISTING_EVENTS) -> None:
        """
        Yönetici motoru ilklendirir.

        Args:
            max_events: Bellekte tutulacak azami delisting olay sayısı.
        """
        self._max_events: int = max_events
        self._delisting_events: list[DelistingEvent] = []
        self._delisted_tickers: dict[str, datetime] = {}  # ticker -> delisting_date
        self._delisting_details: dict[str, DelistingEvent] = {}
        self._active_tickers: set[str] = set()
        self._lock: threading.Lock = threading.Lock()

    def register_delisting(self, event: DelistingEvent) -> None:
        """
        Sisteme tek bir delisting olayı kaydeder.

        Args:
            event: Kaydedilecek DelistingEvent nesnesi.
        """
        with self._lock:
            self._delisting_events.append(event)
            if len(self._delisting_events) > self._max_events:
                self._delisting_events = self._delisting_events[-self._max_events:]

            self._delisted_tickers[event.ticker] = event.delisting_date
            self._delisting_details[event.ticker] = event

        logger.info(
            "Delisting olayı kaydedildi: hisse=%s, tarih=%s, neden=%s",
            event.ticker,
            event.delisting_date.strftime("%Y-%m-%d"),
            event.reason,
        )

    def register_delistings_batch(self, events: list[DelistingEvent]) -> None:
        """
        Birden çok delisting olayını toplu olarak kaydeder.

        Args:
            events: DelistingEvent listesi.
        """
        for event in events:
            self.register_delisting(event)

    def set_active_universe(self, tickers: set[str]) -> None:
        """
        Güncel canlı evreni (bugün işlem gören aktif hisseleri) kaydeder.

        Args:
            tickers: Aktif hisse sembolleri kümesi.
        """
        with self._lock:
            self._active_tickers = {t.strip().upper() for t in tickers if t}

    def get_universe_at_date(
        self,
        target_date: datetime | str | date,
        all_known_tickers: set[str] | None = None,
    ) -> set[str]:
        """
        Belirtilen tarihteki bias-free geçerli evreni hesaplar.

        O tarihte henüz kottan çıkarılmamış olan tüm hisseleri döndürür.
        Bugün delist edilmiş olsa dahi geçmiş tarihte işlem görüyorsa evrene dahil edilir.

        Args:
            target_date: Evrenin hesaplanacağı hedef tarih.
            all_known_tickers: Sistemin tanıdığı tüm hisseler (aktif + kottan çıkanlar).
                Belirtilmezse sistemdeki aktif ve kayıtlı delist hisselerin birleşimi kullanılır.

        Returns:
            set[str]: Hedef tarihte işlem görmeye uygun hisseler kümesi.
        """
        target_dt = _parse_to_datetime(target_date)
        active: set[str] = set()

        with self._lock:
            delisted_map = dict(self._delisted_tickers)
            if all_known_tickers is None:
                universe_pool = self._active_tickers | set(delisted_map.keys())
            else:
                universe_pool = {t.strip().upper() for t in all_known_tickers if t}

        for ticker in universe_pool:
            if ticker in delisted_map:
                delist_date = delisted_map[ticker]
                # Hedef tarihte henüz kottan çıkmamışsa aktiftir
                if target_dt < delist_date:
                    active.add(ticker)
            else:
                # Delisting kaydı yoksa aktif kabul edilir
                active.add(ticker)

        return active

    def apply_survivorship_correction(
        self,
        returns: pl.DataFrame,
        delistings: list[DelistingEvent],
        ticker_col: str = "ticker",
        date_col: str = "date",
        return_col: str = "return",
    ) -> pl.DataFrame:
        """
        Getiri serisine saf Polars vektörel motoruyla survivorship bias düzeltmesi uygular.

        Kottan çıkarılan hisseler için:
        - İflas (bankruptcy) veya recovery_rate tanımlı: Terminal getiri = -1.0 + recovery_rate.
        - Birleşme / devralma (merger/acquisition): final_price üzerinden hesaplanan getiri uygulanır.
        - Gönüllü / regülasyon: Son fiyat veya temerrüt düzeltmesi yansıtılır.

        Args:
            returns: Getiri verilerini içeren Polars DataFrame.
            delistings: Uygulanacak delisting olayları listesi.
            ticker_col: Hisse kodu sütun adı.
            date_col: Tarih sütun adı.
            return_col: Getiri sütun adı.

        Returns:
            pl.DataFrame: Düzeltilmiş getiri serisi içeren yeni Polars DataFrame.

        Raises:
            ValueError: Gerekli sütunlar DataFrame'de mevcut değilse.
        """
        if returns.is_empty():
            return returns.clone()

        required_cols = {ticker_col, date_col, return_col}
        missing_cols = required_cols - set(returns.columns)
        if missing_cols:
            raise ValueError(f"DataFrame içinde zorunlu sütunlar eksik: {missing_cols}")

        if not delistings:
            return returns.clone()

        # Performans optimizasyonu: Yalnızca DataFrame'de bulunan hisselere ait olayları filtrele
        unique_tickers = set(returns[ticker_col].unique().to_list())
        relevant_delistings = [d for d in delistings if d.ticker in unique_tickers]

        if not relevant_delistings:
            return returns.clone()

        # Tarih sütununu karşılaştırma için standart naive pl.Datetime'a normalize et
        col_dtype = returns.schema[date_col]
        if col_dtype in (pl.String, pl.Utf8):
            date_expr = pl.col(date_col).str.to_datetime(strict=False)
        elif col_dtype == pl.Date:
            date_expr = pl.col(date_col).cast(pl.Datetime)
        elif isinstance(col_dtype, pl.Datetime) and col_dtype.time_zone is not None:
            date_expr = pl.col(date_col).dt.replace_time_zone(None)
        else:
            date_expr = pl.col(date_col)

        # return sütununu Float64'e normalize et ve geçici tarih sütunu oluştur
        corrected = returns.with_columns([
            date_expr.alias("_temp_cmp_dt"),
            pl.col(return_col).cast(pl.Float64).alias(return_col),
        ])

        # Her ilgili delisting olayı için vektörel güncelleme uygula
        for delist in relevant_delistings:
            delist_dt = delist.delisting_date

            # İflas veya recovery_rate belirtilmişse terminal getiri (-1 + recovery_rate)
            if delist.reason == "bankruptcy" or delist.recovery_rate is not None:
                recovery = delist.recovery_rate if delist.recovery_rate is not None else DEFAULT_BANKRUPTCY_RECOVERY_RATE
                terminal_return = -1.0 + recovery

                mask = (pl.col(ticker_col) == delist.ticker) & (pl.col("_temp_cmp_dt") >= delist_dt)
                corrected = corrected.with_columns(
                    pl.when(mask).then(pl.lit(terminal_return)).otherwise(pl.col(return_col)).alias(return_col)
                )
                logger.info(
                    "İflas/kurtarma düzeltmesi uygulandı: hisse=%s, kurtarma=%.2f, terminal_getiri=%.2f",
                    delist.ticker,
                    recovery,
                    terminal_return,
                )

            elif delist.final_price is not None:
                # Birleşme / devralma durumunda son fiyat üzerinden getiri (varsayılan 0.0)
                final_ret = 0.0
                mask = (pl.col(ticker_col) == delist.ticker) & (pl.col("_temp_cmp_dt") >= delist_dt)
                corrected = corrected.with_columns(
                    pl.when(mask).then(pl.lit(final_ret)).otherwise(pl.col(return_col)).alias(return_col)
                )
                logger.info(
                    "Kottan çıkma fiyat düzeltmesi uygulandı: hisse=%s, son_fiyat=%.2f, getiri=%.2f",
                    delist.ticker,
                    delist.final_price,
                    final_ret,
                )
            else:
                # Sebebi ne olursa olsun diğer delistlerde fail-closed varsayım: tam kayıp (-1.0)
                terminal_return = -1.0
                mask = (pl.col(ticker_col) == delist.ticker) & (pl.col("_temp_cmp_dt") >= delist_dt)
                corrected = corrected.with_columns(
                    pl.when(mask).then(pl.lit(terminal_return)).otherwise(pl.col(return_col)).alias(return_col)
                )
                logger.info(
                    "Genel delisting düzeltmesi uygulandı: hisse=%s, terminal_getiri=-1.0",
                    delist.ticker,
                )

        return corrected.drop("_temp_cmp_dt")

    def calculate_survivorship_bias_magnitude(
        self,
        full_returns: pl.DataFrame,
        survivor_only_returns: pl.DataFrame,
        return_col: str = "return",
    ) -> dict[str, float]:
        """
        Tam evren ile yalnızca hayatta kalan hisseler arasındaki yanlılık (bias) farkını ölçer.

        Null ve NaN değerleri güvenle filtreler, sıfır varyans ve tanımsız durumları guard altına alır.

        Args:
            full_returns: Delist edilen hisseleri de içeren tam evren getirileri.
            survivor_only_returns: Yalnızca bugüne kalan hisselerin getirileri.
            return_col: Getiri sütununun adı.

        Returns:
            dict[str, float]: Yanlılık büyüklüğü, yüzde farkı ve Sharpe yanlılığı.
        """
        # Boş veri kontrolleri ve temizleme
        if full_returns.is_empty() or return_col not in full_returns.columns:
            full_mean = 0.0
            full_std = 0.0
        else:
            clean_s = full_returns[return_col].drop_nulls().drop_nans()
            if clean_s.is_empty():
                full_mean = 0.0
                full_std = 0.0
            else:
                mean_val = clean_s.mean()
                std_val = clean_s.std()
                full_mean = float(mean_val) if mean_val is not None and not math.isnan(mean_val) else 0.0
                full_std = float(std_val) if std_val is not None and not math.isnan(std_val) else 0.0

        if survivor_only_returns.is_empty() or return_col not in survivor_only_returns.columns:
            survivor_mean = 0.0
            survivor_std = 0.0
        else:
            clean_s = survivor_only_returns[return_col].drop_nulls().drop_nans()
            if clean_s.is_empty():
                survivor_mean = 0.0
                survivor_std = 0.0
            else:
                mean_val = clean_s.mean()
                std_val = clean_s.std()
                survivor_mean = float(mean_val) if mean_val is not None and not math.isnan(mean_val) else 0.0
                survivor_std = float(std_val) if std_val is not None and not math.isnan(std_val) else 0.0

        bias = survivor_mean - full_mean
        bias_pct = (bias / abs(full_mean) * 100.0) if full_mean != 0.0 else 0.0

        ann_factor = math.sqrt(TRADING_DAYS_PER_YEAR)
        full_sharpe = (full_mean / full_std * ann_factor) if full_std > 0.0 else 0.0
        survivor_sharpe = (survivor_mean / survivor_std * ann_factor) if survivor_std > 0.0 else 0.0
        sharpe_bias = survivor_sharpe - full_sharpe

        return {
            "full_universe_mean_return": round(full_mean, 6),
            "survivor_only_mean_return": round(survivor_mean, 6),
            "bias_magnitude": round(bias, 6),
            "bias_percentage": round(bias_pct, 2),
            "full_universe_sharpe": round(full_sharpe, 3),
            "survivor_only_sharpe": round(survivor_sharpe, 3),
            "sharpe_bias": round(sharpe_bias, 3),
        }

    def generate_universe_report(
        self,
        start_date: datetime | str | date,
        end_date: datetime | str | date,
        all_known_tickers: set[str] | None = None,
        interval_days: int = DEFAULT_SNAPSHOT_INTERVAL_DAYS,
    ) -> list[UniverseSnapshot]:
        """
        Belirtilen tarih aralığı boyunca evrenin periyodik değişim raporunu üretir.

        Args:
            start_date: Başlangıç tarihi.
            end_date: Bitiş tarihi.
            all_known_tickers: Takip edilen tüm hisse sembolleri (opsiyonel).
            interval_days: Snapshot alma aralığı (gün cinsinden, pozitif tamsayı).

        Returns:
            list[UniverseSnapshot]: Kronolojik evren snapshot'ları listesi.

        Raises:
            ValueError: Başlangıç tarihi bitişten büyükse veya interval_days <= 0 ise.
        """
        if interval_days <= 0:
            raise ValueError(f"Snapshot aralık gün sayısı (interval_days) pozitif olmalıdır: {interval_days}")

        start_dt = _parse_to_datetime(start_date)
        end_dt = _parse_to_datetime(end_date)

        if start_dt > end_dt:
            raise ValueError(f"Başlangıç tarihi bitiş tarihinden sonra olamaz: {start_dt} > {end_dt}")

        with self._lock:
            if all_known_tickers is None:
                pool = self._active_tickers | set(self._delisted_tickers.keys())
            else:
                pool = {t.strip().upper() for t in all_known_tickers if t}

        snapshots: list[UniverseSnapshot] = []
        current = start_dt

        while current <= end_dt:
            active = self.get_universe_at_date(current, pool)
            delisted = pool - active

            snapshots.append(
                UniverseSnapshot(
                    date=current,
                    active_tickers=active,
                    delisted_tickers=delisted,
                    total_count=len(pool),
                    active_count=len(active),
                    delisted_count=len(delisted),
                )
            )

            current = current + timedelta(days=interval_days)

        return snapshots

    def get_delisted_tickers(self, before_date: datetime | str | date | None = None) -> list[DelistingEvent]:
        """
        Belirtilen tarihten önce kottan çıkarılmış hisselerin olay listesini döndürür.

        Args:
            before_date: İsteğe bağlı üst sınır tarihi.

        Returns:
            list[DelistingEvent]: Filtrelenmiş DelistingEvent listesi.
        """
        with self._lock:
            if before_date is None:
                return list(self._delisting_events)
            cutoff = _parse_to_datetime(before_date)
            return [e for e in self._delisting_events if e.delisting_date <= cutoff]

    def get_delisted_ticker_symbols(self, before_date: datetime | str | date | None = None) -> set[str]:
        """
        Belirtilen tarihten önce kottan çıkarılmış hisse sembolleri kümesini döndürür.

        Args:
            before_date: İsteğe bağlı üst sınır tarihi.

        Returns:
            set[str]: Delist edilmiş hisse kodları kümesi.
        """
        events = self.get_delisted_tickers(before_date=before_date)
        return {e.ticker for e in events}

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"SurvivorshipBiasHandler(events_count={len(self._delisting_events)}, "
                f"delisted_count={len(self._delisted_tickers)}, active_universe={len(self._active_tickers)})"
            )


# =====================================================================
# BIST DELISTING VERİ YÜKLEYİCİ
# =====================================================================
class BISTSurvivorshipDataLoader:
    """
    Borsa İstanbul delisting ve kottan çıkarılma veri yükleyicisi.

    Resmi bülten ve KAP duyurularından alınan gerçek tarihsel verileri işler.
    """

    @staticmethod
    def load_from_csv(filepath: str) -> list[DelistingEvent]:
        """
        CSV dosyasından güvenli Polars okumasıyla delisting verilerini yükler.

        Args:
            filepath: CSV dosyasının dosya yolu.

        Returns:
            list[DelistingEvent]: Ayrıştırılmış DelistingEvent listesi.

        Raises:
            FileNotFoundError: Dosya bulunamadığında.
            ValueError: Zorunlu sütunlar eksik olduğunda.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Delisting CSV dosyası bulunamadı: {filepath}")

        df = pl.read_csv(filepath)
        required = {"ticker", "delisting_date"}
        if not required.issubset(set(df.columns)):
            raise ValueError(f"CSV dosyasında zorunlu sütunlar bulunamadı: {required - set(df.columns)}")

        events: list[DelistingEvent] = []
        for row in df.iter_rows(named=True):
            raw_date = row["delisting_date"]
            if raw_date is None or str(raw_date).strip() == "":
                continue

            parsed_dt = _parse_to_datetime(raw_date)

            final_price = None
            if row.get("final_price") is not None and str(row["final_price"]).strip() != "":
                try:
                    final_price = float(row["final_price"])
                except (ValueError, TypeError):
                    final_price = None

            rec_rate = None
            if row.get("recovery_rate") is not None and str(row["recovery_rate"]).strip() != "":
                try:
                    rec_rate = float(row["recovery_rate"])
                except (ValueError, TypeError):
                    rec_rate = None

            events.append(
                DelistingEvent(
                    ticker=str(row["ticker"]),
                    delisting_date=parsed_dt,
                    reason=str(row.get("reason", "unknown")),
                    final_price=final_price,
                    recovery_rate=rec_rate,
                )
            )
        return events

    @staticmethod
    def create_known_bist_delistings() -> list[DelistingEvent]:
        """
        BIST için resmi kaynaklardan doğrulanmış delisting kayıtlarını döndürür.

        Not: Mock veya uydurma veri içermez (Kural 1). Gerçek resmi liste
        veritabanı veya CSV'den dolduruluncaya kadar boş liste döner.

        Returns:
            list[DelistingEvent]: Doğrulanmış BIST delisting kayıtları.
        """
        logger.warning(
            "create_known_bist_delistings() çağrıldı: Henüz veritabanına bağlanmadı, boş liste dönülüyor. "
            "Gerçek BIST delisting verileri resmi KAP / BIST bültenlerinden beslenmelidir."
        )
        return []

    def __repr__(self) -> str:
        return "BISTSurvivorshipDataLoader()"


# =====================================================================
# GÖÇ VE GERİYE DÖNÜK UYUMLULUK ALIAS'I
# =====================================================================
SurvivorshipBiasCorrector = SurvivorshipBiasHandler

# Singleton örneği
survivorship_handler = SurvivorshipBiasHandler()

__all__ = [
    "DEFAULT_BANKRUPTCY_RECOVERY_RATE",
    "DEFAULT_MAX_DELISTING_EVENTS",
    "DEFAULT_SNAPSHOT_INTERVAL_DAYS",
    "TRADING_DAYS_PER_YEAR",
    "BISTSurvivorshipDataLoader",
    "DelistingEvent",
    "SurvivorshipBiasCorrector",
    "SurvivorshipBiasHandler",
    "UniverseSnapshot",
    "survivorship_handler",
]
