import structlog
logger = structlog.get_logger(__name__)
from typing import Any
import gc

import polars as pl

from services.backtest.engine import BacktestEngine
from services.backtest.walk_forward import WalkForwardEngine
from services.core.alpha_engine import AlphaEngine
from services.core.risk_manager import RiskManager


def run_final() -> Any:
    """Otomatik eklendi."""
    logger.info("\n" + "=" * 70)
    logger.info("🚀 ALPHA BIST - CORE QUANT ENGINE (Ablation + Optuna + EW)")
    logger.info("=" * 70)

    # Kötü göstergeler (bad_features) artık AlphaEngine içinde varsayılan olarak siliniyor.
    engine = AlphaEngine()

    logger.info("?? Fetching 10-year data...")
    market_data, bm_df, sector_map = engine.fetch_data("2015-01-01", "2024-11-03")
    common_dates = list(sorted([d.strftime("%Y-%m-%d") for d in bm_df.index]))

    wf = WalkForwardEngine(train_days=252, test_days=63, step_days=63, purge_days=5, embargo_days=5)

    RiskManager()
    all_signals = []

    folds = wf.create_folds(common_dates)

    for i, fold in enumerate(folds, 1):
        logger.info(
            f"\n? FOLD {i}/{len(folds)} | Train: {fold['train_start']} -> {fold['train_end']} | Test: {fold['test_start']} -> {fold['test_end']}"
        )
        logger.info("  - Optuna & Egitiliyor...")

        success = engine.train(market_data, bm_df, sector_map, fold["train_start"], fold["train_end"], optimize=True)

        if not success:
            continue

        logger.info(f"  - Tahmin Uretiliyor (Test_Start: {fold['test_start']})...")
        try:
            preds = engine.predict(market_data, bm_df, sector_map, fold["test_start"])
            top_picks = preds[:10]

            if top_picks:
                for pick in top_picks:
                    ticker = pick["ticker"]
                    adj_weight = 0.10  # Equal Weight

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
                logger.info("  ? Sinyaller eklendi.")
        except Exception as e:
            logger.info(f"  ? Hata: {e}")

        gc.collect()

    logger.info("\n? Sinyal Uretimi Tamamlandi.")

    price_data_formatted = {}
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
        initial_capital=100000.0,
        commission_rate=0.001,
        slippage_pct=0.002,
        dump_ledger=False,
        stop_loss_pct=1.0,  # NO STOP
        trailing_stop_pct=1.0,  # NO STOP
        market_regime=1.0,
    )

    metrics = report.metrics

    logger.info("\n" + "=" * 70)
    logger.info("?? ALPHA BIST PHASE 18 - THE HOLY GRAIL (ABLATED + OPTUNA)")
    logger.info("=" * 70)
    logger.info(f"CAGR                : %{metrics.cagr_pct:.2f}")
    logger.info(f"Max Drawdown        : -%{metrics.max_drawdown_pct:.2f}")
    logger.info(f"Sharpe Ratio        : {metrics.sharpe_ratio:.2f}")
    logger.info(f"Sortino Ratio       : {metrics.sortino_ratio:.2f}")
    logger.info(f"Win Rate            : %{metrics.win_rate * 100:.1f}")
    logger.info(f"Trade Count         : {metrics.total_trades}")
    logger.info(f"Profit Factor       : {metrics.profit_factor:.2f}")
    logger.info("=" * 70)


if __name__ == "__main__":
    run_final()
