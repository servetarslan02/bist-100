import structlog

logger = structlog.get_logger(__name__)
"""
ALPHA BIST — Canlı Piyasa ve Model Denetim Kanıtı
"""
from services.scanner.bist_ml_scanner import BistMLScanner


def audit(sample_size: int = 15) -> None:
    """Canlı TradingView ve BIST tarayıcı verilerinden dinamik evren örneklemini denetler ve metrikleri raporlar."""
    s = BistMLScanner()
    items = s._fetch_live_scanner_data()
    item_map = {it['name']: it for it in items}

    from services.ingestion.bist_universe import bist_universe

    all_bist = bist_universe.BIST_ALL_TICKERS
    available_tickers = [sym for sym in all_bist if sym in item_map]
    check_tickers = available_tickers[:sample_size] if available_tickers else list(item_map.keys())[:sample_size]
    logger.info('=== GERÇEK PİYASA VERİSİ DENETİM KANITI (CANLI API ÇIKTISI) ===')
    logger.info(f"{'HİSSE':<7} | {'FİYAT':<8} | {'DEĞİŞİM':<8} | {'RVOL':<6} | {'ATR (%)':<8} | {'F/K':<7} | {'PD/DD':<7} | {'ROE (%)':<8} | {'NET MARJ (%)':<12}")
    logger.info('-' * 95)
    for sym in check_tickers:
        d = item_map.get(sym)
        if d:
            p = float(d.get('close', 0.0))
            chg = float(d.get('change', 0.0))
            rvol = float(d.get('relative_volume_10d_calc', 1.0))
            atr_pct = (float(d.get('ATR', 0.0)) / max(p, 1e-4)) * 100.0
            pe = d.get('price_earnings_ttm')
            pb = d.get('price_book_ratio')
            roe = d.get('return_on_equity_fq')
            margin = d.get('net_margin_ttm')
            pe_s = f"{pe:.1f}" if pe is not None else "N/A"
            pb_s = f"{pb:.2f}" if pb is not None else "N/A"
            roe_s = f"%{roe:.1f}" if roe is not None else "N/A"
            mar_s = f"%{margin:.1f}" if margin is not None else "N/A"
            logger.info(f"{sym:<7} | {p:>7.2f} TL | %{chg:>+6.2f} | {rvol:>5.2f}x | %{atr_pct:>6.2f} | {pe_s:>7} | {pb_s:>7} | {roe_s:>8} | {mar_s:>12}")

if __name__ == '__main__':
    audit()
