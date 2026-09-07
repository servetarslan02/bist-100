"""ALPHA BIST — Brüt Takas ve VBTS Tedbir İzleme Motoru (Gross Settlement Monitor).

Bu modül, Borsa İstanbul (BIST) ve Sermaye Piyasası Kurulu (SPK) tarafından yürütülen
Volatilite Bazlı Tedbir Sistemi (VBTS) ve münferit kararlar doğrultusunda hisselere
getirilen brüt takas, açığa satış ve kredili işlem yasağı, emir paketi ve gün içi al-sat
kısıtlamalarını takip eder.

SPK & BIST Mevzuat Kuralları:
- Brüt Takasta Açığa Satış Yasağı: Brüt takas kapsamındaki paylarda açığa satış kesinlikle yapılamaz.
- Kredili İşlem Yasağı: Brüt takas uygulanan paylar kredili alım işlemlerine konu edilemez.
- Takas Süresi ve Nakit: Brüt takasta alım bedeli T+0 anında tam nakit olarak tahsil edilir;
  aynı gün içinde alınan hisse satılamaz veya gün içi netleştirme yapılamaz.
- Point-In-Time Geçerlilik: Tedbirler başlangıç (`start_date`) ve bitiş (`end_date`) tarihleri
  arasında geçerlidir; süresi dolan tedbirler otomatik olarak hükümsüz kalır.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# ==============================================================================
# Standart Tedbir ve Yapılandırma Sabitleri
# ==============================================================================

RESTRICTION_GROSS_SETTLEMENT: Final[str] = "BRUT_TAKAS"
RESTRICTION_NO_SHORT_SELL: Final[str] = "ACIGA_SATIS_YASAGI"
RESTRICTION_NO_MARGIN: Final[str] = "KREDILI_ISLEM_YASAGI"
RESTRICTION_ORDER_PACKAGE: Final[str] = "EMIR_PAKETI"
RESTRICTION_T0_CASH: Final[str] = "T0_NAKIT_TAKAS"
RESTRICTION_NO_DAY_TRADE: Final[str] = "GUN_ICI_AL_SAT_YASAGI"

DEFAULT_GROSS_SETTLEMENT_DB_PATH: Final[str] = "data/gross_settlement_audit.duckdb"
DEFAULT_MAX_QUERY_LIMIT: Final[int] = 100
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)

VALID_RESTRICTION_TYPES: Final[frozenset[str]] = frozenset(
    {
        RESTRICTION_GROSS_SETTLEMENT,
        RESTRICTION_NO_SHORT_SELL,
        RESTRICTION_NO_MARGIN,
        RESTRICTION_ORDER_PACKAGE,
        RESTRICTION_T0_CASH,
        RESTRICTION_NO_DAY_TRADE,
    }
)


# ==============================================================================
# Veri Modelleri
# ==============================================================================


@dataclass(slots=True)
class GrossSettlementStatus:
    """Hisse senedi brüt takas ve tedbir durumu.

    Attributes:
        is_gross: Hisse brüt takas kapsamında mı.
        effect: Uygulanan birincil etki kodu ("NO_SHORT_SELL_NO_MARGIN", "EXPIRED", "NONE" vb.).
        impact: Türkçe kısıtlama ve operasyonel etki açıklaması.
        ticker: Hisse sembolü (örn: "THYAO").
        start_date: Tedbir başlangıç tarihi (YYYY-MM-DD formatında).
        end_date: Tedbir bitiş tarihi (YYYY-MM-DD formatında).
        is_active: Belirtilen tarih itibarıyla tedbir aktif mi.
        restrictions: Aktif kısıtlamaların listesi.
        details: SPK/KAP gerekçe ve ek veri sözlüğü.
    """

    is_gross: bool
    effect: str = "NONE"
    impact: str = "Normal takas (T+2)"
    ticker: str = ""
    start_date: str | None = None
    end_date: str | None = None
    is_active: bool = True
    restrictions: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür."""
        return {
            "is_gross": bool(self.is_gross),
            "effect": self.effect,
            "impact": self.impact,
            "ticker": self.ticker,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "is_active": bool(self.is_active),
            "restrictions": list(self.restrictions),
            "details": dict(self.details),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt serileştirmesi."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        durum_str = "AKTİF" if self.is_active and self.is_gross else "NORMAL"
        return (
            f"GrossSettlementStatus(hisse='{self.ticker}', durum='{durum_str}', "
            f"etki='{self.effect}', kısıtlamalar={self.restrictions})"
        )


# ==============================================================================
# Gross Settlement Monitor Çekirdek Sınıfı
# ==============================================================================


class GrossSettlementMonitor:
    """BIST Brüt Takas ve VBTS Tedbir İzleyici.

    Pay Piyasası emir ve risk kontrollerinde hisselerin brüt takas, açığa satış ve
    kredili işlem kısıtlamalarını Point-In-Time (tarih duyarlı) olarak denetler.
    Thread-safe kilit korumasına, Polars vektörize taramasına ve DuckDB denetim izine sahiptir.
    """

    def __init__(self) -> None:
        """GrossSettlementMonitor başlatıcı."""
        self._lock = threading.RLock()
        self._gross_tickers: set[str] = set()
        self._gross_tickers_with_details: dict[str, dict[str, Any]] = {}

    def __enter__(self) -> GrossSettlementMonitor:
        """Context manager protokolü girişi."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager protokolü çıkışı."""
        self.clear()

    def clear(self) -> None:
        """Tüm kayıtlı brüt takas hisselerini ve detaylarını temizle."""
        with self._lock:
            self._gross_tickers.clear()
            self._gross_tickers_with_details.clear()
        logger.info("brut_takas_verileri_temizlendi")

    def reset(self) -> None:
        """clear() için takma ad."""
        self.clear()

    def _normalize_ticker(self, ticker: str | None) -> str:
        """Hisse sembolünü büyük harfe çevir ve temizle."""
        if not ticker or not isinstance(ticker, str):
            return ""
        return ticker.strip().upper()

    def _parse_date(self, target_date: str | date | datetime | None) -> date | None:
        """Tarih parametresini datetime.date nesnesine güvenle ayrıştır."""
        if target_date is None:
            return None
        if isinstance(target_date, datetime):
            return target_date.date()
        if isinstance(target_date, date):
            return target_date
        if isinstance(target_date, str):
            clean_str = target_date.strip()
            if not clean_str or clean_str.lower() in ("none", "null", "nan"):
                return None
            try:
                # ISO format: YYYY-MM-DD
                return datetime.strptime(clean_str[:10], "%Y-%m-%d").date()
            except ValueError:
                logger.warning("gecersiz_tarih_formati", tarih=clean_str)
                return None
        return None

    def _is_date_in_range(
        self,
        current_date: date | None,
        start_date: str | None,
        end_date: str | None,
    ) -> bool:
        """Belirtilen tarihin tedbir aralığında olup olmadığını doğrula."""
        if current_date is None:
            # Tarih belirtilmemişse anlık aktif kabul edilir
            return True

        start = self._parse_date(start_date)
        end = self._parse_date(end_date)

        # Ters tarih girilmişse sırala
        if start and end and start > end:
            start, end = end, start

        if start and current_date < start:
            return False
        if end and current_date > end:
            return False

        return True

    def set_gross_tickers(self, tickers: list[str]) -> None:
        """Brüt takaslı hisse listesini toplu güncelle.

        Args:
            tickers: Brüt takasa alınan hisse sembolleri listesi.
        """
        cleaned = {self._normalize_ticker(t) for t in tickers if t and self._normalize_ticker(t)}
        with self._lock:
            self._gross_tickers = cleaned
            # Detay sözlüğünde artık listede olmayanları temizle
            to_remove = [k for k in self._gross_tickers_with_details if k not in cleaned]
            for k in to_remove:
                self._gross_tickers_with_details.pop(k, None)

        logger.info("brut_takas_listesi_guncellendi", hisse_sayisi=len(cleaned))

    def set_gross_ticker_detail(self, ticker: str, details: dict[str, Any]) -> None:
        """Hisse için başlangıç/bitiş tarihi ve kısıtlama detaylarını tanımla.

        Args:
            ticker: Hisse sembolü.
            details: Tedbir detayları:
                - reason: SPK gerekçesi (örn: "VBTS Kapsamında")
                - start_date: "YYYY-MM-DD"
                - end_date: "YYYY-MM-DD"
                - day_trade_restricted: bool
                - restrictions: list[str]
        """
        sym = self._normalize_ticker(ticker)
        if not sym:
            return

        clean_details = dict(details)
        start_str = clean_details.get("start_date")
        end_str = clean_details.get("end_date")

        # Ters tarih kontrolü
        d_start = self._parse_date(start_str)
        d_end = self._parse_date(end_str)
        if d_start and d_end and d_start > d_end:
            logger.warning("brut_takas_ters_tarih_duzeltildi", hisse=sym, baslangic=start_str, bitis=end_str)
            clean_details["start_date"] = end_str
            clean_details["end_date"] = start_str

        with self._lock:
            self._gross_tickers.add(sym)
            self._gross_tickers_with_details[sym] = clean_details

        logger.info("brut_takas_detayi_eklendi", hisse=sym, detay=clean_details)

    def add_gross_settlement(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        reason: str = "VBTS",
        day_trade_restricted: bool = False,
    ) -> None:
        """Hisse için brüt takas tedbiri tanımlar."""
        self.set_gross_ticker_detail(
            ticker=ticker,
            details={
                "start_date": start_date,
                "end_date": end_date,
                "reason": reason,
                "day_trade_restricted": day_trade_restricted,
            },
        )

    def add_gross_ticker(self, ticker: str) -> None:
        """Tekil hisseyi brüt takas listesine ekle.

        Args:
            ticker: Hisse sembolü.
        """
        sym = self._normalize_ticker(ticker)
        if not sym:
            return
        with self._lock:
            self._gross_tickers.add(sym)

    def remove_gross_ticker(self, ticker: str) -> None:
        """Hisseyi brüt takas listesinden kaldır.

        Args:
            ticker: Hisse sembolü.
        """
        sym = self._normalize_ticker(ticker)
        if not sym:
            return
        with self._lock:
            self._gross_tickers.discard(sym)
            self._gross_tickers_with_details.pop(sym, None)
        logger.info("brut_takas_tedbiri_kaldirildi", hisse=sym)

    @otel_trace("gross_settlement.check_gross_settlement")
    def check_gross_settlement(
        self,
        ticker: str,
        current_date: str | date | datetime | None = None,
    ) -> GrossSettlementStatus:
        """Hissenin belirtilen tarih itibarıyla brüt takas durumunu denetle.

        Args:
            ticker: Hisse sembolü (örn: 'THYAO').
            current_date: Değerlendirme tarihi (Point-In-Time denetim için).

        Returns:
            GrossSettlementStatus: Tedbir detayları ve operasyonel kısıtlamalar.
        """
        sym = self._normalize_ticker(ticker)
        if not sym:
            return GrossSettlementStatus(
                is_gross=False,
                effect="NONE",
                impact="Geçersiz hisse kodu",
                ticker="",
                is_active=False,
            )

        eval_date = self._parse_date(current_date)

        with self._lock:
            if sym in self._gross_tickers:
                details = dict(self._gross_tickers_with_details.get(sym, {}))
                start_date = details.get("start_date")
                end_date = details.get("end_date")

                is_active = self._is_date_in_range(eval_date, start_date, end_date)

                if is_active:
                    day_trade_restricted = bool(details.get("day_trade_restricted", False))
                    restrictions = list(
                        details.get(
                            "restrictions",
                            [
                                RESTRICTION_GROSS_SETTLEMENT,
                                RESTRICTION_NO_SHORT_SELL,
                                RESTRICTION_NO_MARGIN,
                                RESTRICTION_T0_CASH,
                            ],
                        )
                    )
                    if day_trade_restricted and RESTRICTION_NO_DAY_TRADE not in restrictions:
                        restrictions.append(RESTRICTION_NO_DAY_TRADE)

                    day_trade_msg = ", gün içi al-sat kısıtlı" if day_trade_restricted else ""
                    impact_msg = (
                        f"{sym} brüt takasta — açığa satış yasak, kredili işlem yasak, T+0 nakit{day_trade_msg}"
                    )

                    return GrossSettlementStatus(
                        is_gross=True,
                        effect="NO_SHORT_SELL_NO_MARGIN",
                        impact=impact_msg,
                        ticker=sym,
                        start_date=start_date,
                        end_date=end_date,
                        is_active=True,
                        restrictions=restrictions,
                        details={"ticker": sym, **details},
                    )

                # Süresi dolmuş tedbir
                return GrossSettlementStatus(
                    is_gross=False,
                    effect="EXPIRED",
                    impact=f"{sym} brüt takas tedbir süresi sona erdi ({end_date})",
                    ticker=sym,
                    start_date=start_date,
                    end_date=end_date,
                    is_active=False,
                    restrictions=[],
                    details={"ticker": sym, **details},
                )

        return GrossSettlementStatus(
            is_gross=False,
            effect="NONE",
            impact="Normal takas (T+2)",
            ticker=sym,
            is_active=False,
        )

    def is_short_sell_blocked(
        self,
        ticker: str,
        current_date: str | date | datetime | None = None,
    ) -> bool:
        """Hisse brüt takas sebebiyle açığa satışa kapalı mı?

        Args:
            ticker: Hisse sembolü.
            current_date: Sorgu tarihi.

        Returns:
            bool: Açığa satış yasak ise True, serbest ise False.
        """
        status = self.check_gross_settlement(ticker, current_date=current_date)
        return status.is_gross and status.is_active

    def is_margin_blocked(
        self,
        ticker: str,
        current_date: str | date | datetime | None = None,
    ) -> bool:
        """Hisse brüt takas sebebiyle kredili alıma kapalı mı?

        Args:
            ticker: Hisse sembolü.
            current_date: Sorgu tarihi.

        Returns:
            bool: Kredili işlem yasak ise True, serbest ise False.
        """
        status = self.check_gross_settlement(ticker, current_date=current_date)
        return status.is_gross and status.is_active

    def is_day_trade_restricted(
        self,
        ticker: str,
        current_date: str | date | datetime | None = None,
    ) -> bool:
        """Hisse gün içi al-sat kısıtlamasına tabi mi?

        Args:
            ticker: Hisse sembolü.
            current_date: Sorgu tarihi.

        Returns:
            bool: Gün içi al-sat kısıtlı ise True, serbest ise False.
        """
        status = self.check_gross_settlement(ticker, current_date=current_date)
        if not (status.is_gross and status.is_active):
            return False
        return status.details.get("day_trade_restricted", False)

    def validate_order(
        self,
        ticker: str,
        side: str = "BUY",
        is_short: bool = False,
        is_credit: bool = False,
        is_day_trade: bool = False,
        current_date: str | date | datetime | None = None,
    ) -> tuple[bool, str]:
        """Emir gönderimi öncesinde SPK ve BIST brüt takas kurallarını doğrula.

        Args:
            ticker: Hisse sembolü.
            side: İşlem yönü ("BUY" veya "SELL").
            is_short: Açığa satış emri mi.
            is_credit: Kredili alım emri mi.
            is_day_trade: Gün içi al-sat emri mi.
            current_date: İşlem tarihi.

        Returns:
            tuple[bool, str]: (İşlem geçerli mi, Gerekçe/Açıklama).
        """
        status = self.check_gross_settlement(ticker, current_date=current_date)
        if not (status.is_gross and status.is_active):
            return True, "ONAYLANDI: Hisse normal takasa tabidir."

        if is_short or side.strip().upper() == "SHORT":
            return False, f"RED: {status.ticker} brüt takastadır. Açığa satış kesinlikle yapılamaz (SPK II-15.1)."

        if is_credit:
            return False, f"RED: {status.ticker} brüt takastadır. Kredili alım işlemine konu edilemez."

        if is_day_trade and status.details.get("day_trade_restricted", False):
            return False, f"RED: {status.ticker} için gün içi al-sat kısıtlaması yürürlüktedir."

        return True, f"ONAYLANDI: {status.ticker} brüt takasta işlem görebilir (T+0 tam nakit şartıyla)."

    def get_all_gross(self, current_date: str | date | datetime | None = None) -> list[str]:
        """Aktif tüm brüt takaslı hisselerin listesini getir.

        Args:
            current_date: Opsiyonel tarih filtresi.

        Returns:
            list[str]: Brüt takaslı hisse sembolleri listesi.
        """
        with self._lock:
            all_tickers = list(self._gross_tickers)

        if current_date is None:
            return sorted(all_tickers)

        return sorted([t for t in all_tickers if self.is_short_sell_blocked(t, current_date=current_date)])

    def filter_gross_tickers(
        self,
        tickers: list[str],
        current_date: str | date | datetime | None = None,
    ) -> list[str]:
        """Verilen hisse listesinden sadece brüt takaslı olanları filtrele.

        Args:
            tickers: İncelenecek hisse listesi.
            current_date: Sorgu tarihi.

        Returns:
            list[str]: Brüt takastaki hisseler.
        """
        return [t for t in tickers if self.is_short_sell_blocked(t, current_date=current_date)]

    def export_to_polars(self) -> pl.DataFrame:
        """Tüm kayıtlı brüt takas tedbirlerini Polars DataFrame'e aktar (GEMINI.md Kural 2).

        Returns:
            pl.DataFrame: Katı şemalı tedbir detayları veri çerçevesi.
        """
        schema: dict[str, pl.DataType] = {
            "ticker": pl.Utf8,
            "is_gross": pl.Boolean,
            "start_date": pl.Utf8,
            "end_date": pl.Utf8,
            "day_trade_restricted": pl.Boolean,
            "reason": pl.Utf8,
        }

        with self._lock:
            rows = []
            for sym in sorted(self._gross_tickers):
                details = self._gross_tickers_with_details.get(sym, {})
                rows.append(
                    {
                        "ticker": sym,
                        "is_gross": True,
                        "start_date": str(details.get("start_date") or ""),
                        "end_date": str(details.get("end_date") or ""),
                        "day_trade_restricted": bool(details.get("day_trade_restricted", False)),
                        "reason": str(details.get("reason", "VBTS")),
                    }
                )

        if not rows:
            return pl.DataFrame(schema=schema)

        return pl.DataFrame(rows, schema=schema)

    def check_polars(
        self,
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        date_col: str | None = None,
    ) -> pl.DataFrame:
        """Polars DataFrame üzerinde hisselere brüt takas bayrağı ekle (GEMINI.md Kural 2).

        Args:
            df: Giriş DataFrame'i.
            ticker_col: Hisse sembolü kolonu.
            date_col: Opsiyonel tarih kolonu.

        Returns:
            pl.DataFrame: 'is_gross_settlement' kolonu eklenmiş DataFrame.
        """
        if ticker_col not in df.columns:
            raise ValueError(f"'{ticker_col}' kolonu DataFrame içinde bulunamadı.")

        with self._lock:
            active_gross = set(self._gross_tickers)

        # Eğer tarih kolonu yoksa veya belirtilmemişse sabit küme sorgusu (null güvenli)
        if not date_col or date_col not in df.columns:
            is_gross_expr = (
                pl.col(ticker_col)
                .fill_null("")
                .str.to_uppercase()
                .is_in(active_gross)
                .alias("is_gross_settlement")
            )
            return df.with_columns(is_gross_expr)

        # Tarih duyarlı kontrol için Point-In-Time hesaplama (null ve tip güvenli)
        tickers_list = df[ticker_col].to_list()
        dates_list = df[date_col].to_list()

        flags: list[bool] = []
        for t, d in zip(tickers_list, dates_list, strict=False):
            if not t or str(t).lower() in ("none", "null", "nan"):
                flags.append(False)
                continue
            flags.append(self.is_short_sell_blocked(str(t), current_date=d))

        return df.with_columns(pl.Series("is_gross_settlement", flags, dtype=pl.Boolean))

    def export_to_duckdb(self, db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH) -> int:
        """Brüt takas tedbirlerini DuckDB tablosuna kalıcı olarak aktar (GEMINI.md Kural 5).

        Args:
            db_path: DuckDB veritabanı dosya yolu.

        Returns:
            int: Kaydedilen tedbir sayısı.
        """
        with self._lock:
            items = list(self._gross_tickers_with_details.items())
            simple_tickers = [t for t in self._gross_tickers if t not in self._gross_tickers_with_details]

        target_file = Path(db_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        rows = []
        for sym, det in items:
            rows.append(
                (
                    uuid.uuid4().hex,
                    sym,
                    det.get("start_date"),
                    det.get("end_date"),
                    bool(det.get("day_trade_restricted", False)),
                    det.get("reason", "VBTS"),
                    orjson.dumps(det, default=str).decode("utf-8"),
                )
            )

        for sym in simple_tickers:
            rows.append(
                (
                    uuid.uuid4().hex,
                    sym,
                    None,
                    None,
                    False,
                    "GENEL_BRUT_TAKAS",
                    "{}",
                )
            )

        if not rows:
            return 0

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gross_settlement_audit (
                        id VARCHAR PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        ticker VARCHAR,
                        start_date VARCHAR,
                        end_date VARCHAR,
                        day_trade_restricted BOOLEAN,
                        reason VARCHAR,
                        details_json VARCHAR
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO gross_settlement_audit (
                        id, ticker, start_date, end_date, day_trade_restricted, reason, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

        logger.info("brut_takas_kayitlari_duckdb_aktarildi", adet=len(rows), yol=db_path)
        return len(rows)

    def query_audit_duckdb(
        self,
        db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH,
        ticker: str | None = None,
        limit: int = DEFAULT_MAX_QUERY_LIMIT,
    ) -> pl.DataFrame:
        """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak sorgula (GEMINI.md Kural 2 & 5).

        Args:
            db_path: DuckDB dosya yolu.
            ticker: Opsiyonel hisse filtresi.
            limit: Maksimum satır limiti.

        Returns:
            pl.DataFrame: Sıfır kopyalı filtreli Polars DataFrame.
        """
        target_file = Path(db_path)
        safe_limit = max(1, int(limit))

        schema: dict[str, pl.DataType] = {
            "id": pl.Utf8,
            "created_at": pl.Datetime,
            "ticker": pl.Utf8,
            "start_date": pl.Utf8,
            "end_date": pl.Utf8,
            "day_trade_restricted": pl.Boolean,
            "reason": pl.Utf8,
            "details_json": pl.Utf8,
        }

        if not target_file.exists():
            return pl.DataFrame(schema=schema)

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                configure_duckdb_wal(conn)
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name = 'gross_settlement_audit'"
                ).fetchall()
                if not tables:
                    return pl.DataFrame(schema=schema)

                query = "SELECT * FROM gross_settlement_audit WHERE 1=1"
                params: list[Any] = []

                if ticker:
                    query += " AND ticker = ?"
                    params.append(self._normalize_ticker(ticker))

                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(safe_limit)

                return conn.execute(query, params).pl()

    def load_from_duckdb(
        self,
        db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH,
        current_date: str | date | datetime | None = None,
    ) -> int:
        """DuckDB denetim tablosundaki güncel tedbirleri bellek durumuna geri yükle.

        Args:
            db_path: DuckDB dosya yolu.
            current_date: Opsiyonel değerlendirme tarihi (Point-In-Time).

        Returns:
            int: Yüklenen aktif tedbir sayısı.
        """
        target_file = Path(db_path)
        if not target_file.exists():
            return 0

        eval_date = self._parse_date(current_date)

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                configure_duckdb_wal(conn)
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name = 'gross_settlement_audit'"
                ).fetchall()
                if not tables:
                    return 0

                rows = conn.execute(
                    """
                    SELECT ticker, start_date, end_date, day_trade_restricted, reason, details_json
                    FROM gross_settlement_audit
                    ORDER BY created_at ASC
                    """
                ).fetchall()

            loaded_count = 0
            for sym, s_date, e_date, dt_restr, reason, d_json in rows:
                if not sym:
                    continue
                sym = self._normalize_ticker(sym)
                is_active = self._is_date_in_range(eval_date, s_date, e_date)
                if is_active:
                    try:
                        extra_det = orjson.loads(d_json) if d_json else {}
                    except Exception:
                        extra_det = {}

                    extra_det.update(
                        {
                            "start_date": s_date,
                            "end_date": e_date,
                            "day_trade_restricted": bool(dt_restr),
                            "reason": reason,
                        }
                    )
                    self._gross_tickers.add(sym)
                    self._gross_tickers_with_details[sym] = extra_det
                    loaded_count += 1

            logger.info("brut_takas_duckdbden_yuklendi", yuklenen_adet=loaded_count, yol=db_path)
            return loaded_count

    def to_dict(self) -> dict[str, Any]:
        """İzleyici durumunu sözlük olarak döner."""
        with self._lock:
            return {
                "gross_tickers_count": len(self._gross_tickers),
                "detailed_records_count": len(self._gross_tickers_with_details),
                "gross_tickers": sorted(self._gross_tickers),
            }

    def to_orjson_bytes(self) -> bytes:
        """İzleyici durumunu ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def clear_audit_duckdb(self, db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH) -> None:
        """DuckDB brüt takas denetim tablosunu sıfırlar."""
        clear_gross_settlement_audit_duckdb(db_path=db_path)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return (
                f"GrossSettlementMonitor(brut_takasli_hisse_sayisi={len(self._gross_tickers)}, "
                f"detayli_kayitlar={len(self._gross_tickers_with_details)})"
            )


# ==============================================================================
# Global Singleton ve Modül Seviyesi Kolaylık Fonksiyonları
# ==============================================================================

gross_settlement_monitor: GrossSettlementMonitor = GrossSettlementMonitor()


def get_gross_settlement_monitor() -> GrossSettlementMonitor:
    """GrossSettlementMonitor singleton nesnesini döndürür."""
    return gross_settlement_monitor


def check_stock_gross_settlement(
    ticker: str,
    current_date: str | date | datetime | None = None,
) -> GrossSettlementStatus:
    """Hissenin brüt takas ve kısıtlama durumunu denetler."""
    return gross_settlement_monitor.check_gross_settlement(ticker=ticker, current_date=current_date)


def is_stock_short_sell_blocked(
    ticker: str,
    current_date: str | date | datetime | None = None,
) -> bool:
    """Hissenin açığa satışa kapalı olup olmadığını döndürür."""
    return gross_settlement_monitor.is_short_sell_blocked(ticker=ticker, current_date=current_date)


def is_stock_margin_blocked(
    ticker: str,
    current_date: str | date | datetime | None = None,
) -> bool:
    """Hissenin kredili alıma kapalı olup olmadığını döndürür."""
    return gross_settlement_monitor.is_margin_blocked(ticker=ticker, current_date=current_date)


def is_stock_day_trade_restricted(
    ticker: str,
    current_date: str | date | datetime | None = None,
) -> bool:
    """Hissenin gün içi al-sat kısıtlamasına tabi olup olmadığını döndürür."""
    return gross_settlement_monitor.is_day_trade_restricted(ticker=ticker, current_date=current_date)


def validate_stock_order(
    ticker: str,
    side: str = "BUY",
    is_short: bool = False,
    is_credit: bool = False,
    is_day_trade: bool = False,
    current_date: str | date | datetime | None = None,
) -> tuple[bool, str]:
    """Emir öncesi brüt takas ve açığa satış kurallarını denetler."""
    return gross_settlement_monitor.validate_order(
        ticker=ticker,
        side=side,
        is_short=is_short,
        is_credit=is_credit,
        is_day_trade=is_day_trade,
        current_date=current_date,
    )


def get_all_gross_settlement_stocks(
    current_date: str | date | datetime | None = None,
) -> list[str]:
    """Aktif tüm brüt takaslı hisse kodlarını döndürür."""
    return gross_settlement_monitor.get_all_gross(current_date=current_date)


def filter_gross_settlement_stocks(
    tickers: list[str],
    current_date: str | date | datetime | None = None,
) -> list[str]:
    """Verilen listeden sadece brüt takaslı olan hisseleri filtreler."""
    return gross_settlement_monitor.filter_gross_tickers(tickers=tickers, current_date=current_date)


def export_gross_settlement_to_polars() -> pl.DataFrame:
    """Brüt takas listesini Polars DataFrame olarak döndürür."""
    return gross_settlement_monitor.export_to_polars()


def check_polars_gross_settlement(
    df: pl.DataFrame,
    ticker_col: str = "ticker",
    date_col: str | None = None,
) -> pl.DataFrame:
    """Polars DataFrame üzerinde hisselere brüt takas bayrağı ekler."""
    return gross_settlement_monitor.check_polars(df=df, ticker_col=ticker_col, date_col=date_col)


def export_gross_settlement_to_duckdb(
    db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH,
) -> int:
    """Brüt takas kayıtlarını DuckDB tablosuna aktarır."""
    return gross_settlement_monitor.export_to_duckdb(db_path=db_path)


def query_gross_settlement_audit_duckdb(
    db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH,
    ticker: str | None = None,
    limit: int = DEFAULT_MAX_QUERY_LIMIT,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu Polars DataFrame olarak sorgular."""
    return gross_settlement_monitor.query_audit_duckdb(db_path=db_path, ticker=ticker, limit=limit)


def load_gross_settlement_from_duckdb(
    db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH,
    current_date: str | date | datetime | None = None,
) -> int:
    """DuckDB denetim tablosundan brüt takas durumunu belleğe yükler."""
    return gross_settlement_monitor.load_from_duckdb(db_path=db_path, current_date=current_date)


def read_gross_settlement_audit_from_duckdb(
    db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH,
    ticker: str | None = None,
    limit: int = DEFAULT_MAX_QUERY_LIMIT,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        ticker: İsteğe bağlı hisse kodu filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Okunan denetim kayıtları.
    """
    path_obj = Path(db_path)
    schema: dict[str, pl.DataType] = {
        "id": pl.Utf8,
        "created_at": pl.Datetime,
        "ticker": pl.Utf8,
        "start_date": pl.Utf8,
        "end_date": pl.Utf8,
        "day_trade_restricted": pl.Boolean,
        "reason": pl.Utf8,
        "details_json": pl.Utf8,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'gross_settlement_audit'"
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = "SELECT * FROM gross_settlement_audit WHERE 1=1"
            params: list[Any] = []

            if ticker:
                query += " AND ticker = ?"
                params.append(ticker.upper().strip())

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(max(1, int(limit)))

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_gross_settlement_audit_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_gross_settlement_audit_duckdb(db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH) -> None:
    """DuckDB'deki brüt takas denetim tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS gross_settlement_audit;")
    except Exception as exc:
        logger.error("duckdb_gross_settlement_audit_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__: Final[list[str]] = [
    # Sabitler
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_GROSS_SETTLEMENT_DB_PATH",
    "DEFAULT_MAX_QUERY_LIMIT",
    "DEFAULT_WAL_SIZE",
    "RESTRICTION_GROSS_SETTLEMENT",
    "RESTRICTION_NO_DAY_TRADE",
    "RESTRICTION_NO_MARGIN",
    "RESTRICTION_NO_SHORT_SELL",
    "RESTRICTION_ORDER_PACKAGE",
    "RESTRICTION_T0_CASH",
    "VALID_RESTRICTION_TYPES",
    # Modeller ve Çekirdek Sınıf
    "GrossSettlementMonitor",
    "GrossSettlementStatus",
    # Singleton
    "gross_settlement_monitor",
    # Modül Seviyesi Kolaylık Fonksiyonları
    "check_polars_gross_settlement",
    "check_stock_gross_settlement",
    "clear_gross_settlement_audit_duckdb",
    "configure_duckdb_wal",
    "export_gross_settlement_to_duckdb",
    "export_gross_settlement_to_polars",
    "filter_gross_settlement_stocks",
    "get_all_gross_settlement_stocks",
    "get_gross_settlement_monitor",
    "is_stock_day_trade_restricted",
    "is_stock_margin_blocked",
    "is_stock_short_sell_blocked",
    "load_gross_settlement_from_duckdb",
    "query_gross_settlement_audit_duckdb",
    "read_gross_settlement_audit_from_duckdb",
    "to_orjson_bytes",
    "validate_stock_order",
]
