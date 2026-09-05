"""ALPHA BIST — Şirket ve Pay Bazlı İşlem Durdurma İzleme Motoru (Halt Monitor).

Bu modül, Borsa İstanbul Pay Piyasası'nda işlem gören hisse senetlerine şirket özel durumları,
KAP açıklamaları, Olağanüstü Genel Kurul, bedelsiz/bedelli sermaye artırımları, birleşme/devralma,
SPK geçici işlem yasakları ve devre kesici kaynaklı işlem durdurma (trading halt) kararlarını
izler, emir ve risk motorlarına anlık ve Point-In-Time (zaman duyarlı) bildirim sağlar.

Temel Özellikler:
- Şirket bazlı seans durdurma ve yeniden başlama zamanı takibi.
- Point-In-Time zaman aşımı kontrolü (beklenen başlama zamanı geçen hisselerin otomatik serbest bırakılması).
- Korumalı emir iptali ve yeni emir reddi sinyalleri ("CANCEL_ORDERS", "REJECT_NEW", "WAIT").
- DuckDB tabanlı kalıcı durum yönetimi (StateStore entegrasyonu, sıfır veri kaybı).
- Polars DataFrame vektörize hisse tarama ve DuckDB denetim kaydı.
- Thread-safe reentrant kilit (`threading.RLock`) mimarisi.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace
from services.core.state_store import state_store

logger = structlog.get_logger(__name__)

# ==============================================================================
# Standart Durdurma Türleri ve Eylem Sabitleri
# ==============================================================================

HALT_TYPE_KAP: str = "KAP"
HALT_TYPE_CIRCUIT_BREAKER: str = "CIRCUIT_BREAKER"
HALT_TYPE_CORPORATE: str = "CORPORATE"
HALT_TYPE_SPK: str = "SPK"
HALT_TYPE_VOLATILITY: str = "VOLATILITY"

ACTION_WAIT: str = "WAIT"
ACTION_CANCEL_ORDERS: str = "CANCEL_ORDERS"
ACTION_REJECT_NEW: str = "REJECT_NEW"
ACTION_NO_ACTION: str = "NO_ACTION"

DEFAULT_HALT_DB_PATH: str = "data/halt_audit.duckdb"

VALID_HALT_TYPES: frozenset[str] = frozenset(
    {
        HALT_TYPE_KAP,
        HALT_TYPE_CIRCUIT_BREAKER,
        HALT_TYPE_CORPORATE,
        HALT_TYPE_SPK,
        HALT_TYPE_VOLATILITY,
    }
)

VALID_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_WAIT,
        ACTION_CANCEL_ORDERS,
        ACTION_REJECT_NEW,
        ACTION_NO_ACTION,
    }
)


# ==============================================================================
# Veri Modelleri
# ==============================================================================


@dataclass(slots=True)
class HaltStatus:
    """Hisse senedi işlem durdurma durumu.

    Attributes:
        halted: İşlem durdurulmuş mu.
        ticker: Hisse sembolü (örn: "THYAO").
        reason: Durdurma gerekçesi (örn: "Özel Durum Açıklaması Beklentisi").
        halt_type: Durdurma sınıfı ("KAP", "CIRCUIT_BREAKER", "CORPORATE", "SPK", "VOLATILITY").
        expected_resume: Beklenen yeniden açılış zamanı (ISO 8601 UTC).
        action: Emir iletim motorunun alması gereken aksiyon ("WAIT", "CANCEL_ORDERS", "REJECT_NEW", "NO_ACTION").
        halted_at: Durdurulma zaman damgası (ISO 8601 UTC).
        is_active: Durdurma kararı sorgu zamanı itibarıyla aktif mi.
        details: Ek KAP/BIST meta verileri.
    """

    halted: bool
    ticker: str = ""
    reason: str = ""
    halt_type: str = HALT_TYPE_KAP
    expected_resume: str | None = None
    action: str = ACTION_WAIT
    halted_at: str | None = None
    is_active: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür."""
        return {
            "halted": self.halted,
            "ticker": self.ticker,
            "reason": self.reason,
            "halt_type": self.halt_type,
            "expected_resume": self.expected_resume,
            "action": self.action,
            "halted_at": self.halted_at,
            "is_active": self.is_active,
            "details": dict(self.details),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        durum_str = "DURDURULDU" if self.halted and self.is_active else "SERBEST"
        return (
            f"HaltStatus(hisse='{self.ticker}', durum='{durum_str}', "
            f"tur='{self.halt_type}', aksiyon='{self.action}', neden='{self.reason}')"
        )


# ==============================================================================
# Halt Monitor Çekirdek Sınıfı
# ==============================================================================


class HaltMonitor:
    """Şirket ve Pay Bazlı Durdurma İzleyici (Halt Monitor).

    BIST Pay Piyasası seans akışında hisselerin durdurulma durumlarını takip eder,
    DuckDB (state_store) üzerinden kalıcı kayıt tutar ve Point-In-Time zaman denetimi sağlar.
    """

    def __init__(self) -> None:
        """HaltMonitor başlatıcı."""
        self._lock = threading.RLock()
        self._halted_tickers: dict[str, HaltStatus] = {}
        self._restore_state()

    def _normalize_ticker(self, ticker: str) -> str:
        """Hisse sembolünü büyük harfe çevir ve temizle."""
        if not ticker or not isinstance(ticker, str):
            return ""
        return ticker.strip().upper()

    def _parse_datetime(self, time_val: str | datetime | None) -> datetime | None:
        """Tarih-saat parametresini UTC aware datetime nesnesine ayrıştır."""
        if time_val is None:
            return None
        if isinstance(time_val, datetime):
            return time_val if time_val.tzinfo else time_val.replace(tzinfo=UTC)
        if isinstance(time_val, str):
            try:
                # ISO 8601 ayrıştırma
                clean_str = time_val.strip().replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_str)
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except ValueError:
                logger.warning("gecersiz_zaman_formati", deger=time_val)
                return None
        return None

    @otel_trace("halt_monitor.add_halt")
    def add_halt(
        self,
        ticker: str,
        reason: str,
        halt_type: str = HALT_TYPE_KAP,
        expected_resume: str | datetime | None = None,
        action: str = ACTION_WAIT,
        details: dict[str, Any] | None = None,
    ) -> HaltStatus:
        """Hisse için işlem durdurma durumu ekle.

        Args:
            ticker: Hisse sembolü (örn: 'THYAO').
            reason: Durdurma gerekçesi.
            halt_type: Durdurma türü ("KAP", "CIRCUIT_BREAKER", "CORPORATE", "SPK", "VOLATILITY").
            expected_resume: Beklenen seans başlama zamanı.
            action: Tavsiye edilen eylem ("WAIT", "CANCEL_ORDERS", "REJECT_NEW").
            details: Ek veri sözlüğü.

        Returns:
            HaltStatus: Oluşturulan durdurma kaydı.
        """
        sym = self._normalize_ticker(ticker)
        if not sym:
            raise ValueError("Geçersiz veya boş hisse kodu.")

        ht = halt_type if halt_type in VALID_HALT_TYPES else HALT_TYPE_KAP
        act = action if action in VALID_ACTIONS else ACTION_WAIT
        resume_str = (
            expected_resume.isoformat() if isinstance(expected_resume, datetime) else expected_resume
        )
        now_iso = datetime.now(UTC).isoformat()

        status = HaltStatus(
            halted=True,
            ticker=sym,
            reason=reason,
            halt_type=ht,
            expected_resume=resume_str,
            action=act,
            halted_at=now_iso,
            is_active=True,
            details=details or {},
        )

        with self._lock:
            self._halted_tickers[sym] = status

        self._persist_state(sym)
        logger.info("hisse_durduruldu", hisse=sym, neden=reason, tur=ht, aksiyon=act)
        return status

    @otel_trace("halt_monitor.remove_halt")
    def remove_halt(self, ticker: str) -> bool:
        """Hisse durdurma durumunu kaldır ve seansı serbest bırak.

        Args:
            ticker: Hisse sembolü.

        Returns:
            bool: Durdurma kaydı mevcut olup başarıyla kaldırıldıysa True.
        """
        sym = self._normalize_ticker(ticker)
        if not sym:
            return False

        with self._lock:
            if sym in self._halted_tickers:
                del self._halted_tickers[sym]
                removed = True
            else:
                removed = False

        if removed:
            self._remove_persisted(sym)
            logger.info("hisse_durdurma_kaldirildi", hisse=sym)
        return removed

    @otel_trace("halt_monitor.check_halt")
    def check_halt(
        self,
        ticker: str,
        current_time: str | datetime | None = None,
    ) -> HaltStatus:
        """Hissenin durdurulma durumunu kontrol et (Point-In-Time duyarlı).

        Eğer hisse için beklenen başlama zamanı (`expected_resume`) tanımlanmışsa
        ve sorgu zamanı bu süreyi geçmişse, hisse otomatik serbest kabul edilir.

        Args:
            ticker: Hisse sembolü.
            current_time: Sorgu zamanı (None ise anlık UTC zamanı kullanılır).

        Returns:
            HaltStatus: Durdurma durumu ve geçerlilik bilgisi.
        """
        sym = self._normalize_ticker(ticker)
        if not sym:
            return HaltStatus(halted=False, action=ACTION_NO_ACTION, is_active=False)

        eval_dt = self._parse_datetime(current_time) or datetime.now(UTC)

        with self._lock:
            status = self._halted_tickers.get(sym)
            if not status:
                return HaltStatus(
                    halted=False,
                    ticker=sym,
                    action=ACTION_NO_ACTION,
                    is_active=False,
                )

            # Beklenen yeniden başlama zaman aşımı kontrolü (Auto-Resume / Auto-Expiration)
            if status.expected_resume:
                resume_dt = self._parse_datetime(status.expected_resume)
                if resume_dt and eval_dt >= resume_dt:
                    return HaltStatus(
                        halted=False,
                        ticker=sym,
                        reason=f"Beklenen başlama süresi doldu ({status.expected_resume})",
                        halt_type=status.halt_type,
                        expected_resume=status.expected_resume,
                        action=ACTION_NO_ACTION,
                        halted_at=status.halted_at,
                        is_active=False,
                        details=status.details,
                    )

            return status

    def is_halted(
        self,
        ticker: str,
        current_time: str | datetime | None = None,
    ) -> bool:
        """Hisse durdurulmuş ve an itibarıyla kilitli mi?

        Args:
            ticker: Hisse sembolü.
            current_time: Sorgu zamanı.

        Returns:
            bool: Durdurulmuş ve aktif ise True, işlem görebilir durumda ise False.
        """
        status = self.check_halt(ticker, current_time=current_time)
        return status.halted and status.is_active

    def get_all_halted(
        self,
        current_time: str | datetime | None = None,
    ) -> dict[str, HaltStatus]:
        """Tüm aktif durdurulan hisseleri ve durumlarını getir.

        Args:
            current_time: Opsiyonel sorgu zamanı.

        Returns:
            dict[str, HaltStatus]: {ticker: HaltStatus} haritası.
        """
        eval_dt = self._parse_datetime(current_time)
        with self._lock:
            items = list(self._halted_tickers.items())

        active_map: dict[str, HaltStatus] = {}
        for sym, st in items:
            checked = self.check_halt(sym, current_time=eval_dt)
            if checked.halted and checked.is_active:
                active_map[sym] = checked
        return active_map

    def get_halted_tickers(
        self,
        current_time: str | datetime | None = None,
    ) -> list[str]:
        """Aktif durdurulmuş hisse sembolleri listesini getir.

        Args:
            current_time: Opsiyonel sorgu zamanı.

        Returns:
            list[str]: Durdurulmuş hisse sembolleri listesi.
        """
        return sorted(list(self.get_all_halted(current_time=current_time).keys()))

    def filter_halted_tickers(
        self,
        tickers: list[str],
        current_time: str | datetime | None = None,
    ) -> list[str]:
        """Verilen hisse listesinden yalnızca durdurulmuş olanları filtrele.

        Args:
            tickers: İncelenecek hisse listesi.
            current_time: Sorgu zamanı.

        Returns:
            list[str]: Durdurulan hisseler.
        """
        return [t for t in tickers if self.is_halted(t, current_time=current_time)]

    # ==========================================================================
    # POLARS VE DUCKDB ENTEGRASYONU
    # ==========================================================================

    def export_to_polars(self, current_time: str | datetime | None = None) -> pl.DataFrame:
        """Durdurulan hisseleri Polars DataFrame olarak dışa aktar.

        Args:
            current_time: Opsiyonel Point-In-Time sorgu zamanı.

        Returns:
            pl.DataFrame: Durdurma detaylarını içeren tablo.
        """
        active_halted = self.get_all_halted(current_time=current_time)
        if not active_halted:
            return pl.DataFrame(
                schema={
                    "ticker": pl.Utf8,
                    "halted": pl.Boolean,
                    "reason": pl.Utf8,
                    "halt_type": pl.Utf8,
                    "expected_resume": pl.Utf8,
                    "action": pl.Utf8,
                    "halted_at": pl.Utf8,
                }
            )

        rows = []
        for s in active_halted.values():
            rows.append(
                {
                    "ticker": s.ticker,
                    "halted": s.halted,
                    "reason": s.reason,
                    "halt_type": s.halt_type,
                    "expected_resume": str(s.expected_resume or ""),
                    "action": s.action,
                    "halted_at": str(s.halted_at or ""),
                }
            )
        return pl.DataFrame(rows)

    def check_polars(
        self,
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        time_col: str | None = None,
    ) -> pl.DataFrame:
        """Polars DataFrame üzerinde hisselere 'is_halted' ve 'halt_action' kolonları ekle.

        Args:
            df: İşlem veya piyasa verilerini içeren DataFrame.
            ticker_col: Hisse sembolü kolonu.
            time_col: Opsiyonel zaman damgası kolonu.

        Returns:
            pl.DataFrame: Durdurma bayrakları eklenmiş DataFrame.
        """
        if ticker_col not in df.columns:
            raise ValueError(f"'{ticker_col}' kolonu DataFrame içinde bulunamadı.")

        with self._lock:
            active_set = set(self.get_halted_tickers())

        if not time_col or time_col not in df.columns:
            halted_expr = pl.col(ticker_col).str.to_uppercase().is_in(active_set).alias("is_halted")
            return df.with_columns(halted_expr)

        tickers_list = df[ticker_col].to_list()
        times_list = df[time_col].to_list()
        flags = [
            self.is_halted(str(t), current_time=str(tm))
            for t, tm in zip(tickers_list, times_list, strict=False)
        ]
        return df.with_columns(pl.Series("is_halted", flags, dtype=pl.Boolean))

    def export_to_duckdb(self, db_path: str = DEFAULT_HALT_DB_PATH) -> int:
        """Durdurma geçmişini kalıcı denetim için DuckDB tablosuna aktar.

        Args:
            db_path: DuckDB veritabanı dosya yolu.

        Returns:
            int: Kaydedilen satır sayısı.
        """
        with self._lock:
            statuses = list(self._halted_tickers.values())

        if not statuses:
            return 0

        target_file = Path(db_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        rows = []
        for s in statuses:
            rows.append(
                (
                    uuid.uuid4().hex,
                    s.ticker,
                    s.reason,
                    s.halt_type,
                    s.expected_resume,
                    s.action,
                    s.halted_at,
                    orjson.dumps(s.to_dict()).decode("utf-8"),
                )
            )

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS halt_audit_log (
                        id VARCHAR PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        ticker VARCHAR,
                        reason VARCHAR,
                        halt_type VARCHAR,
                        expected_resume VARCHAR,
                        action VARCHAR,
                        halted_at VARCHAR,
                        details_json VARCHAR
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO halt_audit_log (
                        id, ticker, reason, halt_type, expected_resume, action, halted_at, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

        logger.info("durdurma_kayitlari_duckdb_aktarildi", adet=len(rows), yol=db_path)
        return len(rows)

    # ==========================================================================
    # DUCKDB KALICI DURUM YÖNETİMİ (STATE_STORE ENTEGRASYONU)
    # ==========================================================================

    def _persist_state(self, ticker: str) -> None:
        """Halt durumunu DuckDB tablosuna atomik kaydet.

        Args:
            ticker: Durdurulan hisse sembolü.

        Returns:
            None
        """
        try:
            with self._lock:
                status = self._halted_tickers.get(ticker)
            if not status:
                return

            with state_store._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS halt_states (
                        ticker VARCHAR PRIMARY KEY,
                        reason VARCHAR,
                        halt_type VARCHAR,
                        expected_resume VARCHAR,
                        action VARCHAR,
                        details_json VARCHAR,
                        updated_at VARCHAR
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO halt_states (ticker, reason, halt_type, expected_resume, action, details_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (ticker) DO UPDATE SET
                        reason = EXCLUDED.reason,
                        halt_type = EXCLUDED.halt_type,
                        expected_resume = EXCLUDED.expected_resume,
                        action = EXCLUDED.action,
                        details_json = EXCLUDED.details_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        ticker,
                        status.reason,
                        status.halt_type,
                        status.expected_resume,
                        status.action,
                        orjson.dumps(status.details).decode("utf-8"),
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except Exception as e:
            logger.warning("halt_durumu_duckdb_kaydi_atlanildi", hisse=ticker, hata=str(e))

    def _remove_persisted(self, ticker: str) -> None:
        """Halt durumunu DuckDB tablosundan sil.

        Args:
            ticker: Durdurması kaldırılan hisse sembolü.

        Returns:
            None
        """
        try:
            with state_store._connect() as conn:
                conn.execute("DELETE FROM halt_states WHERE ticker = ?", (ticker,))
        except Exception as e:
            logger.warning("halt_silme_duckdb_atlanildi", hisse=ticker, hata=str(e))

    def _restore_state(self) -> None:
        """Halt durumunu DuckDB tablosundan geri yükle.

        Returns:
            None
        """
        try:
            with state_store._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS halt_states (
                        ticker VARCHAR PRIMARY KEY,
                        reason VARCHAR,
                        halt_type VARCHAR,
                        expected_resume VARCHAR,
                        action VARCHAR,
                        details_json VARCHAR,
                        updated_at VARCHAR
                    )
                    """
                )
                # Eksik kolonlar için otomatik şema göçü (DuckDB schema migration)
                existing_cols = {c[1] for c in conn.execute("PRAGMA table_info('halt_states')").fetchall()}
                for col_name in ("expected_resume", "action", "details_json"):
                    if col_name not in existing_cols:
                        conn.execute(f"ALTER TABLE halt_states ADD COLUMN {col_name} VARCHAR")

                rows = conn.execute(
                    "SELECT ticker, reason, halt_type, expected_resume, action, details_json, updated_at FROM halt_states"
                ).fetchall()

                with self._lock:
                    for row in rows:
                        t = row[0]
                        det = {}
                        if row[5]:
                            try:
                                det = orjson.loads(row[5])
                            except Exception as json_err:
                                logger.warning("halt_detay_ayristirma_hatasi", hisse=t, hata=str(json_err))
                                det = {}

                        self._halted_tickers[t] = HaltStatus(
                            halted=True,
                            ticker=t,
                            reason=row[1] or "",
                            halt_type=row[2] or HALT_TYPE_KAP,
                            expected_resume=row[3],
                            action=row[4] or ACTION_WAIT,
                            halted_at=row[6],
                            is_active=True,
                            details=det,
                        )

                if rows:
                    logger.info("halt_durumlari_duckdbden_yuklendi", adet=len(rows))
        except Exception as e:
            logger.warning("halt_durumu_duckdb_geri_yukleme_atlanildi", hata=str(e))

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return f"HaltMonitor(aktif_durdurulan_hisse_sayisi={len(self._halted_tickers)})"


# ==============================================================================
# Global Singleton ve Dışa Aktarımlar
# ==============================================================================

halt_monitor: HaltMonitor = HaltMonitor()

__all__: list[str] = [
    "ACTION_CANCEL_ORDERS",
    "ACTION_NO_ACTION",
    "ACTION_REJECT_NEW",
    "ACTION_WAIT",
    "DEFAULT_HALT_DB_PATH",
    "HALT_TYPE_CIRCUIT_BREAKER",
    "HALT_TYPE_CORPORATE",
    "HALT_TYPE_KAP",
    "HALT_TYPE_SPK",
    "HALT_TYPE_VOLATILITY",
    "VALID_ACTIONS",
    "VALID_HALT_TYPES",
    "HaltMonitor",
    "HaltStatus",
    "halt_monitor",
]
