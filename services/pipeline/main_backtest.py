"""ALPHA BIST — Core Quant Engine Backtest Yürütücüsü.

Yürütülen adımlar:
1. WalkForwardEngine ile eğitim/test pencerelerinin (folds) oluşturulması.
2. AlphaEngine ile Optuna hiperparametre optimizasyonu ve model eğitimi.
3. Model tahminlerinin ve portföy ağırlıklarının hesaplanması.
4. BacktestEngine ile komisyon, kayma ve mikro-yapı simülasyonu.
"""

import gc
from typing import Any

import polars as pl
import structlog

from services.backtest.execution_engine import BacktestEngine
from services.backtest.walk_forward import WalkForwardEngine
from services.core.alpha_engine import AlphaEngine
from services.core.risk_manager import RiskManager

logger = structlog.get_logger(__name__)

# Varsayılan Sabitler
DEFAULT_INITIAL_CAPITAL: float = 100_000.0
DEFAULT_COMMISSION_RATE: float = 0.001
DEFAULT_SLIPPAGE_PCT: float = 0.002
DEFAULT_TOP_PICKS: int = 10
DEFAULT_TRAIN_DAYS: int = 252
DEFAULT_TEST_DAYS: int = 63
DEFAULT_STEP_DAYS: int = 63
DEFAULT_PURGE_DAYS: int = 5
DEFAULT_EMBARGO_DAYS: int = 5
DEFAULT_BACKTEST_START_DATE: str = "2015-01-01"
DEFAULT_BACKTEST_END_DATE: str = "2024-11-03"


def run_final() -> Any:
    """Nihai Walk-Forward Optuna ve Ablasyon backtest döngüsünü çalıştırır.

    Walk-Forward validasyonu kullanarak geçmiş veriler üzerinde Optuna destekli
    AlphaEngine modelini eğitir, her pencere için tahmin üretir ve BacktestEngine
    aracılığıyla nihai performans metriklerini hesaplar.

    Returns:
        Any: Backtest sonuç raporu ve metrikleri (BacktestReport).

    Raises:
        RuntimeError: Veri çekme veya yürütme sırasında kritik hata oluşursa.
    """
    logger.info("Alpha BIST Core Quant Engine Backtest baslatiliyor", engine="AlphaEngine")

    # Kötü göstergeler (bad_features) artık AlphaEngine içinde varsayılan olarak siliniyor.
    engine = AlphaEngine()

    logger.info("Piyasa verileri cekiliyor", start_date=DEFAULT_BACKTEST_START_DATE, end_date=DEFAULT_BACKTEST_END_DATE)
    market_data, bm_df, sector_map = engine.fetch_data(DEFAULT_BACKTEST_START_DATE, DEFAULT_BACKTEST_END_DATE)
    common_dates = list(sorted([d.strftime("%Y-%m-%d") for d in bm_df.index]))

    wf = WalkForwardEngine(
        train_days=DEFAULT_TRAIN_DAYS,
        test_days=DEFAULT_TEST_DAYS,
        step_days=DEFAULT_STEP_DAYS,
        purge_days=DEFAULT_PURGE_DAYS,
        embargo_days=DEFAULT_EMBARGO_DAYS,
    )

    RiskManager()
    all_signals: list[dict[str, Any]] = []

    folds = wf.create_folds(common_dates)

    for i, fold in enumerate(folds, 1):
        logger.info(
            "Fold egitimi baslatiliyor",
            fold_index=i,
            total_folds=len(folds),
            train_start=fold["train_start"],
            train_end=fold["train_end"],
            test_start=fold["test_start"],
            test_end=fold["test_end"],
        )

        success = engine.train(market_data, bm_df, sector_map, fold["train_start"], fold["train_end"], optimize=True)

        if not success:
            logger.warning("Fold egitimi basarisiz oldu, atlandi", fold_index=i)
            continue

        logger.info("Fold icin tahminler uretiliyor", test_start=fold["test_start"])
        try:
            preds = engine.predict(market_data, bm_df, sector_map, fold["test_start"])
            top_picks = preds[:DEFAULT_TOP_PICKS]

            if top_picks:
                adj_weight = 1.0 / len(top_picks)
                for pick in top_picks:
                    ticker = pick["ticker"]

                    df_t = market_data.get(ticker)
                    if df_t is None:
                        continue

                    t_start = pl.Series(fold["test_start"])
                    t_end = pl.Series(fold["test_end"])
                    df_test = df_t[(df_t.index >= t_start) & (df_t.index <= t_end)]

                    if not df_test.empty:
                        all_signals.append(
                            {
                                "date": str(df_test.index[0].date()),
                                "ticker": ticker,
                                "action": "BUY",
                                "score": pick["score"],
                                "weight": adj_weight,
                            }
                        )
                        all_signals.append(
                            {
                                "date": str(df_test.index[-1].date()),
                                "ticker": ticker,
                                "action": "SELL",
                                "score": pick["score"],
                                "weight": adj_weight,
                            }
                        )
                logger.info("Fold sinyalleri kaydedildi", fold_index=i, signal_count=len(top_picks) * 2)
        except Exception as e:
            logger.error("Fold tahmin uretiminde hata olustu", fold_index=i, error=str(e), exc_info=True)

        gc.collect()

    logger.info("Sinyal uretimi tamamlandi", total_signals=len(all_signals))

    price_data_formatted: dict[str, list[dict[str, Any]]] = {}
    for ticker, df_t in market_data.items():
        if df_t.empty:
            continue
        rows = []
        for d, row in df_t.iterrows():
            rows.append(
                {
                    "date": str(d.date()) if hasattr(d, "date") else str(d)[:10],
                    "close": float(row.get("Close", 0.0)),
                    "volume": float(row.get("Volume", 0.0)),
                }
            )
        price_data_formatted[ticker] = rows

    backtest = BacktestEngine()
    report = backtest.run_backtest(
        strategy_name="Phase18_Final",
        price_data=price_data_formatted,
        signals=all_signals,
        initial_capital=DEFAULT_INITIAL_CAPITAL,
        commission_rate=DEFAULT_COMMISSION_RATE,
        slippage_pct=DEFAULT_SLIPPAGE_PCT,
        dump_ledger=False,
        stop_loss_pct=1.0,  # NO STOP
        trailing_stop_pct=1.0,  # NO STOP
        market_regime=1.0,
    )

    metrics = report.metrics

    logger.info(
        "Alpha BIST Walk-Forward Backtest tamamlandi",
        cagr_pct=metrics.cagr_pct,
        max_drawdown_pct=metrics.max_drawdown_pct,
        sharpe_ratio=metrics.sharpe_ratio,
        sortino_ratio=metrics.sortino_ratio,
        win_rate_pct=metrics.win_rate * 100,
        trade_count=metrics.total_trades,
        profit_factor=metrics.profit_factor,
    )

    return report


__all__ = [
    "DEFAULT_BACKTEST_END_DATE",
    "DEFAULT_BACKTEST_START_DATE",
    "DEFAULT_COMMISSION_RATE",
    "DEFAULT_EMBARGO_DAYS",
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_PURGE_DAYS",
    "DEFAULT_SLIPPAGE_PCT",
    "DEFAULT_STEP_DAYS",
    "DEFAULT_TEST_DAYS",
    "DEFAULT_TOP_PICKS",
    "DEFAULT_TRAIN_DAYS",
    "run_final",
]
