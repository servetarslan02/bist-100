"""ALPHA BIST — Çok Faktörlü Piyasa Rejimi Tespit Motoru (Regime Detector).

- Çok Faktörlü Rejim Tespiti (Trend, Volatilite, Korelasyon, Piyasa Genişliği/Breadth, Hacim)
- Rejim Geçiş Olasılık Matrisi (Markov Transition Matrix)
- Rejim Süresi Takibi (Regime Duration Tracking)
- DuckDB Üzerinde Kalıcı Rejim Günlüğü (Market Regime Audit Trail)
- Polars (Polars >= 1.30) ve orjson desteği
- Thread-safe (RLock) ve Fail-Closed Tasarım
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

try:
    from services.core.otel import otel_trace
except ImportError:
    import functools

    def otel_trace(name: str):
        """Merkezi OTel tracer bulunamadığında kullanılan yerel fallback dekoratörü."""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

logger = structlog.get_logger(__name__)

DEFAULT_LOOKBACK_DAYS: Final[int] = 60
DEFAULT_MAX_HISTORY_LEN: Final[int] = 1000
DEFAULT_REGIME_DUCKDB_PATH: Final[str] = "data/market_regimes.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

REGIME_BULL: Final[str] = "BULL"
REGIME_BEAR: Final[str] = "BEAR"
REGIME_SIDEWAYS: Final[str] = "SIDEWAYS"
REGIME_HIGH_VOL: Final[str] = "HIGH_VOL"
REGIME_LOW_VOL: Final[str] = "LOW_VOL"
REGIME_UNKNOWN: Final[str] = "UNKNOWN"

VALID_REGIMES: Final[tuple[str, ...]] = (
    REGIME_BULL,
    REGIME_BEAR,
    REGIME_SIDEWAYS,
    REGIME_HIGH_VOL,
    REGIME_LOW_VOL,
)


def configure_duckdb_wal(
    conn: duckdb.DuckDBPyConnection,
    checkpoint_threshold: str = DEFAULT_CHECKPOINT_SIZE,
    wal_autocheckpoint: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB WAL parametrelerini optimize eder."""
    try:
        conn.execute(f"SET checkpoint_threshold = '{checkpoint_threshold}';")
        conn.execute(f"SET wal_autocheckpoint = '{wal_autocheckpoint}';")
    except Exception as e:
        logger.warning("regime_duckdb_wal_yapilandirma_uyarisi", hata=str(e))


@dataclass
class RegimeState:
    """Piyasa rejimi durum modeli."""

    regime: str  # BULL, BEAR, SIDEWAYS, HIGH_VOL, LOW_VOL, UNKNOWN
    confidence: float
    duration_days: int
    transition_probability: dict[str, float]
    factors: dict[str, float]
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"RegimeState(regime='{self.regime}', conf={self.confidence:.2f}, "
            f"duration={self.duration_days}d, factors_count={len(self.factors)})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "regime": self.regime,
            "confidence": self.confidence,
            "duration_days": self.duration_days,
            "transition_probability": self.transition_probability,
            "factors": self.factors,
            "detected_at": self.detected_at.isoformat(),
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str, option=orjson.OPT_SERIALIZE_NUMPY)


class RegimeDetector:
    """Çok faktörlü BIST piyasa rejimi tespit motoru.

    Trend, volatilite, hisse korelasyonu ve piyasa genişliği (advance/decline)
    faktörlerini birleştirerek piyasanın makro rejimini belirler.
    """

    REGIMES = list(VALID_REGIMES)

    def __init__(
        self,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        duckdb_conn: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        self.lookback_days = lookback_days
        self._lock = threading.RLock()
        self._regime_history: deque[dict[str, Any]] = deque(maxlen=DEFAULT_MAX_HISTORY_LEN)
        self._current_regime: str = REGIME_UNKNOWN
        self._regime_duration: int = 0
        self._duckdb_conn = duckdb_conn
        if self._duckdb_conn is not None:
            self._init_duckdb_schema()

    def set_duckdb_connection(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Kalıcı rejim geçmişi için DuckDB bağlantısını ayarlar."""
        with self._lock:
            self._duckdb_conn = conn
            self._init_duckdb_schema()

    def _init_duckdb_schema(self) -> None:
        """DuckDB rejim denetim tablosunu ilklendirir."""
        if self._duckdb_conn is None:
            return
        with self._lock:
            configure_duckdb_wal(self._duckdb_conn)
            try:
                self._duckdb_conn.execute("""
                    CREATE TABLE IF NOT EXISTS market_regime_history (
                        id BIGINT,
                        regime VARCHAR,
                        confidence DOUBLE,
                        duration_days INTEGER,
                        factors_json VARCHAR,
                        detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_market_regime START 1;
                """)
            except Exception as exc:
                logger.error("RegimeDetector DuckDB şema oluşturma hatası", hata=str(exc))

    def _get_active_duckdb(self, writable: bool = False) -> tuple[duckdb.DuckDBPyConnection | None, bool]:
        """Aktif DuckDB bağlantısını ve kapatılması gerekip gerekmediğini döndürür."""
        with self._lock:
            if self._duckdb_conn is not None:
                return self._duckdb_conn, False

        p = Path(DEFAULT_REGIME_DUCKDB_PATH)
        if not writable and not p.exists():
            return None, False

        try:
            if writable:
                p.parent.mkdir(parents=True, exist_ok=True)
                conn = duckdb.connect(str(p))
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS market_regime_history (
                        id BIGINT,
                        regime VARCHAR,
                        confidence DOUBLE,
                        duration_days INTEGER,
                        factors_json VARCHAR,
                        detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_market_regime START 1;
                """)
                return conn, True
            else:
                conn = duckdb.connect(str(p), read_only=True)
                tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
                if "market_regime_history" not in tables:
                    conn.close()
                    return None, False
                return conn, True
        except Exception as exc:
            logger.debug("RegimeDetector DuckDB aktif bağlantı hatası", hata=str(exc))
            return None, False

    def _record_to_duckdb(self, state: RegimeState) -> None:
        """Tespit edilen rejimi DuckDB tablosuna yazar."""
        conn, should_close = self._get_active_duckdb(writable=True)
        if conn is None:
            return
        with self._lock:
            try:
                factors_str = orjson.dumps(
                    state.factors, default=str, option=orjson.OPT_SERIALIZE_NUMPY
                ).decode("utf-8")
                conn.execute(
                    """
                    INSERT INTO market_regime_history (id, regime, confidence, duration_days, factors_json, detected_at)
                    VALUES (nextval('seq_market_regime'), ?, ?, ?, ?, ?)
                    """,
                    [state.regime, state.confidence, state.duration_days, factors_str, state.detected_at],
                )
            except Exception as exc:
                logger.debug("RegimeDetector DuckDB kayıt hatası", hata=str(exc))
            finally:
                if should_close:
                    conn.close()

    def read_regimes_from_duckdb(
        self,
        db_path: str = DEFAULT_REGIME_DUCKDB_PATH,
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB'deki rejim geçmişini Polars DataFrame olarak okur."""
        empty_schema = {
            "id": pl.Int64,
            "regime": pl.String,
            "confidence": pl.Float64,
            "duration_days": pl.Int32,
            "factors_json": pl.String,
            "detected_at": pl.Datetime,
        }
        with self._lock:
            if self._duckdb_conn is not None:
                try:
                    return self._duckdb_conn.execute(
                        "SELECT * FROM market_regime_history ORDER BY id DESC LIMIT ?",
                        [limit],
                    ).pl()
                except Exception as e:
                    logger.error("RegimeDetector DuckDB okuma hatası", hata=str(e))
                    return pl.DataFrame(schema=empty_schema)

        p = Path(db_path)
        if not p.exists():
            return pl.DataFrame(schema=empty_schema)

        try:
            conn = duckdb.connect(str(p), read_only=True)
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "market_regime_history" not in tables:
                conn.close()
                return pl.DataFrame(schema=empty_schema)
            df = conn.execute(
                "SELECT * FROM market_regime_history ORDER BY id DESC LIMIT ?",
                [limit],
            ).pl()
            conn.close()
            return df
        except Exception as e:
            logger.error("RegimeDetector dosya okuma hatası", hata=str(e))
            return pl.DataFrame(schema=empty_schema)

    def clear_regimes_duckdb(self, db_path: str = DEFAULT_REGIME_DUCKDB_PATH) -> bool:
        """DuckDB'deki rejim geçmiş tablosunu temizler."""
        with self._lock:
            if self._duckdb_conn is not None:
                try:
                    self._duckdb_conn.execute("DELETE FROM market_regime_history")
                    return True
                except Exception as e:
                    logger.error("RegimeDetector DuckDB temizleme hatası", hata=str(e))
                    return False

        p = Path(db_path)
        if not p.exists():
            return True
        try:
            conn = duckdb.connect(str(p))
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "market_regime_history" in tables:
                conn.execute("DELETE FROM market_regime_history")
            conn.close()
            return True
        except Exception as e:
            logger.error("RegimeDetector dosya temizleme hatası", hata=str(e))
            return False

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"RegimeDetector(current='{self._current_regime}', duration={self._regime_duration}d, "
                f"lookback={self.lookback_days}d, history_size={len(self._regime_history)})"
            )

    @staticmethod
    def _extract_series(df: Any, column_name: str) -> np.ndarray:
        """Polars veya Pandas DataFrame üzerinden güvenli numpy dizisi çıkarır."""
        if df is None:
            return np.array([], dtype=float)

        # Polars DataFrame desteği
        if isinstance(df, pl.DataFrame):
            if column_name in df.columns:
                return df.get_column(column_name).drop_nulls().to_numpy()
            return np.array([], dtype=float)

        # Polars LazyFrame desteği
        if isinstance(df, pl.LazyFrame):
            collected = df.select(column_name).collect()
            return collected.get_column(column_name).drop_nulls().to_numpy()

        # Pandas / Sözlük uyumluluğu
        if hasattr(df, "columns") and column_name in df.columns:
            vals = df[column_name].dropna().values
            return np.asarray(vals, dtype=float)

        return np.array([], dtype=float)

    @otel_trace("regime_detector.detect_regime")
    def detect_regime(
        self,
        market_data: dict[str, Any],  # {ticker: DataFrame (Polars veya Pandas)}
        benchmark_ticker: str = "XU100",
    ) -> RegimeState:
        """Piyasa rejimini çok faktörlü modelle tespit eder.

        Args:
            market_data: Ticker bazında DataFrame sözlüğü
            benchmark_ticker: Referans endeks sembolü (Varsayılan: XU100)

        Returns:
            RegimeState: Tespit edilen rejim durumu.
        """
        with self._lock:
            if benchmark_ticker not in market_data and market_data:
                benchmark_ticker = next(iter(market_data))

            if not benchmark_ticker or benchmark_ticker not in market_data:
                empty_state = RegimeState(
                    regime=REGIME_UNKNOWN,
                    confidence=0.0,
                    duration_days=0,
                    transition_probability={},
                    factors={},
                )
                return empty_state

            df_bench = market_data[benchmark_ticker]
            close = self._extract_series(df_bench, "Close")
            volume = self._extract_series(df_bench, "Volume")
            if len(volume) == 0 and len(close) > 0:
                volume = np.ones(len(close), dtype=float)

            if len(close) < self.lookback_days:
                return RegimeState(
                    regime=REGIME_UNKNOWN,
                    confidence=0.0,
                    duration_days=0,
                    transition_probability={},
                    factors={"available_bars": len(close), "required_bars": self.lookback_days},
                )

            # Faktör Hesaplamaları
            factors: dict[str, float] = {}
            factors["trend_score"] = float(self._calc_trend_score(close))
            factors.update(self._calc_volatility_factors(close))
            factors["momentum_score"] = float(self._calc_momentum_score(close))
            factors.update(self._calc_breadth_factors(market_data))

            avg_corr = float(self._calc_correlation(market_data))
            factors["avg_correlation"] = round(avg_corr, 4)
            factors["dispersion_score"] = round((1.0 - avg_corr) * 100.0, 2)
            factors["volume_trend"] = float(self._calc_volume_trend(volume))

            regime, confidence = self._decide_regime(factors, avg_corr)
            self._update_regime_state(regime, confidence, factors)

            state = RegimeState(
                regime=regime,
                confidence=round(confidence, 4),
                duration_days=self._regime_duration,
                transition_probability=self._estimate_transition_probability(regime),
                factors=factors,
            )

            self._record_to_duckdb(state)
            return state

    def _calc_trend_score(self, close: np.ndarray) -> int:
        """Trend faktörünü hesaplar (0-100)."""
        n = len(close)
        if n < 20:
            return 50

        has_200 = n >= 200
        has_50 = n >= 50
        has_60 = n >= 60

        sma20 = float(np.mean(close[-20:]))
        sma50 = float(np.mean(close[-50:])) if has_50 else sma20
        sma200 = float(np.mean(close[-200:])) if has_200 else sma50

        score = 0
        points = 0

        # Son fiyat SMA20 üzerinde mi?
        points += 20
        if close[-1] > sma20:
            score += 20

        # SMA20 > SMA50 mi?
        if has_50:
            points += 20
            if sma20 > sma50:
                score += 20

        # SMA50 > SMA200 mi?
        if has_200:
            points += 20
            if sma50 > sma200:
                score += 20
        elif has_50:
            points += 20
            if close[-1] > sma50:
                score += 20

        # Son fiyat 20 gün öncesinden yüksek mi?
        points += 20
        if close[-1] > close[-20]:
            score += 20

        # Son fiyat 60 gün öncesinden yüksek mi?
        if has_60:
            points += 20
            if close[-1] > close[-60]:
                score += 20

        return int(round((score / points) * 100)) if points > 0 else 50

    def _calc_volatility_factors(self, close: np.ndarray) -> dict[str, float]:
        """Volatilite faktörlerini hesaplar."""
        if len(close) < 21:
            return {"volatility_score": 0.0, "vol_20d_annual": 0.0, "vol_60d_annual": 0.0}

        returns = np.diff(close[-60:]) / np.maximum(close[-60:-1], 1e-6)
        vol_20d = float(np.std(returns[-20:])) * np.sqrt(252) if len(returns) >= 20 else 0.0
        vol_60d = float(np.std(returns)) * np.sqrt(252) if len(returns) >= 60 else 0.0

        vol_score = 0.0
        if vol_20d > 0.25:
            vol_score = 100.0
        elif vol_20d > 0.15:
            vol_score = 50.0
        elif vol_20d < 0.10:
            vol_score = -50.0

        return {
            "volatility_score": vol_score,
            "vol_20d_annual": round(vol_20d * 100.0, 2),
            "vol_60d_annual": round(vol_60d * 100.0, 2),
        }

    def _calc_momentum_score(self, close: np.ndarray) -> int:
        """Momentum getiri faktörünü hesaplar."""
        n = len(close)
        roc_20d = ((close[-1] / close[-20]) - 1.0) * 100.0 if n >= 20 and close[-20] > 0 else 0.0
        roc_60d = ((close[-1] / close[-60]) - 1.0) * 100.0 if n >= 60 and close[-60] > 0 else 0.0

        score = 0
        if roc_20d > 5.0:
            score += 50
        elif roc_20d < -5.0:
            score -= 50

        if roc_60d > 10.0:
            score += 50
        elif roc_60d < -10.0:
            score -= 50

        return score

    def _calc_breadth_factors(self, market_data: dict[str, Any]) -> dict[str, float]:
        """Piyasa genişliği (Advance/Decline Breadth) faktörlerini hesaplar."""
        advancing = 0
        total = 0

        for _ticker, tdf in market_data.items():
            tclose = self._extract_series(tdf, "Close")
            if len(tclose) >= 2:
                if tclose[-1] > tclose[-2]:
                    advancing += 1
                total += 1

        breadth = (advancing / total) if total > 0 else 0.5
        return {
            "breadth_score": round((breadth - 0.5) * 200.0, 2),
            "advancing_ratio": round(breadth, 4),
        }

    def _calc_correlation(self, market_data: dict[str, Any]) -> float:
        """Hisseler arası ortalama korelasyonu hesaplar."""
        correlations: list[float] = []
        tickers = list(market_data.keys())[:20]

        for i, t1 in enumerate(tickers):
            for t2 in tickers[i + 1 :]:
                c1 = self._extract_series(market_data[t1], "Close")[-20:]
                c2 = self._extract_series(market_data[t2], "Close")[-20:]

                if len(c1) == len(c2) and len(c1) >= 10:
                    r1 = np.diff(c1) / np.maximum(c1[:-1], 1e-6)
                    r2 = np.diff(c2) / np.maximum(c2[:-1], 1e-6)

                    std1 = np.std(r1)
                    std2 = np.std(r2)

                    if std1 > 1e-6 and std2 > 1e-6:
                        corr_matrix = np.corrcoef(r1, r2)
                        val = float(corr_matrix[0, 1])
                        if not math.isnan(val) and not math.isinf(val):
                            correlations.append(val)

        return float(np.mean(correlations)) if correlations else 0.5

    def _calc_volume_trend(self, volume: np.ndarray) -> float:
        """Hacim artış/azalış trendini hesaplar."""
        if len(volume) < 20:
            return 0.0

        vol_recent = float(np.mean(volume[-5:]))
        vol_prev = float(np.mean(volume[-20:-5]))

        if vol_prev <= 0:
            return 0.0

        return round(((vol_recent / vol_prev) - 1.0) * 100.0, 2)

    def _decide_regime(self, factors: dict[str, float], avg_corr: float) -> tuple[str, float]:
        """Çok faktörlü ağırlıklandırma ile nihai piyasa rejimini belirler."""
        bull = bear = sideways = high_vol = low_vol = 0.0

        ts = factors.get("trend_score", 50.0)
        if ts > 60.0:
            bull += 40.0
        elif ts < 30.0:
            bear += 40.0
        else:
            sideways += 30.0

        ms = factors.get("momentum_score", 0.0)
        if ms > 30.0:
            bull += 30.0
        elif ms < -30.0:
            bear += 30.0

        vs = factors.get("volatility_score", 0.0)
        if vs > 50.0:
            high_vol += 50.0
        elif vs < -30.0:
            sideways += 20.0
            low_vol += 40.0

        bs = factors.get("breadth_score", 0.0)
        if bs > 30.0:
            bull += 20.0
        elif bs < -30.0:
            bear += 20.0

        if avg_corr > 0.8:
            bear += 10.0
        elif avg_corr < 0.3:
            bull += 10.0

        if factors.get("volume_trend", 0.0) > 50.0:
            high_vol += 20.0

        scores: dict[str, float] = {
            REGIME_BULL: bull,
            REGIME_BEAR: bear,
            REGIME_SIDEWAYS: sideways,
            REGIME_HIGH_VOL: high_vol,
            REGIME_LOW_VOL: low_vol,
        }

        regime = max(scores, key=lambda k: scores[k])
        max_score = scores[regime]
        confidence = min(1.0, max(0.2, max_score / 100.0))
        return regime, confidence

    def _update_regime_state(self, regime: str, confidence: float, factors: dict[str, float]) -> None:
        """Rejim durumunu günceller ve iç geçmişe kaydeder."""
        if regime != self._current_regime:
            self._regime_duration = 0
            self._current_regime = regime
        else:
            self._regime_duration += 1

        self._regime_history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "regime": regime,
                "confidence": confidence,
                "factors": factors,
            }
        )

        logger.info(
            "Piyasa rejimi tespit edildi",
            rejim=regime,
            guven=round(confidence, 4),
            sure_gun=self._regime_duration,
        )

    def _estimate_transition_probability(self, current_regime: str) -> dict[str, float]:
        """Markov rejim geçiş olasılık matrisini döndürür."""
        transition_matrix: dict[str, dict[str, float]] = {
            REGIME_BULL: {
                REGIME_BULL: 0.65,
                REGIME_BEAR: 0.15,
                REGIME_SIDEWAYS: 0.10,
                REGIME_HIGH_VOL: 0.05,
                REGIME_LOW_VOL: 0.05,
            },
            REGIME_BEAR: {
                REGIME_BULL: 0.10,
                REGIME_BEAR: 0.55,
                REGIME_SIDEWAYS: 0.20,
                REGIME_HIGH_VOL: 0.10,
                REGIME_LOW_VOL: 0.05,
            },
            REGIME_SIDEWAYS: {
                REGIME_BULL: 0.20,
                REGIME_BEAR: 0.20,
                REGIME_SIDEWAYS: 0.40,
                REGIME_HIGH_VOL: 0.10,
                REGIME_LOW_VOL: 0.10,
            },
            REGIME_HIGH_VOL: {
                REGIME_BULL: 0.15,
                REGIME_BEAR: 0.30,
                REGIME_SIDEWAYS: 0.20,
                REGIME_HIGH_VOL: 0.30,
                REGIME_LOW_VOL: 0.05,
            },
            REGIME_LOW_VOL: {
                REGIME_BULL: 0.20,
                REGIME_BEAR: 0.15,
                REGIME_SIDEWAYS: 0.15,
                REGIME_HIGH_VOL: 0.10,
                REGIME_LOW_VOL: 0.40,
            },
        }

        return transition_matrix.get(current_regime, {r: 0.2 for r in VALID_REGIMES})

    @otel_trace("regime_detector.get_regime_history")
    def get_regime_history(self) -> list[dict[str, Any]]:
        """Bellekteki rejim tespit geçmişini liste olarak döndürür."""
        with self._lock:
            return list(self._regime_history)

    def export_history_to_polars(self) -> pl.DataFrame:
        """Rejim geçmişini Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            if not self._regime_history:
                return pl.DataFrame(
                    schema={
                        "timestamp": pl.Utf8,
                        "regime": pl.Utf8,
                        "confidence": pl.Float64,
                        "factors_json": pl.Utf8,
                    }
                )

            records = [
                {
                    "timestamp": r["timestamp"],
                    "regime": r["regime"],
                    "confidence": r["confidence"],
                    "factors_json": orjson.dumps(
                        r["factors"], default=str, option=orjson.OPT_SERIALIZE_NUMPY
                    ).decode("utf-8"),
                }
                for r in self._regime_history
            ]
            return pl.DataFrame(records)


def read_regimes_from_duckdb(
    db_path: str = DEFAULT_REGIME_DUCKDB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """Modül seviyesinde DuckDB rejim geçmişini Polars DataFrame olarak okur."""
    return regime_detector.read_regimes_from_duckdb(db_path=db_path, limit=limit)


def clear_regimes_duckdb(db_path: str = DEFAULT_REGIME_DUCKDB_PATH) -> bool:
    """Modül seviyesinde DuckDB rejim geçmiş tablosunu temizler."""
    return regime_detector.clear_regimes_duckdb(db_path=db_path)


def detect_market_regime(
    market_data: dict[str, Any],
    benchmark_ticker: str = "XU100",
) -> RegimeState:
    """Modül seviyesinde piyasa rejimini tespit eder."""
    return regime_detector.detect_regime(market_data=market_data, benchmark_ticker=benchmark_ticker)


def to_orjson_bytes(data: Any) -> bytes:
    """Veriyi orjson ile güvenli bayt dizisine serileştirir."""
    return orjson.dumps(data, default=str, option=orjson.OPT_SERIALIZE_NUMPY)


# Global Singleton
regime_detector = RegimeDetector()

__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_MAX_HISTORY_LEN",
    "DEFAULT_REGIME_DUCKDB_PATH",
    "DEFAULT_WAL_SIZE",
    "REGIME_BEAR",
    "REGIME_BULL",
    "REGIME_HIGH_VOL",
    "REGIME_LOW_VOL",
    "REGIME_SIDEWAYS",
    "REGIME_UNKNOWN",
    "RegimeDetector",
    "RegimeState",
    "VALID_REGIMES",
    "clear_regimes_duckdb",
    "configure_duckdb_wal",
    "detect_market_regime",
    "read_regimes_from_duckdb",
    "regime_detector",
    "to_orjson_bytes",
]
