"""ALPHA BIST — Dinamik Pozisyon ve Risk Yönetim Motoru (Polars-Native & DuckDB Destekli).

Bu modül, Borsa İstanbul Pay Piyasası'nda çalışan stratejiler için:
- Dinamik pozisyon ağırlıklandırma (Equal, Inverse Volatility, Score-Weighted)
- Çok faktörlü piyasa rejim tespiti (Trend, Volatilite, Momentum)
- Pozisyon ve sektör maruziyet tavanı denetimi (Position & Sector Concentration)
- Dinamik Stop-Loss ve Trailing Stop takibi (Kayıp Durdurma ve İzleyen Stop)
- Portföy zirve ve drawdown takibi (Peak Equity & Drawdown Guard)
- DuckDB üzerinde denetim izi arşivi ve Polars analitik dışa aktarımı sağlar.
"""

from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import numpy as np
import orjson
import polars as pl
import structlog

if TYPE_CHECKING:
    import duckdb

from services.core.otel import otel_trace
from services.core.risk_config import RiskManagerConfig, risk_config

logger = structlog.get_logger(__name__)

DEFAULT_WEIGHT_METHOD: Final[str] = "equal"
DEFAULT_MAX_WEIGHT: Final[float] = 0.20
DEFAULT_RISK_AUDIT_DB: Final[str] = "data/risk_manager_audit.duckdb"


@dataclass(slots=True)
class PositionRiskInfo:
    """Tekil hisse pozisyonu ve risk takip veri modeli."""

    ticker: str
    quantity: int
    entry_price: float
    current_price: float
    peak_price: float
    sector: str = "GENEL"
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def unrealized_pnl_pct(self) -> float:
        """Gerçekleşmemiş kâr/zarar yüzdesi."""
        if self.entry_price <= 0:
            return 0.0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100.0

    @property
    def drawdown_from_peak_pct(self) -> float:
        """Zirve fiyattan olan geri çekilme yüzdesi."""
        if self.peak_price <= 0:
            return 0.0
        return ((self.peak_price - self.current_price) / self.peak_price) * 100.0

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        d = asdict(self)
        d["unrealized_pnl_pct"] = round(self.unrealized_pnl_pct, 2)
        d["drawdown_from_peak_pct"] = round(self.drawdown_from_peak_pct, 2)
        d["updated_at"] = self.updated_at.isoformat()
        return d

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"PositionRiskInfo(hisse='{self.ticker}', adet={self.quantity}, "
            f"maliyet={self.entry_price:.2f}, son={self.current_price:.2f}, "
            f"pnl=%{self.unrealized_pnl_pct:+.1f})"
        )


@dataclass(slots=True)
class RiskManagerState:
    """Portföy genel risk durumu modeli."""

    current_drawdown_pct: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    total_exposure_pct: float = 0.0
    cash_ratio_pct: float = 100.0
    positions_count: int = 0
    is_halted: bool = False
    halt_reason: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        d = asdict(self)
        d["updated_at"] = self.updated_at.isoformat()
        return d

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"RiskManagerState(equity={self.current_equity:.2f}, peak={self.peak_equity:.2f}, "
            f"dd=%{self.current_drawdown_pct:.2f}, poz_adet={self.positions_count})"
        )


class RiskManager:
    """Dinamik pozisyon ve portföy risk yönetim motoru (Fail-Closed, Thread-Safe)."""

    def __init__(
        self,
        config: RiskManagerConfig | None = None,
        duckdb_conn: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        self._lock = threading.RLock()
        cfg = config or risk_config
        self.config = cfg
        self.max_position_pct = float(cfg.max_position_pct)
        self.max_sector_pct = float(cfg.max_sector_pct)
        self.max_drawdown_pct = float(cfg.max_drawdown_pct)
        self.stop_loss_pct = float(cfg.stop_loss_pct)
        self.trailing_stop_pct = float(cfg.trailing_stop_pct)
        self.max_open_positions = int(cfg.max_open_positions)
        self.min_cash_ratio = float(cfg.min_cash_ratio)
        self.volatility_cap = float(cfg.volatility_cap)
        self.correlation_threshold = float(cfg.correlation_threshold)

        self._positions: dict[str, PositionRiskInfo] = {}
        self._sector_exposure: dict[str, float] = {}
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._current_drawdown_pct: float = 0.0
        self._is_halted: bool = False
        self._halt_reason: str = ""

        self._duckdb_conn = duckdb_conn
        if self._duckdb_conn is not None:
            self._init_duckdb_schema()

    def set_duckdb_connection(self, conn: duckdb.DuckDBPyConnection) -> None:
        """DuckDB risk denetim arşivi için bağlantıyı tanımlar."""
        with self._lock:
            self._duckdb_conn = conn
            self._init_duckdb_schema()

    def _init_duckdb_schema(self) -> None:
        """DuckDB risk denetim tablolarını ilklendirir."""
        if self._duckdb_conn is None:
            return
        with self._lock:
            try:
                self._duckdb_conn.execute("""
                    CREATE TABLE IF NOT EXISTS risk_drawdown_audit (
                        id BIGINT,
                        current_equity DOUBLE,
                        peak_equity DOUBLE,
                        drawdown_pct DOUBLE,
                        is_halted BOOLEAN,
                        halt_reason VARCHAR,
                        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_risk_drawdown_audit START 1;

                    CREATE TABLE IF NOT EXISTS risk_weights_audit (
                        id BIGINT,
                        method VARCHAR,
                        tickers_count INTEGER,
                        weights_json VARCHAR,
                        calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_risk_weights_audit START 1;
                """)
            except Exception as exc:
                logger.error("RiskManager DuckDB şema oluşturma hatası", hata=str(exc))

    def _record_drawdown_audit(self) -> None:
        """Drawdown durumunu DuckDB denetim tablosuna yazar."""
        if self._duckdb_conn is None:
            return
        with self._lock:
            try:
                self._duckdb_conn.execute(
                    """
                    INSERT INTO risk_drawdown_audit (
                        id, current_equity, peak_equity, drawdown_pct, is_halted, halt_reason, recorded_at
                    ) VALUES (
                        nextval('seq_risk_drawdown_audit'), ?, ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        self._current_equity,
                        self._peak_equity,
                        self._current_drawdown_pct,
                        self._is_halted,
                        self._halt_reason,
                        datetime.now(UTC),
                    ],
                )
            except Exception as exc:
                logger.debug("RiskManager DuckDB drawdown yazma hatası", hata=str(exc))

    def _record_weights_audit(self, method: str, weights: dict[str, float]) -> None:
        """Ağırlık hesaplama geçmişini DuckDB'ye yazar."""
        if self._duckdb_conn is None:
            return
        with self._lock:
            try:
                w_json = orjson.dumps(weights).decode("utf-8")
                self._duckdb_conn.execute(
                    """
                    INSERT INTO risk_weights_audit (
                        id, method, tickers_count, weights_json, calculated_at
                    ) VALUES (
                        nextval('seq_risk_weights_audit'), ?, ?, ?, ?
                    )
                    """,
                    [
                        method,
                        len(weights),
                        w_json,
                        datetime.now(UTC),
                    ],
                )
            except Exception as exc:
                logger.debug("RiskManager DuckDB ağırlık yazma hatası", hata=str(exc))

    @property
    def is_halted(self) -> bool:
        """Risk kaynaklı işlem durdurma durumu."""
        with self._lock:
            return self._is_halted

    @property
    def halt_reason(self) -> str:
        """İşlem durdurma gerekçesi."""
        with self._lock:
            return self._halt_reason

    def get_state(self) -> RiskManagerState:
        """Mevcut portföy risk durumunu döner."""
        with self._lock:
            pv = max(self._current_equity, 1e-6)
            total_pos_val = sum(p.quantity * p.current_price for p in self._positions.values())
            exposure_pct = (total_pos_val / pv) * 100.0 if self._current_equity > 0 else 0.0
            cash_pct = max(0.0, 100.0 - exposure_pct)
            return RiskManagerState(
                current_drawdown_pct=round(self._current_drawdown_pct, 2),
                peak_equity=round(self._peak_equity, 2),
                current_equity=round(self._current_equity, 2),
                total_exposure_pct=round(exposure_pct, 2),
                cash_ratio_pct=round(cash_pct, 2),
                positions_count=len(self._positions),
                is_halted=self._is_halted,
                halt_reason=self._halt_reason,
            )

    @otel_trace("risk_manager.calculate_weights")
    def calculate_weights(
        self,
        predictions: list[dict[str, Any]],
        method: str = DEFAULT_WEIGHT_METHOD,
        max_weight: float = DEFAULT_MAX_WEIGHT,
    ) -> dict[str, float]:
        """Tahmin edilen hisseler için portföy ağırlıklarını (weight) hesaplar.

        Args:
            predictions: Model tahmin sözlükleri listesi [{'ticker': '...', 'score': ..., ...}].
            method: Ağırlıklandırma yöntemi ('equal', 'inverse_volatility', 'score_weighted').
            max_weight: Tekil hisse için atanabilecek tavan ağırlık oranı (örn. 0.20 = %20).

        Returns:
            dict[str, float]: Hisse koduna karşılık gelen normalize ağırlık oranları sözlüğü.
        """
        if not predictions:
            return {}

        with self._lock:
            tickers = [p.get("ticker", "") for p in predictions if p.get("ticker")]
            if not tickers:
                return {}

            # max_weight parametresi acikca verilmisse onu kullan, aksi halde max_position_pct
            effective_max_weight = max_weight if max_weight is not None else self.max_position_pct
            weights: dict[str, float] = {}

            if method == "equal":
                w = 1.0 / len(tickers)
                for t in tickers:
                    weights[t] = min(w, effective_max_weight)

            elif method == "inverse_volatility":
                inv_vols: list[float] = []
                for p in predictions:
                    features = p.get("features", {})
                    vol = features.get("volatility_20d", 0.40) if isinstance(features, dict) else 0.40
                    try:
                        f_vol = float(vol)
                        if math.isnan(f_vol) or math.isinf(f_vol) or f_vol <= 0.001:
                            f_vol = 0.40
                    except (TypeError, ValueError):
                        f_vol = 0.40
                    inv_vols.append(1.0 / f_vol)

                total_inv_vol = sum(inv_vols)
                for p, inv_v in zip(predictions, inv_vols, strict=False):
                    ticker = p.get("ticker", "")
                    if ticker:
                        w = (inv_v / total_inv_vol) if total_inv_vol > 0 else (1.0 / len(predictions))
                        weights[ticker] = min(w, effective_max_weight)

            elif method == "score_weighted":
                scores_list: list[float] = []
                for p in predictions:
                    sc = p.get("score", 0.0)
                    try:
                        f_sc = float(sc)
                        scores_list.append(max(0.0, 0.0 if math.isnan(f_sc) or math.isinf(f_sc) else f_sc))
                    except (TypeError, ValueError):
                        scores_list.append(0.0)

                scores_arr = np.array(scores_list, dtype=np.float64)
                total_score = float(scores_arr.sum())

                if total_score <= 0:
                    w = 1.0 / len(tickers)
                    for t in tickers:
                        weights[t] = min(w, effective_max_weight)
                else:
                    raw_weights = scores_arr / total_score
                    for p, w in zip(predictions, raw_weights, strict=False):
                        ticker = p.get("ticker", "")
                        if ticker:
                            weights[ticker] = min(float(w), effective_max_weight)

            else:
                raise ValueError(f"Bilinmeyen ağırlıklandırma yöntemi: {method}")

            # Ağırlıkları toplamı 1.0 olacak şekilde yeniden normalize et
            total_w = sum(weights.values())
            if total_w > 0:
                for t in weights:
                    weights[t] = round(weights[t] / total_w, 6)

            self._record_weights_audit(method, weights)
            return weights

    @otel_trace("risk_manager.get_market_regime")
    def get_market_regime(
        self,
        bm_df: pl.DataFrame | pl.LazyFrame,
        target_date: Any,
    ) -> float:
        """BIST100 endeks verisine göre piyasa rejim katsayısını hesaplar.

        Rejim katsayısı:
        - 1.0: Boğa Piyasası (Full Bullish — %100 yatırım kapasitesi)
        - 0.0: Ayı Piyasası (Full Bearish — %100 nakit modu)
        - 0.25 - 0.75: Nötr / Geçiş rejimleri (Kısmi pozisyonlanma)

        Args:
            bm_df: BIST100 endeks verisi içeren Polars DataFrame / LazyFrame.
            target_date: Hedef referans tarihi.

        Returns:
            float: 0.0 ile 1.0 arasında rejim katsayısı.
        """
        # Polars LazyFrame ise topla
        df = bm_df.collect() if isinstance(bm_df, pl.LazyFrame) else bm_df

        if df.is_empty() or "Close" not in df.columns:
            return 0.5

        # Tarih filtresi uygula
        sub_bm = df
        if "Date" in df.columns:
            try:
                sub_bm = df.filter(pl.col("Date") <= target_date)
            except Exception:
                sub_bm = df

        if len(sub_bm) < 200:
            return 1.0

        try:
            closes = sub_bm["Close"].cast(pl.Float64)
            current_close = float(closes.slice(-1, 1).item())
        except Exception:
            return 0.5

        if current_close <= 0:
            return 0.0

        # Hareketli ortalamalar
        try:
            ma_50_series = closes.rolling_mean(window_size=50)
            ma_50 = float(ma_50_series.slice(-1, 1).item()) if len(closes) >= 50 else current_close
            ma_200_series = closes.rolling_mean(window_size=200)
            ma_200 = float(ma_200_series.slice(-1, 1).item()) if len(closes) >= 200 else current_close
        except Exception:
            ma_50 = current_close
            ma_200 = current_close

        # Volatilite (20 günlük getiri standart sapması)
        vol_20d = 0.20
        if len(closes) > 20:
            try:
                returns = closes.pct_change().drop_nulls()
                if len(returns) >= 20:
                    vol_val = returns.tail(20).std()
                    if vol_val is not None and not math.isnan(vol_val):
                        vol_20d = float(vol_val)
            except Exception:
                vol_20d = 0.20

        # Momentum (20 günlük getiri)
        momentum_20d = 0.0
        if len(closes) > 20:
            try:
                prev_close = float(closes.slice(-21, 1).item())
                if prev_close > 0:
                    momentum_20d = (current_close / prev_close) - 1.0
            except Exception:
                momentum_20d = 0.0

        # Trend Skoru (0.0 - 1.0)
        trend_score = 0.5
        if current_close > ma_200:
            trend_score += 0.3
        else:
            trend_score -= 0.3

        if current_close > ma_50:
            trend_score += 0.2
        else:
            trend_score -= 0.2

        # Volatilite Çarpanı
        vol_factor = 1.0
        if vol_20d > 0.35:
            vol_factor = 0.5
        elif vol_20d > 0.25:
            vol_factor = 0.7
        elif vol_20d < 0.15:
            vol_factor = 1.1

        # Momentum Çarpanı
        momentum_factor = 1.0
        if momentum_20d > 0.10:
            momentum_factor = 1.15
        elif momentum_20d > 0.03:
            momentum_factor = 1.05
        elif momentum_20d < -0.10:
            momentum_factor = 0.6
        elif momentum_20d < -0.03:
            momentum_factor = 0.8

        regime_score = max(0.0, min(1.0, trend_score * vol_factor * momentum_factor))
        return round(regime_score, 2)

    @otel_trace("risk_manager.update_portfolio_drawdown")
    def update_portfolio_drawdown(self, current_equity: float) -> tuple[float, bool]:
        """Portföy değerini günceller, drawdown hesaplar ve aşım durumunda kill-switch tetikler.

        Args:
            current_equity: Güncel portföy net aktif değeri (NAV).

        Returns:
            tuple[float, bool]: (Güncel Drawdown %, İşlem Durduruldu mu?)
        """
        with self._lock:
            if current_equity <= 0:
                return self._current_drawdown_pct, self._is_halted

            self._current_equity = current_equity
            if current_equity > self._peak_equity:
                self._peak_equity = current_equity

            if self._peak_equity > 0:
                self._current_drawdown_pct = ((self._peak_equity - current_equity) / self._peak_equity) * 100.0
            else:
                self._current_drawdown_pct = 0.0

            # Drawdown tavan kontrolü
            if self._current_drawdown_pct > self.max_drawdown_pct:
                self._is_halted = True
                self._halt_reason = (
                    f"Maksimum portföy drawdown sınırı aşıldı: "
                    f"%{self._current_drawdown_pct:.1f} > %{self.max_drawdown_pct:.1f}"
                )
                logger.error(
                    "Portföy risk durdurma (Kill-Switch) devrede",
                    drawdown_pct=self._current_drawdown_pct,
                    limit=self.max_drawdown_pct,
                    sebep=self._halt_reason,
                )
            else:
                self._is_halted = False
                self._halt_reason = ""

            self._record_drawdown_audit()
            return self._current_drawdown_pct, self._is_halted

    @otel_trace("risk_manager.update_position")
    def update_position(
        self,
        ticker: str,
        quantity: int,
        price: float,
        sector: str = "GENEL",
    ) -> PositionRiskInfo | None:
        """Portföydeki pozisyonu ve zirve fiyatını günceller.

        Args:
            ticker: Hisse sembolü.
            quantity: Mevcut pozisyon adedi (0 ise pozisyon silinir).
            price: Güncel piyasa fiyatı.
            sector: Hissenin ait olduğu sektör.

        Returns:
            PositionRiskInfo | None: Güncellenmiş pozisyon modeli veya None.
        """
        with self._lock:
            if quantity <= 0:
                self._positions.pop(ticker, None)
                return None

            pos = self._positions.get(ticker)
            if pos is None:
                pos = PositionRiskInfo(
                    ticker=ticker,
                    quantity=quantity,
                    entry_price=price,
                    current_price=price,
                    peak_price=price,
                    sector=sector,
                )
                self._positions[ticker] = pos
            else:
                pos.quantity = quantity
                pos.current_price = price
                if price > pos.peak_price:
                    pos.peak_price = price
                pos.updated_at = datetime.now(UTC)

            return pos

    @otel_trace("risk_manager.check_stop_loss")
    def check_stop_loss(self, ticker: str, current_price: float) -> tuple[bool, str]:
        """Pozisyon için sabit stop-loss ihlali olup olmadığını denetler.

        Args:
            ticker: Hisse sembolü.
            current_price: Güncel piyasa fiyatı.

        Returns:
            tuple[bool, str]: (Stop-loss tetiklendi mi?, Açıklama gerekçesi)
        """
        with self._lock:
            pos = self._positions.get(ticker)
            if pos is None or pos.entry_price <= 0:
                return False, "Pozisyon bulunamadı"

            pos.current_price = current_price
            loss_pct = ((pos.entry_price - current_price) / pos.entry_price) * 100.0
            if loss_pct >= self.stop_loss_pct:
                reason = f"Sabit Stop-Loss tetiklendi: %{loss_pct:.1f} >= %{self.stop_loss_pct:.1f}"
                logger.warn("Stop-Loss uyarısı", hisse=ticker, zarar_pct=loss_pct, limit=self.stop_loss_pct)
                return True, reason

            return False, "Stop-loss güvenli"

    @otel_trace("risk_manager.check_trailing_stop")
    def check_trailing_stop(self, ticker: str, current_price: float) -> tuple[bool, str]:
        """Pozisyon için izleyen stop (trailing stop) ihlali olup olmadığını denetler.

        Args:
            ticker: Hisse sembolü.
            current_price: Güncel piyasa fiyatı.

        Returns:
            tuple[bool, str]: (Trailing stop tetiklendi mi?, Açıklama gerekçesi)
        """
        with self._lock:
            pos = self._positions.get(ticker)
            if pos is None or pos.peak_price <= 0:
                return False, "Pozisyon bulunamadı"

            pos.current_price = current_price
            if current_price > pos.peak_price:
                pos.peak_price = current_price

            dd_from_peak = ((pos.peak_price - current_price) / pos.peak_price) * 100.0
            if dd_from_peak >= self.trailing_stop_pct:
                reason = f"İzleyen Stop (Trailing Stop) tetiklendi: %{dd_from_peak:.1f} >= %{self.trailing_stop_pct:.1f}"
                logger.warn(
                    "Trailing-Stop uyarısı",
                    hisse=ticker,
                    geri_cekilme_pct=dd_from_peak,
                    limit=self.trailing_stop_pct,
                )
                return True, reason

            return False, "Trailing-stop güvenli"

    @otel_trace("risk_manager.export_positions_to_polars")
    def export_positions_to_polars(self) -> pl.DataFrame:
        """Mevcut açık pozisyonların risk durumunu Polars DataFrame olarak döner."""
        with self._lock:
            if not self._positions:
                return pl.DataFrame(
                    schema={
                        "ticker": pl.Utf8,
                        "quantity": pl.Int64,
                        "entry_price": pl.Float64,
                        "current_price": pl.Float64,
                        "peak_price": pl.Float64,
                        "sector": pl.Utf8,
                        "unrealized_pnl_pct": pl.Float64,
                        "drawdown_from_peak_pct": pl.Float64,
                        "updated_at": pl.Utf8,
                    }
                )

            data = [p.to_dict() for p in self._positions.values()]
            return pl.DataFrame(data)

    @otel_trace("risk_manager.export_audit_to_polars")
    def export_audit_to_polars(self) -> pl.DataFrame:
        """DuckDB'de saklanan drawdown denetim geçmişini Polars DataFrame olarak döner."""
        if self._duckdb_conn is None:
            return pl.DataFrame(
                schema={
                    "id": pl.Int64,
                    "current_equity": pl.Float64,
                    "peak_equity": pl.Float64,
                    "drawdown_pct": pl.Float64,
                    "is_halted": pl.Boolean,
                    "halt_reason": pl.Utf8,
                    "recorded_at": pl.Datetime,
                }
            )

        with self._lock:
            try:
                return self._duckdb_conn.execute("SELECT * FROM risk_drawdown_audit ORDER BY id ASC").pl()
            except Exception as exc:
                logger.error("DuckDB drawdown denetim kayıtları çekilemedi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"RiskManager(max_pos={self.max_position_pct:.1%}, max_sec={self.max_sector_pct:.1%}, "
                f"max_dd={self.max_drawdown_pct:.1%}, stop_loss={self.stop_loss_pct:.1%}, "
                f"halted={self._is_halted})"
            )


# Global varsayılan singleton motoru
risk_manager: Final[RiskManager] = RiskManager()

__all__ = [
    "DEFAULT_MAX_WEIGHT",
    "DEFAULT_RISK_AUDIT_DB",
    "DEFAULT_WEIGHT_METHOD",
    "PositionRiskInfo",
    "RiskManager",
    "RiskManagerState",
    "risk_manager",
]
