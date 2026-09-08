"""ALPHA BIST — Mum Formasyonları Ampirik Başarı Karnesi & ML Özellik Mühendisliği v2.0 (Production-Hardened)

BIST pay piyasasında 12 Japon mum formasyonu ve Smart Money likidite emiliminin
ampirik başarı istatistiklerini (Kazanma Oranı, Kâr Çarpanı, Beklenen Değer) hesaplar;
LightGBM ve rakip makine öğrenimi modellerine beslenecek yüksek değerli, sıfır veri sızıntılı
öznitelik matrislerini (Feature Vectors) vektörize Polars işlemleriyle üretir.

Kurallar & Standartlar:
- Polars zorunludur (pandas yasaktır, clone() kullanılır)
- DuckDB WAL optimizasyonu ve denetim logu desteği (SQLite yasaktır)
- orjson yüksek hızlı serileştirme (standart json yasaktır)
- Sıfır Veri Sızıntısı (Zero Data Leakage / Point-In-Time) ilkesi
- threading.RLock eşzamanlılık güvenliği
- Fail-closed hata yönetimi ve structlog yapısal loglama
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

from services.intelligence.candle_patterns import candle_engine

logger = structlog.get_logger(__name__)

# ===================== SABİTLER (CONSTANTS) =====================

DEFAULT_MIN_SAMPLES: Final[int] = 50
DEFAULT_FORWARD_DAYS: Final[int] = 10
DEFAULT_LOOKBACK_WINDOW: Final[int] = 30
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


# ===================== DUCKDB WAL YARDIMCISI =====================


def configure_duckdb_wal(
    con: duckdb.DuckDBPyConnection,
    checkpoint_size: str = DEFAULT_CHECKPOINT_SIZE,
    wal_size: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB bağlantısında SSD korumalı WAL ve checkpoint parametrelerini yapılandırır.

    Args:
        con: Yapılandırılacak DuckDB bağlantısı.
        checkpoint_size: Otomatik checkpoint eşik boyutu.
        wal_size: Maksimum WAL dosya boyutu.
    """
    con.execute(f"SET checkpoint_threshold = '{checkpoint_size}';")
    con.execute(f"SET wal_autocheckpoint = '{wal_size}';")


# ===================== VERİ MODELLERİ (DATA MODELS) =====================


@dataclass(slots=True)
class CandleEmpiricalSummary:
    """Tek bir mum formasyonunun BIST ampirik performans özeti.

    Attributes:
        pattern: Formasyon adı.
        sample_count: Tarihsel tespit edilen örneklem adedi.
        win_rate: Kazanma oranı yüzde değeri (%0 - %100).
        avg_forward_return: Ortalama ileriye dönük getiri yüzdesi.
        profit_factor: Kâr / Zarar çarpanı (Gross Win / Gross Loss).
        payoff_ratio: Ortalama kazanç / ortalama kayıp oranı.
        expectancy: Matematiksel beklenen değer yüzdesi.
        recommendation: Model karar önerisi derecesi.
    """

    pattern: str
    sample_count: int
    win_rate: float
    avg_forward_return: float
    profit_factor: float
    payoff_ratio: float
    expectancy: float
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart sözlüğe dönüştürür."""
        return {
            "pattern": self.pattern,
            "sample_count": self.sample_count,
            "win_rate": self.win_rate,
            "avg_forward_return": self.avg_forward_return,
            "profit_factor": self.profit_factor,
            "payoff_ratio": self.payoff_ratio,
            "expectancy": self.expectancy,
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandleEmpiricalSummary:
        """Sözlükten CandleEmpiricalSummary nesnesi oluşturur."""
        return cls(
            pattern=str(data.get("pattern", "")),
            sample_count=int(data.get("sample_count", 0)),
            win_rate=float(data.get("win_rate", 0.0)),
            avg_forward_return=float(data.get("avg_forward_return", 0.0)),
            profit_factor=float(data.get("profit_factor", 0.0)),
            payoff_ratio=float(data.get("payoff_ratio", 0.0)),
            expectancy=float(data.get("expectancy", 0.0)),
            recommendation=str(data.get("recommendation", "")),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"CandleEmpiricalSummary(pattern={self.pattern!r}, samples={self.sample_count}, "
            f"win_rate={self.win_rate:.1f}%, expectancy={self.expectancy:.2f}%, rec={self.recommendation!r})"
        )


# ===================== MUM ÖZNİTELİK MÜHENDİSİ MOTORU =====================


class CandleFeatureEngineer:
    """BIST hisselerinde mum formasyonlarının ampirik başarı analizini ve ML özniteliklerini üretir v2.0.

    Özellikler:
    - BIST pay piyasası için ampirik kazanma oranı, kâr faktörü ve beklenen değer tablosu
    - Sıfır Veri Sızıntısı (Zero Data Leakage / Point-In-Time) garantili öznitelik çıkarımı
    - Polars tabanlı yüksek hızlı bellek yönetimi ve tek bloklu vektörize kolon ekleme
    - Esnek büyük/küçük harf duyarlı sütun algılama (Close, close vb.)
    - DuckDB WAL denetim logu ve Polars entegrasyonu
    - threading.RLock thread-safety koruması
    """

    def __init__(self) -> None:
        """CandleFeatureEngineer motorunu başlatır."""
        self._lock = threading.RLock()
        self.pattern_stats: dict[str, dict[str, float]] = {}

    def __repr__(self) -> str:
        with self._lock:
            n_patterns = len(self.pattern_stats)
            return f"CandleFeatureEngineer(tracked_patterns={n_patterns})"

    @staticmethod
    def _find_column(df: pl.DataFrame, candidates: list[str]) -> str:
        """DataFrame içinde aday sütun adlarından ilk eşleşeni bulur.

        Args:
            df: Taranacak Polars DataFrame.
            candidates: Aranacak sütun adları listesi.

        Returns:
            Bulunan sütun adı.

        Raises:
            ValueError: Hiçbir aday sütun bulunamazsa.
        """
        cols = set(df.columns)
        for cand in candidates:
            if cand in cols:
                return cand
        raise ValueError(f"DataFrame içinde beklenen sütun bulunamadı. Adaylar: {candidates}, Mevcut: {df.columns}")

    def compute_empirical_edge_table(
        self,
        stock_dict: dict[str, pl.DataFrame],
        forward_days: int = DEFAULT_FORWARD_DAYS,
    ) -> pl.DataFrame:
        """Tüm BIST hisselerinin tarihsel verilerini tarayarak ampirik başarı tablosu üretir.

        Args:
            stock_dict: {sembol: OHLCV_DataFrame} eşlemesi.
            forward_days: İleriye dönük getiri ölçüm periyodu (gün).

        Returns:
            Formasyon bazlı başarı karnesi Polars DataFrame'i.
        """
        records: list[dict[str, Any]] = []
        fwd_d = max(1, int(forward_days))

        for ticker, df in stock_dict.items():
            if df is None or len(df) < DEFAULT_MIN_SAMPLES:
                continue

            try:
                close_col = self._find_column(df, ["Close", "close", "kapanis"])
            except ValueError:
                logger.warning("kapanis_sutunu_bulunamadi", sembol=ticker)
                continue

            closes = df[close_col].to_numpy()
            n = len(df)

            if n <= DEFAULT_LOOKBACK_WINDOW + fwd_d:
                continue

            for i in range(DEFAULT_LOOKBACK_WINDOW, n - fwd_d):
                sub_df = df[: i + 1]
                c_res = candle_engine.analyze_dataframe(sub_df[-DEFAULT_LOOKBACK_WINDOW:], ticker)

                p_entry = float(closes[i])
                p_exit = float(closes[i + fwd_d])

                if p_entry <= 0.0 or not np.isfinite(p_entry) or not np.isfinite(p_exit):
                    continue

                fwd_ret = (p_exit - p_entry) / p_entry * 100.0

                for pat in c_res.patterns_detected:
                    records.append(
                        {
                            "ticker": ticker,
                            "pattern": pat,
                            "fwd_ret": fwd_ret,
                            "is_win": fwd_ret > 0.0,
                            "buyer_pressure": c_res.buyer_pressure_pct,
                        }
                    )

        if not records:
            return pl.DataFrame()

        df_rec = pl.DataFrame(records)
        summary: list[dict[str, Any]] = []

        with self._lock:
            self.pattern_stats.clear()

            for pat, grp in df_rec.group_by("pattern"):
                pat_name = str(pat[0] if isinstance(pat, tuple) else pat)
                count = len(grp)
                if count == 0:
                    continue

                win_count = int(grp["is_win"].sum())
                win_rate = (win_count / count) * 100.0
                avg_ret = float(grp["fwd_ret"].mean())

                wins = grp.filter(pl.col("fwd_ret") > 0.0)["fwd_ret"]
                losses = grp.filter(pl.col("fwd_ret") < 0.0)["fwd_ret"].abs()

                avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
                avg_loss = float(losses.mean()) if len(losses) > 0 else 1e-9

                sum_win = float(wins.sum()) if len(wins) > 0 else 0.0
                sum_loss = float(losses.sum()) if len(losses) > 0 else 1e-9

                payoff_ratio = round(avg_win / max(avg_loss, 1e-9), 2)
                profit_factor = round(sum_win / max(sum_loss, 1e-9), 2)

                # Beklenen Değer (Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss))
                expectancy = ((win_rate / 100.0) * avg_win) - (((100.0 - win_rate) / 100.0) * avg_loss)

                rec_text = (
                    "⭐⭐⭐⭐⭐ (Güçlü Al)"
                    if expectancy > 1.0 and win_rate >= 50.0
                    else ("⭐⭐⭐ (Nötr/Teyitli)" if expectancy > 0.0 else "⚠️ (Filtrelenmeli)")
                )

                item = CandleEmpiricalSummary(
                    pattern=pat_name,
                    sample_count=count,
                    win_rate=round(win_rate, 1),
                    avg_forward_return=round(avg_ret, 2),
                    profit_factor=profit_factor,
                    payoff_ratio=payoff_ratio,
                    expectancy=round(expectancy, 2),
                    recommendation=rec_text,
                )
                summary.append(item.to_dict())

                self.pattern_stats[pat_name] = {
                    "win_rate": item.win_rate,
                    "profit_factor": item.profit_factor,
                    "expectancy": item.expectancy,
                    "sample_count": float(count),
                }

        return pl.DataFrame(summary).sort(by="expectancy", descending=True)

    def extract_features_for_dataframe(
        self,
        df: pl.DataFrame,
        ticker: str = "ASSET",
    ) -> pl.DataFrame:
        """OHLCV DataFrame'ine ML modelinin doğrudan öğrenebileceği sayısal mum öznitelikleri ekler.

        Sıfır Veri Sızıntısı (Point-In-Time):
        Her t anında yalnızca t ve öncesindeki barlar analiz edilir; geleceğe bakılmaz.

        Args:
            df: Girdi OHLCV Polars DataFrame.
            ticker: Hisse senedi sembolü.

        Returns:
            Öznitelik sütunları eklenmiş yeni Polars DataFrame.
        """
        if df is None or len(df) == 0:
            return pl.DataFrame()

        n = len(df)
        df_feat = df.clone()

        if n < 4:
            # Asgari bar sayısı yetersizse sıfır değerli kolonlar üret
            zero_arr = np.zeros(n, dtype=np.float64)
            return df_feat.with_columns(
                pl.lit(zero_arr).alias("feat_buyer_pressure"),
                pl.lit(zero_arr).alias("feat_candle_score"),
                pl.lit(zero_arr).alias("feat_has_bull_engulfing"),
                pl.lit(zero_arr).alias("feat_has_hammer"),
                pl.lit(zero_arr).alias("feat_has_morning_star"),
                pl.lit(zero_arr).alias("feat_has_soldiers"),
                pl.lit(zero_arr).alias("feat_has_fvg"),
                pl.lit(zero_arr).alias("feat_has_shooting_star"),
                pl.lit(zero_arr).alias("feat_has_crows"),
            )

        col_buyer_pressure = np.zeros(n, dtype=np.float64)
        col_candle_score = np.zeros(n, dtype=np.float64)
        col_has_engulfing = np.zeros(n, dtype=np.float64)
        col_has_hammer = np.zeros(n, dtype=np.float64)
        col_has_morning_star = np.zeros(n, dtype=np.float64)
        col_has_soldiers = np.zeros(n, dtype=np.float64)
        col_has_fvg = np.zeros(n, dtype=np.float64)
        col_has_shooting_star = np.zeros(n, dtype=np.float64)
        col_has_crows = np.zeros(n, dtype=np.float64)

        for i in range(3, n):
            # Point-in-time: Sadece i ve gerisindeki son 30 barı al
            sub_df = df[max(0, i - DEFAULT_LOOKBACK_WINDOW) : i + 1]
            c_res = candle_engine.analyze_dataframe(sub_df, ticker)

            col_buyer_pressure[i] = c_res.buyer_pressure_pct
            col_candle_score[i] = c_res.candle_score

            pats = set(c_res.patterns_detected)
            if "BULLISH_ENGULFING" in pats:
                col_has_engulfing[i] = 1.0
            if "HAMMER_PINBAR" in pats:
                col_has_hammer[i] = 1.0
            if "MORNING_STAR" in pats:
                col_has_morning_star[i] = 1.0
            if "THREE_WHITE_SOLDIERS" in pats:
                col_has_soldiers[i] = 1.0
            if "BULLISH_FVG" in pats:
                col_has_fvg[i] = 1.0
            if "SHOOTING_STAR" in pats or "BEARISH_ENGULFING" in pats:
                col_has_shooting_star[i] = 1.0
            if "THREE_BLACK_CROWS" in pats:
                col_has_crows[i] = 1.0

        # Tek bir vektörize blokta tüm sütunları ekle (bellek optimizasyonu)
        return df_feat.with_columns(
            pl.lit(col_buyer_pressure).alias("feat_buyer_pressure"),
            pl.lit(col_candle_score).alias("feat_candle_score"),
            pl.lit(col_has_engulfing).alias("feat_has_bull_engulfing"),
            pl.lit(col_has_hammer).alias("feat_has_hammer"),
            pl.lit(col_has_morning_star).alias("feat_has_morning_star"),
            pl.lit(col_has_soldiers).alias("feat_has_soldiers"),
            pl.lit(col_has_fvg).alias("feat_has_fvg"),
            pl.lit(col_has_shooting_star).alias("feat_has_shooting_star"),
            pl.lit(col_has_crows).alias("feat_has_crows"),
        )

    # ===================== DUCKDB & POLARS ENTEGRASYONU =====================

    def export_empirical_table_duckdb(
        self,
        edge_df: pl.DataFrame,
        db_path: str = ":memory:",
        table_name: str = "candle_empirical_edge",
    ) -> None:
        """Ampirik mum başarı tablosunu DuckDB veritabanına kaydeder.

        Args:
            edge_df: Başarı tablosunu içeren Polars DataFrame.
            db_path: DuckDB veritabanı dosya yolu.
            table_name: Hedef tablo adı.
        """
        if edge_df is None or len(edge_df) == 0:
            logger.warning("bos_tablo_duckdbye_yazilamadi", tablo=table_name)
            return

        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            arrow_data = edge_df.to_arrow()
            con.register("arrow_view", arrow_data)
            con.execute(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM arrow_view LIMIT 0")
            con.execute(f"INSERT INTO {table_name} SELECT * FROM arrow_view")
            logger.info("ampirik_mum_tablosu_duckdbye_yazildi", tablo=table_name, adet=len(edge_df))
        finally:
            con.close()

    def read_empirical_table_polars(
        self,
        db_path: str = ":memory:",
        table_name: str = "candle_empirical_edge",
    ) -> pl.DataFrame:
        """DuckDB veritabanındaki ampirik mum başarı tablosunu Polars DataFrame olarak okur.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.

        Returns:
            Ampirik başarı kayıtlarını içeren Polars DataFrame.
        """
        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            arrow_table = con.execute(f"SELECT * FROM {table_name} ORDER BY expectancy DESC").arrow()
            return pl.from_arrow(arrow_table)  # type: ignore[return-value]
        finally:
            con.close()


# Singleton Örneği
candle_feature_engineer = CandleFeatureEngineer()

__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_FORWARD_DAYS",
    "DEFAULT_LOOKBACK_WINDOW",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_WAL_SIZE",
    "CandleEmpiricalSummary",
    "CandleFeatureEngineer",
    "candle_feature_engineer",
    "configure_duckdb_wal",
]
