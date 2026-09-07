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
- DuckDB denetim tablosunu doğrudan Polars DataFrame olarak native .pl() ile sorgulama.
- Thread-safe reentrant kilit (`threading.RLock`) mimarisi.
- Context manager protokolü (`__enter__` / `__exit__`) ve güvenli temizleme (`clear`).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

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

HALT_TYPE_KAP: Final[str] = "KAP"
HALT_TYPE_CIRCUIT_BREAKER: Final[str] = "CIRCUIT_BREAKER"
HALT_TYPE_CORPORATE: Final[str] = "CORPORATE"
HALT_TYPE_SPK: Final[str] = "SPK"
HALT_TYPE_VOLATILITY: Final[str] = "VOLATILITY"

ACTION_WAIT: Final[str] = "WAIT"
ACTION_CANCEL_ORDERS: Final[str] = "CANCEL_ORDERS"
ACTION_REJECT_NEW: Final[str] = "REJECT_NEW"
ACTION_NO_ACTION: Final[str] = "NO_ACTION"

DEFAULT_HALT_DB_PATH: Final[str] = "data/halt_audit.duckdb"
DEFAULT_HALT_QUERY_LIMIT: Final[int] = 100
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

VALID_HALT_TYPES: Final[frozenset[str]] = frozenset(
    {
        HALT_TYPE_KAP,
        HALT_TYPE_CIRCUIT_BREAKER,
        HALT_TYPE_CORPORATE,
        HALT_TYPE_SPK,
        HALT_TYPE_VOLATILITY,
    }
)

VALID_ACTIONS: Final[frozenset[str]] = frozenset(
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
            "halted": bool(self.halted),
            "ticker": self.ticker,
            "reason": self.reason,
            "halt_type": self.halt_type,
            "expected_resume": self.expected_resume,
            "action": self.action,
            "halted_at": self.halted_at,
            "is_active": bool(self.is_active),
            "details": dict(self.details),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict(), default=str)

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

    def __enter__(self) -> HaltMonitor:
        """Context manager protokolü girişi."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager protokolü çıkışı."""
        self.clear()

    def clear(self, clear_persisted: bool = False) -> None:
        """Bellekteki durdurma kayıtlarını sıfırla.

        Args:
            clear_persisted: True ise kalıcı StateStore'daki kayıtlar da silinir.
        """
        with self._lock:
            tickers = list(self._halted_tickers.keys())
            self._halted_tickers.clear()

        if clear_persisted:
            for t in tickers:
                self._remove_persisted(t)
        logger.info("halt_monitor_temizlendi", silinen_hisse_sayisi=len(tickers))

    def reset(self) -> None:
        """clear() için takma ad."""
        self.clear()

    def _normalize_ticker(self, ticker: str | None) -> str:
        """Hisse sembolünü büyük harfe çevir ve temizle."""
        if not ticker or not isinstance(ticker, str):
            return ""
        return ticker.strip().upper()

    def _parse_datetime(self, time_val: str | datetime | None) -> datetime | None:
        """Tarih-saat parametresini UTC aware datetime nesnesine güvenle ayrıştır."""
        if time_val is None:
            return None
        if isinstance(time_val, datetime):
            return time_val if time_val.tzinfo else time_val.replace(tzinfo=UTC)
        if isinstance(time_val, str):
            clean_str = time_val.strip()
            if not clean_str or clean_str.lower() in ("none", "null", "nan"):
                return None
            try:
                # ISO 8601 ayrıştırma
                normalized_str = clean_str.replace("Z", "+00:00")
                dt = datetime.fromisoformat(normalized_str)
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except ValueError:
                logger.warning("gecersiz_zaman_formati", deger=clean_str)
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

        ht = halt_type.strip().upper() if halt_type and halt_type.strip().upper() in VALID_HALT_TYPES else HALT_TYPE_KAP
        act = action.strip().upper() if action and action.strip().upper() in VALID_ACTIONS else ACTION_WAIT

        resume_str = (
            expected_resume.isoformat() if isinstance(expected_resume, datetime) else expected_resume
        )
        now_iso = datetime.now(UTC).isoformat()

        status = HaltStatus(
            halted=True,
            ticker=sym,
            reason=reason.strip() if reason else "İşlem Durdurma",
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

    def validate_order(
        self,
        ticker: str,
        current_time: str | datetime | None = None,
    ) -> tuple[bool, str, str]:
        """Emir gönderimi öncesinde hissenin seans durdurma durumunu doğrula.

        Args:
            ticker: Hisse sembolü.
            current_time: İşlem zamanı.

        Returns:
            tuple[bool, str, str]: (Emir onaylandı mı, Önerilen Aksiyon, Açıklama/Gerekçe).
        """
        status = self.check_halt(ticker, current_time=current_time)
        if not (status.halted and status.is_active):
            return True, ACTION_NO_ACTION, "ONAYLANDI: Hisse seansı açıktır."

        action = status.action
        reason = f"RED: {status.ticker} işlemi durdurulmuştur. Neden: {status.reason} (Aksiyon: {action})"
        return False, action, reason

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
        for sym, _ in items:
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
        """Durdurulan hisseleri Polars DataFrame olarak dışa aktar (GEMINI.md Kural 2).

        Args:
            current_time: Opsiyonel Point-In-Time sorgu zamanı.

        Returns:
            pl.DataFrame: Durdurma detaylarını içeren tablo.
        """
        schema: dict[str, pl.DataType] = {
            "ticker": pl.Utf8,
            "halted": pl.Boolean,
            "reason": pl.Utf8,
            "halt_type": pl.Utf8,
            "expected_resume": pl.Utf8,
            "action": pl.Utf8,
            "halted_at": pl.Utf8,
        }

        active_halted = self.get_all_halted(current_time=current_time)
        if not active_halted:
            return pl.DataFrame(schema=schema)

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
        return pl.DataFrame(rows, schema=schema)

    def check_polars(
        self,
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        time_col: str | None = None,
    ) -> pl.DataFrame:
        """Polars DataFrame üzerinde hisselere 'is_halted' kolonu ekle (GEMINI.md Kural 2).

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
            halted_expr = (
                pl.col(ticker_col)
                .fill_null("")
                .str.to_uppercase()
                .is_in(active_set)
                .alias("is_halted")
            )
            return df.with_columns(halted_expr)

        tickers_list = df[ticker_col].to_list()
        times_list = df[time_col].to_list()

        flags: list[bool] = []
        for t, tm in zip(tickers_list, times_list, strict=False):
            if not t or str(t).lower() in ("none", "null", "nan"):
                flags.append(False)
                continue
            flags.append(self.is_halted(str(t), current_time=tm))

        return df.with_columns(pl.Series("is_halted", flags, dtype=pl.Boolean))

    def export_to_duckdb(self, db_path: str = DEFAULT_HALT_DB_PATH) -> int:
        """Durdurma geçmişini kalıcı denetim için DuckDB tablosuna aktar (GEMINI.md Kural 5).

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

        rows = [
            (
                uuid.uuid4().hex,
                s.ticker,
                s.reason,
                s.halt_type,
                s.expected_resume,
                s.action,
                s.halted_at,
                orjson.dumps(s.to_dict(), default=str).decode("utf-8"),
            )
            for s in statuses
        ]

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                configure_duckdb_wal(conn)
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

    def query_audit_duckdb(
        self,
        db_path: str = DEFAULT_HALT_DB_PATH,
        ticker: str | None = None,
        halt_type: str | None = None,
        limit: int = DEFAULT_HALT_QUERY_LIMIT,
    ) -> pl.DataFrame:
        """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak sorgula (GEMINI.md Kural 2 & 5).

        Args:
            db_path: DuckDB dosya yolu.
            ticker: Opsiyonel hisse filtresi.
            halt_type: Opsiyonel durdurma sınıfı filtresi.
            limit: Maksimum satır sayısı.

        Returns:
            pl.DataFrame: Sıfır kopyalı filtreli Polars DataFrame.
        """
        target_file = Path(db_path)
        safe_limit = max(1, int(limit))

        schema: dict[str, pl.DataType] = {
            "id": pl.Utf8,
            "created_at": pl.Datetime,
            "ticker": pl.Utf8,
            "reason": pl.Utf8,
            "halt_type": pl.Utf8,
            "expected_resume": pl.Utf8,
            "action": pl.Utf8,
            "halted_at": pl.Utf8,
            "details_json": pl.Utf8,
        }

        if not target_file.exists():
            return pl.DataFrame(schema=schema)

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                configure_duckdb_wal(conn)
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name = 'halt_audit_log'"
                ).fetchall()
                if not tables:
                    return pl.DataFrame(schema=schema)

                query = "SELECT * FROM halt_audit_log WHERE 1=1"
                params: list[Any] = []

                if ticker:
                    query += " AND ticker = ?"
                    params.append(self._normalize_ticker(ticker))
                if halt_type:
                    query += " AND halt_type = ?"
                    params.append(halt_type.strip().upper())

                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(safe_limit)

                return conn.execute(query, params).pl()

    # ==========================================================================
    # DUCKDB KALICI DURUM YÖNETİMİ (STATE_STORE ENTEGRASYONU)
    # ==========================================================================

    def _persist_state(self, ticker: str) -> None:
        """Halt durumunu DuckDB tablosuna atomik kaydet."""
        try:
            with self._lock:
                status = self._halted_tickers.get(ticker)
            if not status:
                return

            with state_store._connect() as conn:
                configure_duckdb_wal(conn)
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
                        orjson.dumps(status.details, default=str).decode("utf-8"),
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except Exception as e:
            logger.warning("halt_durumu_duckdb_kaydi_atlanildi", hisse=ticker, hata=str(e))

    def _remove_persisted(self, ticker: str) -> None:
        """Halt durumunu DuckDB tablosundan sil."""
        try:
            with state_store._connect() as conn:
                configure_duckdb_wal(conn)
                conn.execute("DELETE FROM halt_states WHERE ticker = ?", (ticker,))
        except Exception as e:
            logger.warning("halt_silme_duckdb_atlanildi", hisse=ticker, hata=str(e))

    def _restore_state(self) -> None:
        """Halt durumunu DuckDB tablosundan geri yükle."""
        try:
            with state_store._connect() as conn:
                configure_duckdb_wal(conn)
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

    def to_dict(self) -> dict[str, Any]:
        """İzleyici durumunu sözlük olarak döner."""
        with self._lock:
            return {
                "halted_tickers_count": len(self._halted_tickers),
                "halted_tickers": sorted(self._halted_tickers.keys()),
            }

    def to_orjson_bytes(self) -> bytes:
        """İzleyici durumunu ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def clear_audit_duckdb(self, db_path: str = DEFAULT_HALT_DB_PATH) -> None:
        """DuckDB seans durdurma denetim tablosunu sıfırlar."""
        clear_halt_audit_duckdb(db_path=db_path)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return f"HaltMonitor(aktif_durdurulan_hisse_sayisi={len(self._halted_tickers)})"


# ==============================================================================
# Global Singleton ve Modül Seviyesi Kolaylık Fonksiyonları
# ==============================================================================

halt_monitor: HaltMonitor = HaltMonitor()


def get_halt_monitor() -> HaltMonitor:
    """HaltMonitor singleton örneğini döndürür."""
    return halt_monitor


def add_stock_halt(
    ticker: str,
    reason: str,
    halt_type: str = HALT_TYPE_KAP,
    expected_resume: str | datetime | None = None,
    action: str = ACTION_WAIT,
    details: dict[str, Any] | None = None,
) -> HaltStatus:
    """Hisse için işlem durdurma kararı ekler."""
    return halt_monitor.add_halt(
        ticker=ticker,
        reason=reason,
        halt_type=halt_type,
        expected_resume=expected_resume,
        action=action,
        details=details,
    )


def remove_stock_halt(ticker: str) -> bool:
    """Hisse işlem durdurma kararını kaldırır."""
    return halt_monitor.remove_halt(ticker=ticker)


def check_stock_halt(
    ticker: str,
    current_time: str | datetime | None = None,
) -> HaltStatus:
    """Hissenin durdurulma durumunu denetler."""
    return halt_monitor.check_halt(ticker=ticker, current_time=current_time)


def is_stock_halted(
    ticker: str,
    current_time: str | datetime | None = None,
) -> bool:
    """Hissenin durdurulmuş ve an itibarıyla kilitli olup olmadığını döndürür."""
    return halt_monitor.is_halted(ticker=ticker, current_time=current_time)


def validate_stock_halt_order(
    ticker: str,
    current_time: str | datetime | None = None,
) -> tuple[bool, str, str]:
    """Emir gönderimi öncesinde seans durdurma kontrolü yapar."""
    return halt_monitor.validate_order(ticker=ticker, current_time=current_time)


def get_all_halted_stocks(
    current_time: str | datetime | None = None,
) -> dict[str, HaltStatus]:
    """Aktif tüm durdurulan hisseleri ve durumlarını döndürür."""
    return halt_monitor.get_all_halted(current_time=current_time)


def get_halted_stock_tickers(
    current_time: str | datetime | None = None,
) -> list[str]:
    """Aktif durdurulan hisse kodlarını döndürür."""
    return halt_monitor.get_halted_tickers(current_time=current_time)


def filter_halted_stock_tickers(
    tickers: list[str],
    current_time: str | datetime | None = None,
) -> list[str]:
    """Verilen hisse listesinden yalnızca durdurulmuş olanları filtreler."""
    return halt_monitor.filter_halted_tickers(tickers=tickers, current_time=current_time)


def export_halt_status_to_polars(
    current_time: str | datetime | None = None,
) -> pl.DataFrame:
    """Durdurulan hisseleri Polars DataFrame olarak dışa aktarır."""
    return halt_monitor.export_to_polars(current_time=current_time)


def check_polars_halt_status(
    df: pl.DataFrame,
    ticker_col: str = "ticker",
    time_col: str | None = None,
) -> pl.DataFrame:
    """Polars DataFrame üzerinde hisselere 'is_halted' kolonu ekler."""
    return halt_monitor.check_polars(df=df, ticker_col=ticker_col, time_col=time_col)


def export_halt_audit_to_duckdb(
    db_path: str = DEFAULT_HALT_DB_PATH,
) -> int:
    """Durdurma kayıtlarını DuckDB denetim tablosuna kaydeder."""
    return halt_monitor.export_to_duckdb(db_path=db_path)


def query_halt_audit_duckdb(
    db_path: str = DEFAULT_HALT_DB_PATH,
    ticker: str | None = None,
    halt_type: str | None = None,
    limit: int = DEFAULT_HALT_QUERY_LIMIT,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu Polars DataFrame olarak sorgular."""
    return halt_monitor.query_audit_duckdb(
        db_path=db_path,
        ticker=ticker,
        halt_type=halt_type,
        limit=limit,
    )


def read_halt_audit_from_duckdb(
    db_path: str = DEFAULT_HALT_DB_PATH,
    ticker: str | None = None,
    halt_type: str | None = None,
    limit: int = DEFAULT_HALT_QUERY_LIMIT,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        ticker: İsteğe bağlı hisse filtresi.
        halt_type: İsteğe bağlı durdurma sınıfı filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Okunan denetim kayıtları.
    """
    path_obj = Path(db_path)
    schema: dict[str, pl.DataType] = {
        "id": pl.Utf8,
        "created_at": pl.Datetime,
        "ticker": pl.Utf8,
        "reason": pl.Utf8,
        "halt_type": pl.Utf8,
        "expected_resume": pl.Utf8,
        "action": pl.Utf8,
        "halted_at": pl.Utf8,
        "details_json": pl.Utf8,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'halt_audit_log'"
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = "SELECT * FROM halt_audit_log WHERE 1=1"
            params: list[Any] = []

            if ticker:
                query += " AND ticker = ?"
                params.append(ticker.upper().strip())
            if halt_type:
                query += " AND halt_type = ?"
                params.append(halt_type.strip().upper())

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(max(1, int(limit)))

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_halt_audit_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_halt_audit_duckdb(db_path: str = DEFAULT_HALT_DB_PATH) -> None:
    """DuckDB'deki seans durdurma denetim tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS halt_audit_log;")
    except Exception as exc:
        logger.error("duckdb_halt_audit_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__: Final[list[str]] = [
    # Eylem Sabitleri
    "ACTION_CANCEL_ORDERS",
    "ACTION_NO_ACTION",
    "ACTION_REJECT_NEW",
    "ACTION_WAIT",
    "VALID_ACTIONS",
    # Durdurma Türleri Sabitleri
    "HALT_TYPE_CIRCUIT_BREAKER",
    "HALT_TYPE_CORPORATE",
    "HALT_TYPE_KAP",
    "HALT_TYPE_SPK",
    "HALT_TYPE_VOLATILITY",
    "VALID_HALT_TYPES",
    # Yapılandırma Sabitleri
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_HALT_DB_PATH",
    "DEFAULT_HALT_QUERY_LIMIT",
    "DEFAULT_WAL_SIZE",
    # Modeller ve Çekirdek Sınıf
    "HaltMonitor",
    "HaltStatus",
    # Singleton
    "halt_monitor",
    # Modül Seviyesi Kolaylık Fonksiyonları
    "add_stock_halt",
    "check_polars_halt_status",
    "check_stock_halt",
    "clear_halt_audit_duckdb",
    "configure_duckdb_wal",
    "export_halt_audit_to_duckdb",
    "export_halt_status_to_polars",
    "filter_halted_stock_tickers",
    "get_all_halted_stocks",
    "get_halt_monitor",
    "get_halted_stock_tickers",
    "is_stock_halted",
    "query_halt_audit_duckdb",
    "read_halt_audit_from_duckdb",
    "remove_stock_halt",
    "to_orjson_bytes",
    "validate_stock_halt_order",
]
