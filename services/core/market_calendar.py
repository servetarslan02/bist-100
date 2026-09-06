"""ALPHA BIST — Piyasa Takvimi ve Seans Durum Yönetimi (Market Calendar v2.0).

Bu modül, Borsa İstanbul (BIST) pay piyasası resmi işlem saatleri, seans evreleri,
yarım iş günleri, resmi tatiller ve devre kesici/işlem durdurma durumlarını
merkezi, thread-safe, Polars ve DuckDB uyumlu olarak yönetir.

Eylül 2025 BIST Güncel Kuralları:
- Tam Gün Sürekli Müzayede: 10:00 - 18:00
- Açılış Seansı (Emir Toplama & Eşleşme): 09:40 - 10:00
- Kapanış Seansı (Açık Artırma & Kapanış Fiyatından İşlem): 18:01 - 18:10
- Yarım Gün Sürekli Müzayede: 10:00 - 12:30 (Kapanış: 12:40)
- EBDKS: BIST-100 endeksi %6 ve üzeri düştüğünde devreye girer
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.holiday_manager import holiday_manager
from services.core.market_session_fsm import _TZ_ISTANBUL, BISTMarketPhase, bist_session_fsm
from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# =====================================================
# SABİTLER (CONSTANTS)
# =====================================================

DEFAULT_MARKET_OPEN_TIME: Final[time] = time(10, 0)
DEFAULT_MARKET_CLOSE_TIME: Final[time] = time(18, 0)
DEFAULT_HALF_MARKET_CLOSE_TIME: Final[time] = time(12, 30)
DEFAULT_PRE_MARKET_START_TIME: Final[time] = time(9, 40)
DEFAULT_CLOSING_END_TIME: Final[time] = time(18, 10)
DEFAULT_HALF_CLOSING_END_TIME: Final[time] = time(12, 40)
DEFAULT_CALENDAR_LOOKAHEAD_DAYS: Final[int] = 30
DEFAULT_MARKET_CALENDAR_DB_PATH: Final[Path] = Path("data/duckdb/alpha_bist_market_calendar.duckdb")


# =====================================================
# ENUM VE VERİ MODELLERİ (ENUMS & DATA MODELS)
# =====================================================


class MarketSession(StrEnum):
    """BIST işlem seans evreleri."""

    PRE_MARKET = "PRE_MARKET"  # 09:40 - 10:00 (Açılış emir toplama)
    OPENING = "OPENING"  # 09:55 - 10:00 (Açılış fiyat belirleme)
    CONTINUOUS = "CONTINUOUS"  # 10:00 - 18:00 (Sürekli müzayede)
    CLOSING = "CLOSING"  # 18:01 - 18:10 (Kapanış marj, açık artırma ve işlemler)
    CLOSED = "CLOSED"  # Seans kapalı

    def __repr__(self) -> str:
        return f"MarketSession.{self.name}"


class MarketStatus(StrEnum):
    """Piyasa genel çalışma durumu."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_MARKET = "PRE_MARKET"
    HALT = "HALT"
    EARLY_CLOSE = "EARLY_CLOSE"

    def __repr__(self) -> str:
        return f"MarketStatus.{self.name}"


@dataclass(slots=True)
class MarketCalendarInfo:
    """Belirli bir zaman dilimindeki piyasa takvim ve seans durumu.

    Attributes:
        date: Tarih (YYYY-MM-DD).
        is_trading_day: Günün işlem günü olup olmadığı.
        is_half_day: Günün yarım seans günü olup olmadığı.
        is_market_open: Piyasanın emir girişine/işleme açık olup olmadığı.
        session: Mevcut seans evresi (MarketSession).
        status: Piyasa durumu (MarketStatus).
        next_open: Bir sonraki seans açılış zaman damgası (ISO 8601).
        next_close: Bir sonraki seans kapanış zaman damgası (ISO 8601).
        ebdks_active: Endeks Bazlı Devre Kesici Sistemi aktiflik durumu.
        query_time: Sorgunun yapıldığı zaman damgası (ISO 8601).
    """

    date: str
    is_trading_day: bool
    is_half_day: bool
    is_market_open: bool
    session: str
    status: str
    next_open: str
    next_close: str
    ebdks_active: bool
    query_time: str

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlük yapısına dönüştürür.

        Returns:
            dict[str, Any]: Serileştirilebilir sözlük.
        """
        return {
            "date": self.date,
            "is_trading_day": self.is_trading_day,
            "is_half_day": self.is_half_day,
            "is_market_open": self.is_market_open,
            "session": self.session,
            "status": self.status,
            "next_open": self.next_open,
            "next_close": self.next_close,
            "ebdks_active": self.ebdks_active,
            "query_time": self.query_time,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli yüksek hızlı JSON bayt dizisine serileştirir.

        Returns:
            bytes: orjson kodlu baytlar.
        """
        return orjson.dumps(self.to_dict(), default=str)

    def to_json(self) -> str:
        """Modeli UTF-8 JSON metnine dönüştürür.

        Returns:
            str: JSON metni.
        """
        return orjson.dumps(self.to_dict(), default=str).decode("utf-8")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MarketCalendarInfo:
        """Sözlükten MarketCalendarInfo nesnesi türetir.

        Args:
            d: Model verilerini içeren sözlük.

        Returns:
            MarketCalendarInfo: Model nesnesi.
        """
        return cls(
            date=str(d.get("date", "")),
            is_trading_day=bool(d.get("is_trading_day", False)),
            is_half_day=bool(d.get("is_half_day", False)),
            is_market_open=bool(d.get("is_market_open", False)),
            session=str(d.get("session", MarketSession.CLOSED.value)),
            status=str(d.get("status", MarketStatus.CLOSED.value)),
            next_open=str(d.get("next_open", "")),
            next_close=str(d.get("next_close", "")),
            ebdks_active=bool(d.get("ebdks_active", False)),
            query_time=str(d.get("query_time", "")),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> MarketCalendarInfo:
        """JSON metni veya baytlarından MarketCalendarInfo nesnesi türetir.

        Args:
            raw: JSON dizgisi veya bayt dizisi.

        Returns:
            MarketCalendarInfo: Çözümlenmiş model nesnesi.
        """
        data = orjson.loads(raw)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        """Açıklayıcı model gösterimi.

        Returns:
            str: Model özeti.
        """
        return (
            f"MarketCalendarInfo(tarih='{self.date}', acik={self.is_market_open}, "
            f"seans='{self.session}', durum='{self.status}', ebdks={self.ebdks_active})"
        )


# =====================================================
# BIST PİYASA TAKVİMİ MOTORU (MARKET CALENDAR)
# =====================================================


class MarketCalendar:
    """Borsa İstanbul işlem takvimi, seans ve tatil koordinasyon motoru."""

    MARKET_OPEN = DEFAULT_MARKET_OPEN_TIME
    MARKET_CLOSE = DEFAULT_MARKET_CLOSE_TIME
    HALF_MARKET_CLOSE = DEFAULT_HALF_MARKET_CLOSE_TIME
    PRE_MARKET_START = DEFAULT_PRE_MARKET_START_TIME
    CLOSING_END = DEFAULT_CLOSING_END_TIME
    HALF_CLOSING_END = DEFAULT_HALF_CLOSING_END_TIME

    def __init__(
        self,
        holidays: list[date] | set[date] | None = None,
        half_days: list[date] | set[date] | None = None,
    ) -> None:
        """Piyasa takvim motorunu başlatır.

        Args:
            holidays: Opsiyonel başlangıç tatil günleri listesi.
            half_days: Opsiyonel başlangıç yarım günleri listesi.
        """
        self._lock = threading.RLock()
        self._hm = holiday_manager

        today = date.today()
        with self._lock:
            self._holidays: set[date] = set(holidays) if holidays else self._hm.get_holidays(today.year)
            self._half_days: set[date] = set(half_days) if half_days else self._hm.get_half_days(today.year)
            self._halts: dict[date, list[tuple[time, time]]] = {}

            # FSM'ye tatil günlerini senkronize aktar
            holiday_strs = {d.strftime("%Y-%m-%d") for d in self._holidays}
            half_day_strs = {d.strftime("%Y-%m-%d") for d in self._half_days}
            bist_session_fsm.set_holidays(holiday_strs)
            bist_session_fsm.set_half_days(half_day_strs)

        logger.info(
            "islem_takvimi_baslatildi",
            yil=today.year,
            tatil_sayisi=len(self._holidays),
            yarim_gun_sayisi=len(self._half_days),
        )

    def _normalize_datetime(self, dt: datetime | None = None) -> datetime:
        """Zaman damgasını doğrular ve İstanbul zaman dilimine normalleştirir."""
        if dt is None:
            return datetime.now(_TZ_ISTANBUL)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_TZ_ISTANBUL)
        return dt.astimezone(_TZ_ISTANBUL)

    @otel_trace("market_calendar.is_half_day")
    def is_half_day(self, d: date | None = None) -> bool:
        """Belirtilen günün yarım seans günü olup olmadığını doğrular.

        Args:
            d: Kontrol edilecek tarih (varsayılan: bugün).

        Returns:
            bool: Yarım gün ise True, aksi halde False.
        """
        target_date = d if d is not None else date.today()
        with self._lock:
            if target_date in self._half_days:
                return True
            return self._hm.is_half_day(target_date)

    @otel_trace("market_calendar.is_trading_day")
    def is_trading_day(self, d: date | None = None) -> bool:
        """Belirtilen günün işlem yapılabilir BIST iş günü olup olmadığını doğrular.

        Args:
            d: Kontrol edilecek tarih (varsayılan: bugün).

        Returns:
            bool: İşlem günü ise True, tatil veya hafta sonu ise False.
        """
        target_date = d if d is not None else date.today()
        if target_date.weekday() >= 5:
            return False

        with self._lock:
            if target_date in self._holidays:
                return False
            return self._hm.is_trading_day(target_date)

    @otel_trace("market_calendar.is_market_open")
    def is_market_open(self, dt: datetime | None = None) -> bool:
        """Belirtilen anda piyasanın emir girişine ve işlemlere açık olup olmadığını denetler.

        Args:
            dt: Kontrol edilecek zaman damgası (varsayılan: şu an).

        Returns:
            bool: Piyasa açık ise True, kapalı veya durdurulmuş ise False.
        """
        current_dt = self._normalize_datetime(dt)
        current_date = current_dt.date()

        if not self.is_trading_day(current_date):
            return False

        # Aktif halt (işlem durdurma) kontrolü
        current_time = current_dt.time()
        with self._lock:
            halts = self._halts.get(current_date, [])
            for start, end in halts:
                if start <= current_time <= end:
                    return False

        if bist_session_fsm.is_ebdks_active():
            return False

        phase = bist_session_fsm.get_phase(current_time=current_dt)
        return bist_session_fsm.is_order_entry_allowed(phase)

    @otel_trace("market_calendar.get_session")
    def get_session(self, dt: datetime | None = None) -> MarketSession:
        """Belirtilen an için geçerli seans evresini döndürür.

        Args:
            dt: Kontrol edilecek zaman damgası (varsayılan: şu an).

        Returns:
            MarketSession: Aktif seans türü.
        """
        current_dt = self._normalize_datetime(dt)
        if not self.is_trading_day(current_dt.date()):
            return MarketSession.CLOSED

        phase = bist_session_fsm.get_phase(current_time=current_dt)
        mapping = {
            BISTMarketPhase.CLOSED: MarketSession.CLOSED,
            BISTMarketPhase.OPENING_AUCTION_COLLECTION: MarketSession.PRE_MARKET,
            BISTMarketPhase.OPENING_AUCTION_DETERMINATION: MarketSession.OPENING,
            BISTMarketPhase.CONTINUOUS_AUCTION: MarketSession.CONTINUOUS,
            BISTMarketPhase.CIRCUIT_BREAKER_AUCTION: MarketSession.CONTINUOUS,
            BISTMarketPhase.CLOSING_AUCTION_COLLECTION: MarketSession.CLOSING,
            BISTMarketPhase.CLOSING_AUCTION_DETERMINATION: MarketSession.CLOSING,
            BISTMarketPhase.CLOSING_PRICE_TRADING: MarketSession.CLOSING,
        }
        return mapping.get(phase, MarketSession.CLOSED)

    @otel_trace("market_calendar.get_status")
    def get_status(self, dt: datetime | None = None) -> MarketStatus:
        """Piyasanın genel operasyonel durumunu döndürür.

        Args:
            dt: Kontrol edilecek zaman damgası (varsayılan: şu an).

        Returns:
            MarketStatus: OPEN, CLOSED, PRE_MARKET, HALT veya EARLY_CLOSE.
        """
        current_dt = self._normalize_datetime(dt)
        current_date = current_dt.date()
        current_time = current_dt.time()

        # Halt kontrolü
        with self._lock:
            halts = self._halts.get(current_date, [])
            for start, end in halts:
                if start <= current_time <= end:
                    return MarketStatus.HALT

        if bist_session_fsm.is_ebdks_active():
            return MarketStatus.HALT

        session = self.get_session(current_dt)
        if session == MarketSession.CLOSED:
            return MarketStatus.CLOSED
        elif session == MarketSession.PRE_MARKET:
            return MarketStatus.PRE_MARKET
        else:
            return MarketStatus.OPEN

    @otel_trace("market_calendar.next_open")
    def next_open(self, dt: datetime | None = None) -> datetime:
        """Bir sonraki işlem seansının açılış zaman damgasını hesaplar.

        Args:
            dt: Referans zaman damgası (varsayılan: şu an).

        Returns:
            datetime: Sonraki seans açılış anı (İstanbul saat diliminde).
        """
        current_dt = self._normalize_datetime(dt)
        target_date = current_dt.date()

        if self.is_trading_day(target_date):
            today_open = datetime.combine(target_date, self.MARKET_OPEN, tzinfo=_TZ_ISTANBUL)
            if current_dt < today_open:
                return today_open

        check_date = target_date + timedelta(days=1)
        for _ in range(DEFAULT_CALENDAR_LOOKAHEAD_DAYS):
            if self.is_trading_day(check_date):
                return datetime.combine(check_date, self.MARKET_OPEN, tzinfo=_TZ_ISTANBUL)
            check_date += timedelta(days=1)

        return current_dt + timedelta(days=1)

    @otel_trace("market_calendar.next_close")
    def next_close(self, dt: datetime | None = None) -> datetime:
        """Bir sonraki işlem seansının kapanış zaman damgasını hesaplar.

        Args:
            dt: Referans zaman damgası (varsayılan: şu an).

        Returns:
            datetime: Sonraki seans kapanış anı (İstanbul saat diliminde).
        """
        current_dt = self._normalize_datetime(dt)
        target_date = current_dt.date()

        if self.is_trading_day(target_date):
            close_time = self.HALF_MARKET_CLOSE if self.is_half_day(target_date) else self.MARKET_CLOSE
            today_close = datetime.combine(target_date, close_time, tzinfo=_TZ_ISTANBUL)
            if current_dt < today_close:
                return today_close

        check_date = target_date + timedelta(days=1)
        for _ in range(DEFAULT_CALENDAR_LOOKAHEAD_DAYS):
            if self.is_trading_day(check_date):
                close_time = self.HALF_MARKET_CLOSE if self.is_half_day(check_date) else self.MARKET_CLOSE
                return datetime.combine(check_date, close_time, tzinfo=_TZ_ISTANBUL)
            check_date += timedelta(days=1)

        return current_dt + timedelta(days=1)

    @otel_trace("market_calendar.trading_days_between")
    def trading_days_between(self, start: date, end: date) -> int:
        """İki tarih arasındaki toplam işlem günü sayısını hesaplar (sınırlar dahil).

        Args:
            start: Başlangıç tarihi.
            end: Bitiş tarihi.

        Returns:
            int: İşlem günü sayısı.
        """
        if start > end:
            return 0
        count = 0
        current = start
        while current <= end:
            if self.is_trading_day(current):
                count += 1
            current += timedelta(days=1)
        return count

    @otel_trace("market_calendar.add_halt")
    def add_halt(self, d: date, start: time, end: time) -> None:
        """Belirtilen gün ve saat aralığı için bir işlem durdurma (halt) kaydeder.

        Args:
            d: Durdurmanın geçerli olduğu tarih.
            start: Başlangıç saati.
            end: Bitiş saati.
        """
        with self._lock:
            if d not in self._halts:
                self._halts[d] = []
            self._halts[d].append((start, end))
            logger.warning("islem_durdurma_eklendi", tarih=d.isoformat(), baslangic=start.isoformat(), bitis=end.isoformat())

    @otel_trace("market_calendar.clear_halts")
    def clear_halts(self, d: date | None = None) -> None:
        """Belirli bir günün veya tüm kayıtlı durdurma aralıklarını temizler.

        Args:
            d: Temizlenecek tarih veya tümü için None.
        """
        with self._lock:
            if d is not None:
                self._halts.pop(d, None)
            else:
                self._halts.clear()

    @otel_trace("market_calendar.report_no_data")
    def report_no_data(self, d: date | None = None) -> bool:
        """Veri akışı kesintisini raporlar ve anlık tatil tespiti tetikler.

        Args:
            d: İlgili tarih.

        Returns:
            bool: Anlık tatil tespit edildiyse True.
        """
        return self._hm.report_no_data(d)

    @otel_trace("market_calendar.add_manual_holiday")
    def add_manual_holiday(self, d: date, reason: str = "") -> None:
        """Anlık veya idari kararla ilan edilen tatili sisteme ekler.

        Args:
            d: Tatil tarihi.
            reason: İlan gerekçesi.
        """
        with self._lock:
            self._hm.add_manual_holiday(d, reason)
            self._holidays.add(d)
            holiday_strs = {dd.strftime("%Y-%m-%d") for dd in self._hm.get_holidays(d.year)}
            bist_session_fsm.set_holidays(holiday_strs)
            logger.warning("manuel_tatil_eklendi", tarih=d.isoformat(), gerekce=reason)

    @otel_trace("market_calendar.sync_from_bist")
    async def sync_from_bist(self) -> bool:
        """Borsa İstanbul resmi web sitesinden tatil günlerini günceller.

        Returns:
            bool: Senkronizasyon başarılı ise True.
        """
        success = await self._hm.sync_from_bist()
        if success:
            today = date.today()
            with self._lock:
                self._holidays = self._hm.get_holidays(today.year)
                self._half_days = self._hm.get_half_days(today.year)
                holiday_strs = {dd.strftime("%Y-%m-%d") for dd in self._holidays}
                half_day_strs = {dd.strftime("%Y-%m-%d") for dd in self._half_days}
                bist_session_fsm.set_holidays(holiday_strs)
                bist_session_fsm.set_half_days(half_day_strs)
        return success

    @otel_trace("market_calendar.get_holiday_info")
    def get_holiday_info(self, year: int | None = None) -> str:
        """Yıl içindeki tatil ve arife günlerinin metin dökümünü döndürür.

        Args:
            year: Hedef takvim yılı.

        Returns:
            str: Biçimlendirilmiş tatil listesi metni.
        """
        return self._hm.get_all_holidays_text(year)

    @otel_trace("market_calendar.get_info")
    def get_info(self, dt: datetime | None = None) -> dict[str, Any]:
        """Piyasa durumu ve bir sonraki seans detaylarını sözlük formatında döndürür.

        Args:
            dt: Referans zaman damgası.

        Returns:
            dict[str, Any]: Seans ve takvim detayları.
        """
        return self.get_calendar_info(dt).to_dict()

    @otel_trace("market_calendar.get_calendar_info")
    def get_calendar_info(self, dt: datetime | None = None) -> MarketCalendarInfo:
        """Piyasa durumu ve seans bilgilerini yapılandırılmış model olarak döndürür.

        Args:
            dt: Referans zaman damgası.

        Returns:
            MarketCalendarInfo: Yapılandırılmış model nesnesi.
        """
        current_dt = self._normalize_datetime(dt)
        return MarketCalendarInfo(
            date=current_dt.date().isoformat(),
            is_trading_day=self.is_trading_day(current_dt.date()),
            is_half_day=self.is_half_day(current_dt.date()),
            is_market_open=self.is_market_open(current_dt),
            session=self.get_session(current_dt).value,
            status=self.get_status(current_dt).value,
            next_open=self.next_open(current_dt).isoformat(),
            next_close=self.next_close(current_dt).isoformat(),
            ebdks_active=bist_session_fsm.is_ebdks_active(),
            query_time=current_dt.isoformat(),
        )

    def export_schedule_to_polars(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """Belirtilen tarih aralığındaki seans takvimini Polars DataFrame olarak dışa aktarır.

        Args:
            start_date: Başlangıç tarihi (varsayılan: bugün).
            end_date: Bitiş tarihi (varsayılan: 30 gün sonrası).

        Returns:
            pl.DataFrame: Tarih bazlı seans çizelgesi tablosu.
        """
        start = start_date if start_date is not None else date.today()
        end = end_date if end_date is not None else (start + timedelta(days=DEFAULT_CALENDAR_LOOKAHEAD_DAYS))

        schema = {
            "date": pl.String,
            "day_name": pl.String,
            "is_trading_day": pl.Boolean,
            "is_half_day": pl.Boolean,
            "market_open": pl.String,
            "market_close": pl.String,
            "status": pl.String,
        }

        if start > end:
            return pl.DataFrame(schema=schema)

        rows: list[dict[str, Any]] = []
        cur = start
        while cur <= end:
            is_trade = self.is_trading_day(cur)
            is_half = self.is_half_day(cur)
            if is_trade:
                open_str = self.MARKET_OPEN.strftime("%H:%M")
                close_str = self.HALF_MARKET_CLOSE.strftime("%H:%M") if is_half else self.MARKET_CLOSE.strftime("%H:%M")
                stat_str = MarketStatus.EARLY_CLOSE.value if is_half else MarketStatus.OPEN.value
            else:
                open_str = ""
                close_str = ""
                stat_str = MarketStatus.CLOSED.value

            rows.append({
                "date": cur.isoformat(),
                "day_name": cur.strftime("%A"),
                "is_trading_day": is_trade,
                "is_half_day": is_half,
                "market_open": open_str,
                "market_close": close_str,
                "status": stat_str,
            })
            cur += timedelta(days=1)

        return pl.DataFrame(rows, schema=schema)

    def export_schedule_to_duckdb(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        db_path: str | Path | None = None,
    ) -> int:
        """Seans çizelgesini DuckDB `bist_market_schedule` tablosuna atomik olarak yazar.

        Args:
            start_date: Başlangıç tarihi.
            end_date: Bitiş tarihi.
            db_path: DuckDB dosya yolu.

        Returns:
            int: Eklenen veya güncellenen gün sayısı.
        """
        df = self.export_schedule_to_polars(start_date=start_date, end_date=end_date)
        if df.is_empty():
            return 0

        target_path = Path(db_path) if db_path is not None else DEFAULT_MARKET_CALENDAR_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.is_file() and target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)

        con = duckdb.connect(str(target_path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bist_market_schedule (
                    date VARCHAR PRIMARY KEY,
                    day_name VARCHAR,
                    is_trading_day BOOLEAN,
                    is_half_day BOOLEAN,
                    market_open VARCHAR,
                    market_close VARCHAR,
                    status VARCHAR,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            arrow_table = df.to_arrow()
            con.register("sched_arrow", arrow_table)
            con.execute("""
                INSERT OR REPLACE INTO bist_market_schedule (
                    date, day_name, is_trading_day, is_half_day, market_open, market_close, status
                )
                SELECT date, day_name, is_trading_day, is_half_day, market_open, market_close, status
                FROM sched_arrow
            """)
            con.unregister("sched_arrow")
            con.commit()
            return len(df)
        finally:
            con.close()

    @staticmethod
    def query_schedule_duckdb(
        db_path: str | Path | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pl.DataFrame:
        """DuckDB bist_market_schedule tablosundan Polars DataFrame olarak takvim sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            start_date: Opsiyonel başlangıç tarihi filtresi (YYYY-MM-DD).
            end_date: Opsiyonel bitiş tarihi filtresi (YYYY-MM-DD).

        Returns:
            pl.DataFrame: Takvim kayıtları veri çerçevesi.
        """
        schema = {
            "date": pl.String,
            "day_name": pl.String,
            "is_trading_day": pl.Boolean,
            "is_half_day": pl.Boolean,
            "market_open": pl.String,
            "market_close": pl.String,
            "status": pl.String,
        }
        target_path = Path(db_path) if db_path is not None else DEFAULT_MARKET_CALENDAR_DB_PATH
        if not target_path.exists():
            return pl.DataFrame(schema=schema)
        if target_path.is_file() and target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)
            return pl.DataFrame(schema=schema)

        con = duckdb.connect(str(target_path), read_only=True)
        try:
            tbl_check = con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'bist_market_schedule'"
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = "SELECT * FROM bist_market_schedule WHERE 1=1"
            params: list[Any] = []
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            query += " ORDER BY date ASC"
            return con.execute(query, params).pl()
        finally:
            con.close()

    def __repr__(self) -> str:
        """Türkçe açıklayıcı metin gösterimi.

        Returns:
            str: Durum özeti.
        """
        with self._lock:
            return (
                f"MarketCalendar(tatil_sayisi={len(self._holidays)}, "
                f"yarim_gun_sayisi={len(self._half_days)}, durdurma_sayisi={len(self._halts)})"
            )


# =====================================================
# GLOBAL SINGLETON ÖRNEĞİ
# =====================================================

market_calendar: Final[MarketCalendar] = MarketCalendar()


def get_market_calendar() -> MarketCalendar:
    """Merkezi piyasa takvimi tekil örneğini döndürür."""
    return market_calendar


# =====================================================
# MODÜL SEVİYESİ KOLAYLIK FONKSİYONLARI (CONVENIENCE HELPERS)
# =====================================================


def is_market_open(dt: datetime | None = None) -> bool:
    """Piyasanın işlem görmeye açık olup olmadığını doğrular."""
    return market_calendar.is_market_open(dt)


def is_trading_day(d: date | None = None) -> bool:
    """Günün BIST işlem günü olup olmadığını doğrular."""
    return market_calendar.is_trading_day(d)


def is_half_day(d: date | None = None) -> bool:
    """Günün yarım seans olup olmadığını doğrular."""
    return market_calendar.is_half_day(d)


def get_session(dt: datetime | None = None) -> MarketSession:
    """Aktif seans evresini döndürür."""
    return market_calendar.get_session(dt)


def get_status(dt: datetime | None = None) -> MarketStatus:
    """Piyasa genel durumunu döndürür."""
    return market_calendar.get_status(dt)


def get_market_info(dt: datetime | None = None) -> dict[str, Any]:
    """Piyasa seans bilgilerini sözlük formatında döndürür."""
    return market_calendar.get_info(dt)


def get_calendar_info(dt: datetime | None = None) -> MarketCalendarInfo:
    """Piyasa durumunu MarketCalendarInfo modeli olarak döndürür."""
    return market_calendar.get_calendar_info(dt)


def next_open(dt: datetime | None = None) -> datetime:
    """Sonraki seans açılış anını döndürür."""
    return market_calendar.next_open(dt)


def next_close(dt: datetime | None = None) -> datetime:
    """Sonraki seans kapanış anını döndürür."""
    return market_calendar.next_close(dt)


def trading_days_between(start: date, end: date) -> int:
    """İki tarih arasındaki işlem günü adedini döndürür."""
    return market_calendar.trading_days_between(start, end)


def add_market_halt(d: date, start: time, end: time) -> None:
    """Piyasa takvimine işlem durdurma (halt) aralığı ekler."""
    market_calendar.add_halt(d, start, end)


def export_schedule_to_polars(
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """Seans takvimini Polars DataFrame olarak üretir."""
    return market_calendar.export_schedule_to_polars(start_date, end_date)


def export_schedule_to_duckdb(
    start_date: date | None = None,
    end_date: date | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Seans takvimini DuckDB bist_market_schedule tablosuna yazar."""
    return market_calendar.export_schedule_to_duckdb(start_date, end_date, db_path)


def query_schedule_duckdb(
    db_path: str | Path | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pl.DataFrame:
    """DuckDB üzerinden seans takvimini doğrudan Polars DataFrame olarak sorgular."""
    return MarketCalendar.query_schedule_duckdb(db_path, start_date, end_date)


__all__: list[str] = [
    "DEFAULT_CALENDAR_LOOKAHEAD_DAYS",
    "DEFAULT_CLOSING_END_TIME",
    "DEFAULT_HALF_CLOSING_END_TIME",
    "DEFAULT_HALF_MARKET_CLOSE_TIME",
    "DEFAULT_MARKET_CALENDAR_DB_PATH",
    "DEFAULT_MARKET_CLOSE_TIME",
    "DEFAULT_MARKET_OPEN_TIME",
    "DEFAULT_PRE_MARKET_START_TIME",
    "MarketCalendar",
    "MarketCalendarInfo",
    "MarketSession",
    "MarketStatus",
    "add_market_halt",
    "export_schedule_to_duckdb",
    "export_schedule_to_polars",
    "get_calendar_info",
    "get_market_calendar",
    "get_market_info",
    "get_session",
    "get_status",
    "is_half_day",
    "is_market_open",
    "is_trading_day",
    "market_calendar",
    "next_close",
    "next_open",
    "query_schedule_duckdb",
    "trading_days_between",
]
