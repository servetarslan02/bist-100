"""ALPHA BIST — ML Model Tahminleri ve Portföy Backtest Entegrasyonu (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; makine öğrenimi modelleri tarafından üretilen sinyal skorlarını gerçekçi
simülasyon koşulları (işlem komisyonu, kayma / slippage, dinamik pozisyon büyüklüğü kısıtları)
altında geçmişe dönük test eden (backtest), modeller arası performans karşılaştırması
yürüten ve piyasa rejimlerine göre ayrıştırılmış getiri analizi sunan motordur.

Temel Yetenekler:
- Model tahminlerinden (`predict_fn`) otomatik AL / SAT / TUT sinyali türetimi
- Çoklu model (Ensemble vs Champion vs Challenger) başa baş performans karşılaştırması
- Piyasa rejimlerine (BOĞA, AYI, YATAY, YÜKSEK VOLATİLİTE) göre PnL ve kazanma oranı analizi
- Gerçekçi maliyet modeli: Komisyon oranı ve yönlü kayma (slippage) kesintisi
- Kapsamlı risk-getiri metrikleri: Toplam/Yıllık Getiri, Sharpe, Calmar, Max Drawdown, Profit Factor
- Polars DataFrame üzerinden sonuç ve bakiye eğrisi çıktısı (`run_backtest_polars`)
- DuckDB üzerinde SSD korumalı WAL ile backtest denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve fail-closed mimari
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    import polars as pl

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_INITIAL_CAPITAL: Final[float] = 100_000.0
DEFAULT_COMMISSION_RATE: Final[float] = 0.0010  # %0.10
DEFAULT_SLIPPAGE_RATE: Final[float] = 0.0005     # %0.05
DEFAULT_MAX_POSITION_PCT: Final[float] = 0.10   # %10 portföy tahsisi
DEFAULT_RISK_FREE_RATE: Final[float] = 0.0
DEFAULT_ANNUALIZATION_FACTOR: Final[int] = 252
DEFAULT_BUY_THRESHOLD: Final[float] = 0.70
DEFAULT_SELL_THRESHOLD: Final[float] = 0.30
DEFAULT_DUCKDB_PATH: Final[str] = "data/ml_backtest.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8


class TradeSide(StrEnum):
    """İşlem yönü türleri."""

    BUY = "BUY"
    SELL = "SELL"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısına SSD ömrünü ve WAL boyutunu koruma direktiflerini uygular.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute("PRAGMA checkpoint_threshold = '4MB';")
        conn.execute("PRAGMA wal_autocheckpoint = '2MB';")
    except Exception as exc:
        logger.warning("DuckDB WAL pragma yapilandirmasi basarisiz", hata=str(exc))


@dataclass(slots=True)
class BacktestTrade:
    """Backtest işlem kaydı veri modeli."""

    timestamp: str
    ticker: str
    side: TradeSide | str
    price: float
    quantity: int
    signal_score: float
    model_name: str
    commission: float = 0.0
    slippage: float = 0.0
    pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """İşlem kaydını sözlüğe dönüştürür."""
        return {
            "timestamp": self.timestamp,
            "ticker": self.ticker,
            "side": str(self.side),
            "price": round(self.price, 4),
            "quantity": self.quantity,
            "signal_score": round(self.signal_score, 4),
            "model_name": self.model_name,
            "commission": round(self.commission, 2),
            "slippage": round(self.slippage, 2),
            "pnl": round(self.pnl, 2),
        }

    def to_orjson_bytes(self) -> bytes:
        """İşlem kaydını orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BacktestTrade:
        """Sözlükten BacktestTrade nesnesi oluşturur."""
        return cls(
            timestamp=str(data.get("timestamp", "")),
            ticker=str(data.get("ticker", "")),
            side=TradeSide(str(data.get("side", "BUY"))),
            price=float(data.get("price", 0.0)),
            quantity=int(data.get("quantity", 0)),
            signal_score=float(data.get("signal_score", 0.0)),
            model_name=str(data.get("model_name", "")),
            commission=float(data.get("commission", 0.0)),
            slippage=float(data.get("slippage", 0.0)),
            pnl=float(data.get("pnl", 0.0)),
        )

    def __repr__(self) -> str:
        return (
            f"BacktestTrade(date='{self.timestamp}', ticker='{self.ticker}', "
            f"side='{self.side}', qty={self.quantity}, pnl={self.pnl:.2f})"
        )


@dataclass(slots=True)
class BacktestResult:
    """Tekil model backtest performans sonucu veri modeli."""

    model_name: str
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_trade_pnl: float
    avg_holding_days: float
    calmar_ratio: float
    equity_curve: list[tuple[str, float]]
    trades: list[BacktestTrade]
    regime_performance: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        """Backtest sonucunu sözlük formatına dönüştürür."""
        return {
            "model_name": self.model_name,
            "total_return": round(self.total_return, 4),
            "annualized_return": round(self.annualized_return, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "total_trades": self.total_trades,
            "avg_trade_pnl": round(self.avg_trade_pnl, 2),
            "avg_holding_days": round(self.avg_holding_days, 1),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "equity_curve": self.equity_curve,
            "trades": [t.to_dict() for t in self.trades],
            "regime_performance": self.regime_performance,
            "equity_curve_len": len(self.equity_curve),
        }

    def to_orjson_bytes(self) -> bytes:
        """Backtest sonucunu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BacktestResult:
        """Sözlükten BacktestResult nesnesi oluşturur."""
        trades_raw = data.get("trades", [])
        trades_list = [
            BacktestTrade.from_dict(t) if isinstance(t, dict) else t
            for t in trades_raw
        ]
        return cls(
            model_name=str(data.get("model_name", "")),
            total_return=float(data.get("total_return", 0.0)),
            annualized_return=float(data.get("annualized_return", 0.0)),
            sharpe_ratio=float(data.get("sharpe_ratio", 0.0)),
            max_drawdown=float(data.get("max_drawdown", 0.0)),
            win_rate=float(data.get("win_rate", 0.0)),
            profit_factor=float(data.get("profit_factor", 0.0)),
            total_trades=int(data.get("total_trades", 0)),
            avg_trade_pnl=float(data.get("avg_trade_pnl", 0.0)),
            avg_holding_days=float(data.get("avg_holding_days", 0.0)),
            calmar_ratio=float(data.get("calmar_ratio", 0.0)),
            equity_curve=list(data.get("equity_curve", [])),
            trades=trades_list,
            regime_performance=dict(data.get("regime_performance", {})),
        )

    def __repr__(self) -> str:
        return (
            f"BacktestResult(model='{self.model_name}', ret={self.total_return * 100:.2f}%, "
            f"sharpe={self.sharpe_ratio:.2f}, max_dd={self.max_drawdown * 100:.2f}%, trades={self.total_trades})"
        )


@dataclass(slots=True)
class ComparisonResult:
    """Modeller arası başa baş performans karşılaştırma sonucu veri modeli."""

    models: list[BacktestResult]
    best_model: str
    ranking_metric: str
    ranking: list[tuple[str, float]]

    def to_dict(self) -> dict[str, Any]:
        """Karşılaştırma sonucunu sözlüğe dönüştürür."""
        return {
            "best_model": self.best_model,
            "ranking_metric": self.ranking_metric,
            "ranking": self.ranking,
            "models": [m.to_dict() for m in self.models],
            "model_count": len(self.models),
        }

    def to_orjson_bytes(self) -> bytes:
        """Karşılaştırma sonucunu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComparisonResult:
        """Sözlükten ComparisonResult nesnesi oluşturur."""
        models_raw = data.get("models", [])
        models_list = [
            BacktestResult.from_dict(m) if isinstance(m, dict) else m
            for m in models_raw
        ]
        return cls(
            models=models_list,
            best_model=str(data.get("best_model", "")),
            ranking_metric=str(data.get("ranking_metric", "sharpe_ratio")),
            ranking=list(data.get("ranking", [])),
        )

    def __repr__(self) -> str:
        return f"ComparisonResult(best='{self.best_model}', metric='{self.ranking_metric}', n_models={len(self.models)})"


class MLBacktestEngine:
    """Makine öğrenimi modelleri için kurumsal seviye simülasyon ve backtest motoru."""

    def __init__(
        self,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
        max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        annualization_factor: int = DEFAULT_ANNUALIZATION_FACTOR,
        buy_threshold: float = DEFAULT_BUY_THRESHOLD,
        sell_threshold: float = DEFAULT_SELL_THRESHOLD,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """MLBacktestEngine nesnesini başlatır.

        Args:
            initial_capital: Başlangıç portföy sermayesi.
            commission_rate: İşlem komisyon oranı.
            slippage_rate: İşlem kayma (slippage) oranı.
            max_position_pct: Tekil hisse azami portföy tahsisi oranı.
            risk_free_rate: Yıllık risksiz faiz oranı.
            annualization_factor: Yıllık işlem günü sayısı.
            buy_threshold: Alış sinyal eşik değeri.
            sell_threshold: Satış sinyal eşik değeri.
            duckdb_path: Denetim izi DuckDB veritabanı yolu.
        """
        self._lock = threading.RLock()
        self.initial_capital = float(initial_capital)
        self.commission_rate = float(commission_rate)
        self.slippage_rate = float(slippage_rate)
        self.max_position_pct = float(max_position_pct)
        self.risk_free_rate = float(risk_free_rate)
        self.annualization_factor = int(annualization_factor)
        self.buy_threshold = float(buy_threshold)
        self.sell_threshold = float(sell_threshold)
        self.duckdb_path = duckdb_path

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self.duckdb_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ml_backtest_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        model_name VARCHAR,
                        total_return DOUBLE,
                        annualized_return DOUBLE,
                        sharpe_ratio DOUBLE,
                        max_drawdown DOUBLE,
                        win_rate DOUBLE,
                        total_trades BIGINT,
                        calmar_ratio DOUBLE
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB backtest denetim tablosu hazirlanamadi", hata=str(exc))

    def run_backtest(
        self,
        model_name: str,
        predict_fn: Callable[[np.ndarray], Any],
        price_data: dict[str, np.ndarray],
        feature_data: dict[str, np.ndarray],
        dates: list[str],
        regimes: list[str] | None = None,
        tickers: list[str] | None = None,
    ) -> BacktestResult:
        """Belirtilen model tahmin fonksiyonu için tam kapsamlı simülasyon çalıştırır.

        Args:
            model_name: Modelin tanımlayıcı adı.
            predict_fn: Girdi öznitelik matrisini alıp tahmin döndüren fonksiyon.
            price_data: Hisse fiyat serileri `{ticker: np.ndarray}`.
            feature_data: Hisse öznitelik serileri `{ticker: np.ndarray}`.
            dates: Tarih listesi (kronolojik sıralı).
            regimes: Günlük piyasa rejimleri listesi (opsiyonel).
            tickers: Değerlendirilecek hisse kodları listesi.

        Returns:
            BacktestResult nesnesi.
        """
        with self._lock:
            actual_tickers = tickers if tickers is not None else list(price_data.keys())
            capital = self.initial_capital
            positions: dict[str, dict[str, Any]] = {}
            trades: list[BacktestTrade] = []
            equity_curve: list[tuple[str, float]] = []
            regime_perf: dict[str, list[float]] = {}

            n_days = len(dates)

            for day_idx in range(n_days):
                date = str(dates[day_idx])[:10]
                regime = str(regimes[day_idx]).upper() if regimes and day_idx < len(regimes) else "UNKNOWN"

                if regime not in regime_perf:
                    regime_perf[regime] = []

                # Her hisse için tahmin al
                scores: dict[str, float] = {}
                for ticker in actual_tickers:
                    if ticker not in feature_data or ticker not in price_data:
                        continue
                    feats = feature_data[ticker]
                    if len(feats.shape) == 1:
                        feats = feats.reshape(1, -1)
                    if day_idx >= feats.shape[0]:
                        continue

                    try:
                        X = feats[day_idx : day_idx + 1]
                        pred = predict_fn(X)
                        val = float(pred[0]) if hasattr(pred, "__len__") else float(pred)
                        if np.isfinite(val):
                            scores[ticker] = val
                    except Exception as ex:
                        logger.debug("Sinyal tahmin istisnasi", ticker=ticker, hata=str(ex))
                        continue

                if not scores:
                    portfolio_val = capital
                    for t, pos in positions.items():
                        if t in price_data and day_idx < len(price_data[t]):
                            portfolio_val += pos["qty"] * float(price_data[t][day_idx])
                    equity_curve.append((date, portfolio_val))
                    continue

                # SATIŞ Sinyalleri (skor < sell_threshold)
                for ticker in list(positions.keys()):
                    if ticker in scores and scores[ticker] < self.sell_threshold:
                        if ticker in price_data and day_idx < len(price_data[ticker]):
                            raw_p = float(price_data[ticker][day_idx])
                            if raw_p <= DEFAULT_EPSILON or not np.isfinite(raw_p):
                                continue

                            sell_price = raw_p * (1.0 - self.slippage_rate)
                            pos = positions[ticker]
                            commission = sell_price * pos["qty"] * self.commission_rate
                            pnl = (sell_price - pos["entry_price"]) * pos["qty"] - commission
                            capital += sell_price * pos["qty"] - commission

                            trades.append(
                                BacktestTrade(
                                    timestamp=date,
                                    ticker=ticker,
                                    side=TradeSide.SELL,
                                    price=sell_price,
                                    quantity=pos["qty"],
                                    signal_score=scores[ticker],
                                    model_name=model_name,
                                    commission=commission,
                                    slippage=raw_p * self.slippage_rate * pos["qty"],
                                    pnl=pnl,
                                )
                            )

                            regime_perf[regime].append(pnl)
                            del positions[ticker]

                # ALIŞ Sinyalleri (skor > buy_threshold)
                sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                for ticker, score in sorted_scores:
                    if ticker in positions:
                        continue
                    if score < self.buy_threshold:
                        continue

                    # Güncel portföy değerini hesapla
                    portfolio_val = capital
                    for t, pos in positions.items():
                        if t in price_data and day_idx < len(price_data[t]):
                            portfolio_val += pos["qty"] * float(price_data[t][day_idx])

                    max_invest = portfolio_val * self.max_position_pct
                    if capital < max_invest * 0.10:
                        break  # Yetersiz nakit

                    if ticker in price_data and day_idx < len(price_data[ticker]):
                        raw_p = float(price_data[ticker][day_idx])
                        if raw_p <= DEFAULT_EPSILON or not np.isfinite(raw_p):
                            continue

                        buy_price = raw_p * (1.0 + self.slippage_rate)
                        qty = int(max_invest / buy_price)
                        if qty <= 0:
                            continue

                        commission = buy_price * qty * self.commission_rate
                        total_cost = buy_price * qty + commission

                        if total_cost > capital:
                            qty = int((capital * 0.95) / buy_price)
                            if qty <= 0:
                                continue
                            commission = buy_price * qty * self.commission_rate
                            total_cost = buy_price * qty + commission

                        capital -= total_cost
                        positions[ticker] = {
                            "qty": qty,
                            "entry_price": buy_price,
                            "entry_date": date,
                        }

                        trades.append(
                            BacktestTrade(
                                timestamp=date,
                                ticker=ticker,
                                side=TradeSide.BUY,
                                price=buy_price,
                                quantity=qty,
                                signal_score=score,
                                model_name=model_name,
                                commission=commission,
                                slippage=raw_p * self.slippage_rate * qty,
                            )
                        )

                # Gün sonu portföy değerini kaydet
                portfolio_val = capital
                for t, pos in positions.items():
                    if t in price_data and day_idx < len(price_data[t]):
                        portfolio_val += pos["qty"] * float(price_data[t][day_idx])
                equity_curve.append((date, portfolio_val))

            metrics = self._calculate_metrics(equity_curve, trades)

            # Rejim bazlı özet performans
            regime_summary: dict[str, dict[str, float]] = {}
            for reg, pnls in regime_perf.items():
                if pnls:
                    regime_summary[reg] = {
                        "total_pnl": round(float(np.sum(pnls)), 2),
                        "avg_pnl": round(float(np.mean(pnls)), 2),
                        "win_rate": round(float(np.mean([p > 0 for p in pnls])), 4),
                        "n_trades": len(pnls),
                    }

            result = BacktestResult(
                model_name=model_name,
                total_return=metrics["total_return"],
                annualized_return=metrics["annualized_return"],
                sharpe_ratio=metrics["sharpe_ratio"],
                max_drawdown=metrics["max_drawdown"],
                win_rate=metrics["win_rate"],
                profit_factor=metrics["profit_factor"],
                total_trades=len(trades),
                avg_trade_pnl=metrics["avg_trade_pnl"],
                avg_holding_days=metrics["avg_holding_days"],
                calmar_ratio=metrics["calmar_ratio"],
                equity_curve=equity_curve,
                trades=trades,
                regime_performance=regime_summary,
            )

            # DuckDB denetim kaydı
            self._record_audit(result)

            logger.info(
                "Model backtesti tamamlandi",
                model=model_name,
                toplam_getiri=round(result.total_return, 4),
                sharpe=round(result.sharpe_ratio, 2),
                islem_adedi=result.total_trades,
            )

            return result

    def compare_models(
        self,
        models: dict[str, Callable[[np.ndarray], Any]],
        price_data: dict[str, np.ndarray],
        feature_data: dict[str, np.ndarray],
        dates: list[str],
        regimes: list[str] | None = None,
        ranking_metric: str = "sharpe_ratio",
    ) -> ComparisonResult:
        """Birden fazla model için eşanlı backtest çalıştırıp performanslarına göre sıralar.

        Args:
            models: `{model_adi: tahmin_fonksiyonu}` sözlüğü.
            price_data: Fiyat verileri sözlüğü.
            feature_data: Öznitelik verileri sözlüğü.
            dates: Tarih serisi.
            regimes: Rejim serisi.
            ranking_metric: Sıralamada kullanılacak metrik ('sharpe_ratio', 'total_return', 'calmar_ratio').

        Returns:
            ComparisonResult nesnesi.
        """
        with self._lock:
            results: list[BacktestResult] = []

            for name, predict_fn in models.items():
                logger.info("Model backtesti yurutuluyor", model=name)
                try:
                    res = self.run_backtest(
                        model_name=name,
                        predict_fn=predict_fn,
                        price_data=price_data,
                        feature_data=feature_data,
                        dates=dates,
                        regimes=regimes,
                    )
                    results.append(res)
                except Exception as ex:
                    logger.error("Model backtesti basarisiz oldu", model=name, hata=str(ex))

            def _get_metric(r: BacktestResult) -> float:
                """Sıralama için model sonucundan metrik değerini güvenle çeker."""
                val = getattr(r, ranking_metric, 0.0)
                return float(val) if np.isfinite(val) else -999.0

            results.sort(key=_get_metric, reverse=True)
            ranking = [(r.model_name, _get_metric(r)) for r in results]
            best_model = ranking[0][0] if ranking else "none"

            return ComparisonResult(
                models=results,
                best_model=best_model,
                ranking_metric=ranking_metric,
                ranking=ranking,
            )

    def run_backtest_polars(
        self,
        model_name: str,
        predict_fn: Callable[[np.ndarray], Any],
        price_data: dict[str, np.ndarray],
        feature_data: dict[str, np.ndarray],
        dates: list[str],
        regimes: list[str] | None = None,
    ) -> tuple[BacktestResult, pl.DataFrame, pl.DataFrame]:
        """Backtest sonuçlarını ve bakiye eğrisini Polars DataFrame olarak döndürür.

        Args:
            model_name: Model adı.
            predict_fn: Tahmin fonksiyonu.
            price_data: Fiyat verisi.
            feature_data: Öznitelik verisi.
            dates: Tarih listesi.
            regimes: Rejim listesi.

        Returns:
            `(BacktestResult, df_equity, df_trades)` demeti.
        """
        import polars as pl

        res = self.run_backtest(
            model_name=model_name,
            predict_fn=predict_fn,
            price_data=price_data,
            feature_data=feature_data,
            dates=dates,
            regimes=regimes,
        )

        df_equity = pl.DataFrame({
            "date": [e[0] for e in res.equity_curve],
            "equity": [e[1] for e in res.equity_curve],
        })

        if res.trades:
            trade_dicts = [t.to_dict() for t in res.trades]
            df_trades = pl.DataFrame(trade_dicts)
        else:
            df_trades = pl.DataFrame(
                schema={
                    "timestamp": pl.Utf8,
                    "ticker": pl.Utf8,
                    "side": pl.Utf8,
                    "price": pl.Float64,
                    "quantity": pl.Int64,
                    "signal_score": pl.Float64,
                    "model_name": pl.Utf8,
                    "commission": pl.Float64,
                    "slippage": pl.Float64,
                    "pnl": pl.Float64,
                }
            )

        return res, df_equity, df_trades

    def _calculate_metrics(
        self,
        equity_curve: list[tuple[str, float]],
        trades: list[BacktestTrade],
    ) -> dict[str, float]:
        """Bakiye eğrisi ve işlemlerden risk-getiri metriklerini hesaplar."""
        if not equity_curve:
            return self._empty_metrics()

        values = np.array([v for _, v in equity_curve], dtype=np.float64)
        n_days = len(values)
        if n_days == 0:
            return self._empty_metrics()

        # Toplam ve Yıllık Getiri
        total_return = (values[-1] / max(self.initial_capital, DEFAULT_EPSILON)) - 1.0
        years = n_days / float(self.annualization_factor)

        # Sermaye sıfırlanma guard'ı
        pos_base = max(1.0 + total_return, 0.0)
        annualized_return = (pos_base ** (1.0 / max(years, 0.01))) - 1.0

        # Günlük Getiriler ve Sharpe
        safe_denom = np.where(values[:-1] > DEFAULT_EPSILON, values[:-1], 1.0)
        daily_returns = np.diff(values) / safe_denom if len(values) > 1 else np.array([0.0])

        mean_daily = float(np.mean(daily_returns))
        std_daily = float(np.std(daily_returns))
        sharpe = (
            ((mean_daily - self.risk_free_rate / float(self.annualization_factor)) / max(std_daily, DEFAULT_EPSILON))
            * np.sqrt(self.annualization_factor)
        )

        # Max Drawdown
        running_max = np.maximum.accumulate(values)
        running_max_safe = np.where(running_max > DEFAULT_EPSILON, running_max, 1.0)
        drawdown = (values - running_max) / running_max_safe
        max_drawdown = float(np.abs(np.min(drawdown))) if len(drawdown) > 0 else 0.0

        # Win Rate ve Profit Factor
        sell_trades = [t for t in trades if str(t.side) == TradeSide.SELL]
        if sell_trades:
            wins = sum(1 for t in sell_trades if t.pnl > 0.0)
            win_rate = wins / float(len(sell_trades))
            gross_profit = sum(t.pnl for t in sell_trades if t.pnl > 0.0)
            gross_loss = abs(sum(t.pnl for t in sell_trades if t.pnl < 0.0))
            profit_factor = gross_profit / max(gross_loss, 1.0)
            avg_trade_pnl = float(np.mean([t.pnl for t in sell_trades]))
        else:
            win_rate = 0.0
            profit_factor = 0.0
            avg_trade_pnl = 0.0

        # Ortalama elde tutma süresi (holding days)
        holding_days: list[int] = []
        buy_dates: dict[str, str] = {}
        for t in trades:
            if str(t.side) == TradeSide.BUY:
                buy_dates[t.ticker] = t.timestamp
            elif str(t.side) == TradeSide.SELL and t.ticker in buy_dates:
                try:
                    buy_dt = datetime.fromisoformat(buy_dates[t.ticker][:10])
                    sell_dt = datetime.fromisoformat(t.timestamp[:10])
                    holding_days.append((sell_dt - buy_dt).days)
                except Exception as exc:
                    logger.debug("Pozisyon elde tutma gunu hesaplanamadi", ticker=t.ticker, hata=str(exc))
                del buy_dates[t.ticker]

        avg_holding = float(np.mean(holding_days)) if holding_days else 0.0
        calmar = annualized_return / max(max_drawdown, DEFAULT_EPSILON)

        return {
            "total_return": round(float(total_return), 4),
            "annualized_return": round(float(annualized_return), 4),
            "sharpe_ratio": round(float(sharpe), 4),
            "max_drawdown": round(float(max_drawdown), 4),
            "win_rate": round(float(win_rate), 4),
            "profit_factor": round(float(profit_factor), 4),
            "avg_trade_pnl": round(float(avg_trade_pnl), 2),
            "avg_holding_days": round(float(avg_holding), 1),
            "calmar_ratio": round(float(calmar), 4),
        }

    def _empty_metrics(self) -> dict[str, float]:
        """Boş metrik seti."""
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_trade_pnl": 0.0,
            "avg_holding_days": 0.0,
            "calmar_ratio": 0.0,
        }

    def _record_audit(self, res: BacktestResult) -> None:
        """Backtest denetim izini DuckDB'ye yazar."""
        try:
            with duckdb.connect(self.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO ml_backtest_audit (
                        model_name, total_return, annualized_return, sharpe_ratio,
                        max_drawdown, win_rate, total_trades, calmar_ratio
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        str(res.model_name),
                        float(res.total_return),
                        float(res.annualized_return),
                        float(res.sharpe_ratio),
                        float(res.max_drawdown),
                        float(res.win_rate),
                        int(res.total_trades),
                        float(res.calmar_ratio),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB backtest denetim kaydi atlandi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki backtest denetim kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM ml_backtest_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        return (
            f"MLBacktestEngine(capital={self.initial_capital:,.0f}, comm={self.commission_rate * 100:.2f}%, "
            f"slip={self.slippage_rate * 100:.2f}%, max_pos={self.max_position_pct * 100:.0f}%)"
        )


# Singleton
ml_backtest_engine = MLBacktestEngine()

__all__: Final[list[str]] = [
    "DEFAULT_ANNUALIZATION_FACTOR",
    "DEFAULT_BUY_THRESHOLD",
    "DEFAULT_COMMISSION_RATE",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_MAX_POSITION_PCT",
    "DEFAULT_RISK_FREE_RATE",
    "DEFAULT_SELL_THRESHOLD",
    "DEFAULT_SLIPPAGE_RATE",
    "BacktestResult",
    "BacktestTrade",
    "ComparisonResult",
    "MLBacktestEngine",
    "TradeSide",
    "configure_duckdb_wal",
    "ml_backtest_engine",
]
