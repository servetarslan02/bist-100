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
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# ==============================================================================
# Standart Tedbir ve Yapılandırma Sabitleri
# ==============================================================================

RESTRICTION_GROSS_SETTLEMENT: str = "BRUT_TAKAS"
RESTRICTION_NO_SHORT_SELL: str = "ACIGA_SATIS_YASAGI"
RESTRICTION_NO_MARGIN: str = "KREDILI_ISLEM_YASAGI"
RESTRICTION_ORDER_PACKAGE: str = "EMIR_PAKETI"
RESTRICTION_T0_CASH: str = "T0_NAKIT_TAKAS"
RESTRICTION_NO_DAY_TRADE: str = "GUN_ICI_AL_SAT_YASAGI"

DEFAULT_GROSS_SETTLEMENT_DB_PATH: str = "data/gross_settlement_audit.duckdb"

VALID_RESTRICTION_TYPES: frozenset[str] = frozenset(
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
        effect: Uygulanan birincil etki kodu ("NO_SHORT_SELL_NO_MARGIN", "NONE" vb.).
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
            "is_gross": self.is_gross,
            "effect": self.effect,
            "impact": self.impact,
            "ticker": self.ticker,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "is_active": self.is_active,
            "restrictions": list(self.restrictions),
            "details": dict(self.details),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt serileştirmesi."""
        return orjson.dumps(self.to_dict())

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

    def _normalize_ticker(self, ticker: str) -> str:
        """Hisse sembolünü büyük harfe çevir ve temizle."""
        if not ticker or not isinstance(ticker, str):
            return ""
        return ticker.strip().upper()

    def _parse_date(self, target_date: str | date | datetime | None) -> date | None:
        """Tarih parametresini datetime.date nesnesine ayrıştır."""
        if target_date is None:
            return None
        if isinstance(target_date, datetime):
            return target_date.date()
        if isinstance(target_date, date):
            return target_date
        if isinstance(target_date, str):
            try:
                # ISO format: YYYY-MM-DD
                clean_str = target_date.strip()[:10]
                return datetime.strptime(clean_str, "%Y-%m-%d").date()
            except ValueError:
                logger.warning("gecersiz_tarih_formati", tarih=target_date)
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
        cleaned = {self._normalize_ticker(t) for t in tickers if t}
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

        with self._lock:
            self._gross_tickers.add(sym)
            self._gross_tickers_with_details[sym] = dict(details)

        logger.info("brut_takas_detayi_eklendi", hisse=sym, detay=details)

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
                    day_trade_restricted = details.get("day_trade_restricted", False)
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
        """Tüm kayıtlı brüt takas tedbirlerini Polars DataFrame'e aktar.

        Returns:
            pl.DataFrame: Tedbir detaylarını içeren veri çerçevesi.
        """
        with self._lock:
            rows = []
            for sym in sorted(self._gross_tickers):
                details = self._gross_tickers_with_details.get(sym, {})
                rows.append(
                    {
                        "ticker": sym,
                        "is_gross": True,
                        "start_date": str(details.get("start_date", "")),
                        "end_date": str(details.get("end_date", "")),
                        "day_trade_restricted": bool(details.get("day_trade_restricted", False)),
                        "reason": str(details.get("reason", "VBTS")),
                    }
                )

        if not rows:
            return pl.DataFrame(
                schema={
                    "ticker": pl.Utf8,
                    "is_gross": pl.Boolean,
                    "start_date": pl.Utf8,
                    "end_date": pl.Utf8,
                    "day_trade_restricted": pl.Boolean,
                    "reason": pl.Utf8,
                }
            )

        return pl.DataFrame(rows)

    def check_polars(
        self,
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        date_col: str | None = None,
    ) -> pl.DataFrame:
        """Polars DataFrame üzerinde hisselere brüt takas bayrağı ekle.

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

        # Eğer tarih kolonu yoksa sabit küme sorgusu
        if not date_col or date_col not in df.columns:
            is_gross_expr = pl.col(ticker_col).str.to_uppercase().is_in(active_gross).alias("is_gross_settlement")
            return df.with_columns(is_gross_expr)

        # Tarih duyarlı kontrol için seri bazlı Point-In-Time hesaplama
        tickers_list = df[ticker_col].to_list()
        dates_list = df[date_col].to_list()
        flags = [
            self.is_short_sell_blocked(str(t), current_date=str(d))
            for t, d in zip(tickers_list, dates_list, strict=False)
        ]

        return df.with_columns(pl.Series("is_gross_settlement", flags, dtype=pl.Boolean))

    def export_to_duckdb(self, db_path: str = DEFAULT_GROSS_SETTLEMENT_DB_PATH) -> int:
        """Brüt takas tedbirlerini DuckDB tablosuna kalıcı olarak aktar.

        Args:
            db_path: DuckDB veritabanı dosya yolu.

        Returns:
            int: Kaydedilen tedbir sayısı.

        Raises:
            Exception: DuckDB bağlantı veya kayıt hatası durumunda.
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
                    orjson.dumps(det).decode("utf-8"),
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

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return (
                f"GrossSettlementMonitor(brut_takasli_hisse_sayisi={len(self._gross_tickers)}, "
                f"detayli_kayitlar={len(self._gross_tickers_with_details)})"
            )


# ==============================================================================
# Global Singleton ve Dışa Aktarımlar
# ==============================================================================

gross_settlement_monitor: GrossSettlementMonitor = GrossSettlementMonitor()

__all__: list[str] = [
    "DEFAULT_GROSS_SETTLEMENT_DB_PATH",
    "RESTRICTION_GROSS_SETTLEMENT",
    "RESTRICTION_NO_DAY_TRADE",
    "RESTRICTION_NO_MARGIN",
    "RESTRICTION_NO_SHORT_SELL",
    "RESTRICTION_ORDER_PACKAGE",
    "RESTRICTION_T0_CASH",
    "VALID_RESTRICTION_TYPES",
    "GrossSettlementMonitor",
    "GrossSettlementStatus",
    "gross_settlement_monitor",
]
