"""
ALPHA BIST — 7 Motor Feature Engine v3.0

ROADMAP v3.0 FAZ 2:
- 100+ feature hesaplama
- Mask-aware hesaplama
- Yeni motorlar: Mean Reversion, Seasonality, Options Flow
- Cross-sectional entegrasyon

Her motor bağımsız çalışır, birbirinin sonucunu etkilemez.
Motor çıktıları ranking modeline girdi olarak kullanılır.
"""

from collections import defaultdict
from datetime import UTC

import numpy as np
import structlog

logger = structlog.get_logger()


# =====================================================
# MOTOR 1: RELATİF GÜÇ (Güçlendirilmiş)
# =====================================================

class RelativeStrengthMotor:
    """Hisse vs BIST + sektör + peer karşılaştırması (çok ufuklu)."""

    HORIZONS = [1, 5, 10, 20, 60, 120, 252]

    def compute(
        self,
        ticker: str,
        stock_close: np.ndarray,
        benchmark_close: np.ndarray,
        sector_close: np.ndarray | None = None,
        peer_closes: dict[str, np.ndarray] | None = None,
        mask: np.ndarray | None = None,
    ) -> dict[str, float]:
        """Relatif güç feature'ları hesapla."""
        features = {}

        # Mask uygula
        if mask is not None:
            stock_close = np.where(mask == 1, stock_close, np.nan)
            benchmark_close = np.where(mask == 1, benchmark_close, np.nan)
            if sector_close is not None:
                sector_close = np.where(mask == 1, sector_close, np.nan)

        valid_stock = stock_close[~np.isnan(stock_close)]
        valid_bench = benchmark_close[~np.isnan(benchmark_close)]

        if len(valid_stock) < 5 or len(valid_bench) < 5:
            return features

        # Her horizon için relatif getiri
        for h in self.HORIZONS:
            if len(valid_stock) > h and len(valid_bench) > h:
                stock_ret = (valid_stock[-1] / valid_stock[-h] - 1) * 100
                bench_ret = (valid_bench[-1] / valid_bench[-h] - 1) * 100

                # vs BIST
                features[f"rs_vs_bist_{h}d"] = round(stock_ret - bench_ret, 4)
                features[f"rs_ratio_{h}d"] = round(stock_ret / bench_ret, 4) if bench_ret != 0 else 0

                # Alpha (Jensen's alpha approximation)
                if h >= 20:
                    features[f"alpha_{h}d"] = round(stock_ret - bench_ret, 4)

                # Beta (rolling)
                if h >= 20 and len(valid_stock) >= h and len(valid_bench) >= h:
                    stock_rets = np.diff(valid_stock[-h:]) / valid_stock[-h:-1]
                    bench_rets = np.diff(valid_bench[-h:]) / valid_bench[-h:-1]
                    if np.std(bench_rets) > 0:
                        beta = np.cov(stock_rets, bench_rets)[0, 1] / np.var(bench_rets)
                        features[f"beta_{h}d"] = round(float(beta), 4)

                # vs sektör
                if sector_close is not None:
                    valid_sector = sector_close[~np.isnan(sector_close)]
                    if len(valid_sector) > h:
                        sector_ret = (valid_sector[-1] / valid_sector[-h] - 1) * 100
                        features[f"rs_vs_sector_{h}d"] = round(stock_ret - sector_ret, 4)
                        features[f"rs_sector_ratio_{h}d"] = round(stock_ret / sector_ret, 4) if sector_ret != 0 else 0

        # Relatif güç trendi (son 5 gün vs önceki 5 gün)
        if len(valid_stock) > 10 and len(valid_bench) > 10:
            rs_recent = (valid_stock[-1] / valid_stock[-5] - 1) - (valid_bench[-1] / valid_bench[-5] - 1)
            rs_prev = (valid_stock[-5] / valid_stock[-10] - 1) - (valid_bench[-5] / valid_bench[-10] - 1)
            features["rs_trend"] = round(rs_recent - rs_prev, 4)
            features["rs_trend_accel"] = round(rs_recent - 2 * rs_prev, 4)

        # Peer relatif gücü
        if peer_closes:
            for h in [5, 20]:
                peer_h_returns = []
                for _peer_ticker, peer_close in peer_closes.items():
                    if mask is not None:
                        peer_close = np.where(mask == 1, peer_close, np.nan)
                    valid_peer = peer_close[~np.isnan(peer_close)]
                    if len(valid_peer) > h:
                        peer_h_returns.append((valid_peer[-1] / valid_peer[-h] - 1) * 100)

                if peer_h_returns and len(valid_stock) > h:
                    stock_h = (valid_stock[-1] / valid_stock[-h] - 1) * 100
                    peer_mean = np.mean(peer_h_returns)
                    peer_std = np.std(peer_h_returns)
                    features[f"rs_vs_peers_{h}d"] = round(stock_h - peer_mean, 4)
                    features[f"rs_peer_rank_{h}d"] = round(
                        sum(1 for p in peer_h_returns if p <= stock_h) / len(peer_h_returns), 4
                    )
                    if peer_std > 0:
                        features[f"rs_peer_zscore_{h}d"] = round((stock_h - peer_mean) / peer_std, 4)

        # RS momentum (RS'nin kendi momentumu)
        if len(valid_stock) > 20 and len(valid_bench) > 20:
            rs_20d = (valid_stock[-1] / valid_stock[-20] - 1) - (valid_bench[-1] / valid_bench[-20] - 1)
            rs_40d = (valid_stock[-20] / valid_stock[-40] - 1) - (valid_bench[-20] / valid_bench[-40] - 1) if len(valid_stock) > 40 else 0
            features["rs_momentum_20d"] = round(rs_20d - rs_40d, 4)

        return features


# =====================================================
# MOTOR 2: MOMENTUM + TREND (Güçlendirilmiş)
# =====================================================

class MomentumTrendMotor:
    """Momentum seviyesi değil, ivme ve değişim yönü."""

    def compute(
        self,
        ticker: str,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> dict[str, float]:
        """Momentum + trend feature'ları hesapla."""
        features = {}

        if mask is not None:
            close = np.where(mask == 1, close, np.nan)
            high = np.where(mask == 1, high, np.nan)
            low = np.where(mask == 1, low, np.nan)
            volume = np.where(mask == 1, volume, np.nan)

        valid_close = close[~np.isnan(close)]
        valid_high = high[~np.isnan(high)]
        valid_low = low[~np.isnan(low)]
        volume[~np.isnan(volume)]
        n = len(valid_close)

        if n < 20:
            return features

        # ROC çok ufuklu
        for h in [1, 5, 10, 20, 60, 120]:
            if n > h:
                features[f"roc_{h}d"] = round((valid_close[-1] / valid_close[-h] - 1) * 100, 4)

        # Trend eğimi (lineer regresyon slope + R²) çok periyot
        for period in [10, 20, 60]:
            if n >= period:
                x = np.arange(period)
                y = valid_close[-period:]
                if np.std(y) > 0:
                    coeffs = np.polyfit(x, y, 1)
                    slope = coeffs[0]
                    features[f"trend_slope_{period}d"] = round(float(slope / valid_close[-1] * 100), 4)

                    y_pred = np.polyval(coeffs, x)
                    ss_res = np.sum((y - y_pred) ** 2)
                    ss_tot = np.sum((y - np.mean(y)) ** 2)
                    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
                    features[f"trend_r2_{period}d"] = round(float(r_squared), 4)

                    # Eğim değişimi (ivme)
                    if period == 20 and n >= 40:
                        y_prev = valid_close[-40:-20]
                        x_prev = np.arange(20)
                        slope_prev = np.polyfit(x_prev, y_prev, 1)[0]
                        features["trend_slope_change"] = round(float((slope - slope_prev) / abs(slope_prev) * 100), 4) if slope_prev != 0 else 0

        # Momentum ivmesi
        if n > 25:
            roc_now = (valid_close[-1] / valid_close[-5] - 1) * 100
            roc_5ago = (valid_close[-5] / valid_close[-10] - 1) * 100
            roc_10ago = (valid_close[-10] / valid_close[-15] - 1) * 100
            roc_15ago = (valid_close[-15] / valid_close[-20] - 1) * 100

            features["momentum_acceleration"] = round(float(roc_now - roc_5ago), 4)
            features["momentum_accel_2nd"] = round(float((roc_now - roc_5ago) - (roc_5ago - roc_10ago)), 4)

            accel_1 = roc_now - roc_5ago
            accel_2 = roc_5ago - roc_10ago
            accel_3 = roc_10ago - roc_15ago
            if accel_1 > accel_2 > accel_3:
                features["momentum_accel_trend"] = 1.0
            elif accel_1 < accel_2 < accel_3:
                features["momentum_accel_trend"] = -1.0
            else:
                features["momentum_accel_trend"] = 0.0

        # Yeni yüksek/düşük tespiti
        for period in [5, 10, 20, 60, 120]:
            if n > period:
                high_n = np.max(valid_high[-period:])
                low_n = np.min(valid_low[-period:])
                features[f"near_{period}d_high"] = 1.0 if valid_close[-1] >= high_n * 0.98 else 0.0
                features[f"near_{period}d_low"] = 1.0 if valid_close[-1] <= low_n * 1.02 else 0.0
                features[f"pct_from_{period}d_high"] = round((valid_close[-1] / high_n - 1) * 100, 4)
                features[f"pct_from_{period}d_low"] = round((valid_close[-1] / low_n - 1) * 100, 4)

        # Breakout başarısızlığı
        if n > 25:
            for period in [20, 60]:
                if n > period + 5:
                    high_period = np.max(valid_high[-(period+5):-5])
                    if valid_close[-5] > high_period and valid_close[-1] < high_period:
                        features[f"breakout_failure_{period}d"] = 1.0
                    else:
                        features[f"breakout_failure_{period}d"] = 0.0

        # Drawdown + toparlanma gücü
        for period in [20, 60]:
            if n > period:
                peak = np.max(valid_close[-period:])
                trough = np.min(valid_close[-period:])
                current_dd = (peak - valid_close[-1]) / peak * 100
                features[f"drawdown_{period}d"] = round(float(current_dd), 4)
                features[f"max_drawdown_{period}d"] = round((peak - trough) / peak * 100, 4)

                if current_dd > 5:
                    recovery = (valid_close[-1] - trough) / (peak - trough) * 100 if (peak - trough) > 0 else 0
                    features[f"recovery_strength_{period}d"] = round(float(recovery), 4)

        # Hareketli ortalama konumu
        for period in [5, 10, 20, 50, 200]:
            if n >= period:
                sma = np.mean(valid_close[-period:])
                if sma > 0:
                    features[f"price_vs_sma{period}"] = round(float((valid_close[-1] / sma - 1) * 100), 4)

        # Golden/Death cross
        if n >= 50:
            sma20 = np.mean(valid_close[-20:])
            sma50 = np.mean(valid_close[-50:])
            features["golden_cross"] = 1.0 if sma20 > sma50 else 0.0
            features["ma_spread_20_50"] = round((sma20 / sma50 - 1) * 100, 4)

        if n >= 200:
            sma50 = np.mean(valid_close[-50:])
            sma200 = np.mean(valid_close[-200:])
            features["golden_cross_50_200"] = 1.0 if sma50 > sma200 else 0.0
            features["ma_spread_50_200"] = round((sma50 / sma200 - 1) * 100, 4)

        # Price channel
        if n >= 20:
            channel_high = np.max(valid_high[-20:])
            channel_low = np.min(valid_low[-20:])
            if channel_high != channel_low:
                features["price_channel_position"] = round((valid_close[-1] - channel_low) / (channel_high - channel_low), 4)

        # Volatility-adjusted momentum
        if n >= 20:
            returns = np.diff(valid_close[-20:]) / valid_close[-20:-1]
            vol = np.std(returns) * np.sqrt(252)
            if vol > 0:
                features["momentum_vol_adjusted"] = round(features.get("roc_20d", 0) / vol, 4)

        return features


# =====================================================
# MOTOR 3: HACİM + MİKROYAPI (Güçlendirilmiş)
# =====================================================

class VolumeMicrostructureMotor:
    """Hacim yüksek ≠ anlamlı. Fiyat-hacim ilişkisi kritik."""

    def compute(
        self,
        ticker: str,
        open_: np.ndarray,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> dict[str, float]:
        """Hacim + mikroyapı feature'ları hesapla."""
        features = {}

        if mask is not None:
            open_ = np.where(mask == 1, open_, np.nan)
            close = np.where(mask == 1, close, np.nan)
            high = np.where(mask == 1, high, np.nan)
            low = np.where(mask == 1, low, np.nan)
            volume = np.where(mask == 1, volume, np.nan)

        valid_open = open_[~np.isnan(open_)]
        valid_close = close[~np.isnan(close)]
        valid_high = high[~np.isnan(high)]
        valid_low = low[~np.isnan(low)]
        valid_vol = volume[~np.isnan(volume)]
        n = len(valid_close)

        if n < 20:
            return features

        # Hacim percentile çok periyot
        for period in [5, 10, 20, 60]:
            if len(valid_vol) >= period:
                current_vol = valid_vol[-1]
                vol_period = valid_vol[-period:]
                percentile = sum(1 for v in vol_period if v <= current_vol) / len(vol_period)
                features[f"volume_percentile_{period}d"] = round(float(percentile), 4)

        # Hacim-fiyat yönü ilişkisi (vektörize)
        for period in [5, 10, 20]:
            start_idx = max(1, n - period)
            close_slice = valid_close[start_idx:n]
            prev_slice = valid_close[start_idx-1:n-1]
            vol_slice = valid_vol[start_idx:n]

            up_mask = close_slice > prev_slice
            down_mask = close_slice < prev_slice

            up_vol = vol_slice[up_mask]
            down_vol = vol_slice[down_mask]

            if len(up_vol) > 0 and len(down_vol) > 0:
                avg_up = float(np.mean(up_vol))
                avg_down = float(np.mean(down_vol))
                if avg_down > 0:
                    features[f"volume_up_down_ratio_{period}d"] = round(avg_up / avg_down, 4)
                features[f"volume_up_avg_{period}d"] = round(avg_up, 0)
                features[f"volume_down_avg_{period}d"] = round(avg_down, 0)

        # Tick rule (alış/satış baskısı — vektörize)
        for period in [5, 10, 20]:
            start_idx = max(0, n - period)
            close_slice = valid_close[start_idx:n]
            open_slice = valid_open[start_idx:n]
            vol_slice = valid_vol[start_idx:n]

            buy_mask = close_slice > open_slice
            sell_mask = close_slice < open_slice

            buy_ticks = float(np.sum(vol_slice[buy_mask]))
            sell_ticks = float(np.sum(vol_slice[sell_mask]))

            total_ticks = buy_ticks + sell_ticks
            if total_ticks > 0:
                features[f"tick_rule_{period}d"] = round((buy_ticks - sell_ticks) / total_ticks, 4)
                features[f"buy_pressure_{period}d"] = round(buy_ticks / total_ticks, 4)

        # VWAP sapması çok periyot
        for period in [5, 10, 20]:
            if n >= period:
                tp = (valid_high[-period:] + valid_low[-period:] + valid_close[-period:]) / 3
                vol_sum = np.sum(valid_vol[-period:])
                vwap = np.sum(tp * valid_vol[-period:]) / vol_sum if vol_sum > 0 else valid_close[-1]
                if vwap > 0:
                    features[f"vwap_deviation_{period}d"] = round(float((valid_close[-1] / vwap - 1) * 100), 4)

        # Hacim anomalisi (z-score)
        for period in [10, 20, 60]:
            if len(valid_vol) >= period:
                vol_mean = np.mean(valid_vol[-period:])
                vol_std = np.std(valid_vol[-period:])
                if vol_std > 0:
                    features[f"volume_zscore_{period}d"] = round(float((valid_vol[-1] - vol_mean) / vol_std), 4)

        # On-balance volume (OBV — vektörize)
        price_diff = np.diff(valid_close)
        obv = float(np.sum(valid_vol[1:][price_diff > 0]) - np.sum(valid_vol[1:][price_diff < 0]))
        features["obv"] = round(obv, 0)

        # OBV momentum (vektörize)
        if n >= 20:
            pd_20 = np.diff(valid_close[-20:])
            vol_20 = valid_vol[-19:]
            obv_20 = float(np.sum(vol_20[pd_20 > 0]) - np.sum(vol_20[pd_20 < 0]))
            features["obv_20d"] = round(obv_20, 0)

        # Volume trend (hacim artıyor mu azalıyor mu)
        if len(valid_vol) >= 10:
            vol_recent = np.mean(valid_vol[-5:])
            vol_prev = np.mean(valid_vol[-10:-5])
            if vol_prev > 0:
                features["volume_trend"] = round((vol_recent / vol_prev - 1) * 100, 4)

        # Average volume (ranking model bekler)
        if len(valid_vol) >= 5:
            features["avg_volume_5d"] = round(float(np.mean(valid_vol[-5:])), 0)

        # Money Flow Index (MFI) approximation
        if n >= 14:
            pos_flow = 0
            neg_flow = 0
            for i in range(n-14, n):
                tp = (valid_high[i] + valid_low[i] + valid_close[i]) / 3
                if i > 0:
                    prev_tp = (valid_high[i-1] + valid_low[i-1] + valid_close[i-1]) / 3
                    if tp > prev_tp:
                        pos_flow += tp * valid_vol[i]
                    else:
                        neg_flow += tp * valid_vol[i]
            if neg_flow > 0:
                mfi = 100 - (100 / (1 + pos_flow / neg_flow))
                features["mfi_14d"] = round(float(mfi), 4)

        # Chaikin Money Flow (CMF)
        if n >= 20:
            cmf_sum = 0
            vol_sum = 0
            for i in range(n-20, n):
                if valid_high[i] != valid_low[i]:
                    mf_multiplier = ((valid_close[i] - valid_low[i]) - (valid_high[i] - valid_close[i])) / (valid_high[i] - valid_low[i])
                    cmf_sum += mf_multiplier * valid_vol[i]
                    vol_sum += valid_vol[i]
            if vol_sum > 0:
                features["cmf_20d"] = round(float(cmf_sum / vol_sum), 4)

        return features


# =====================================================
# MOTOR 4: FUNDAMENTAL (Güçlendirilmiş)
# =====================================================

class FundamentalMotor:
    """Sektörel normalize + FCF merkezli + kalite skorları."""

    def compute(
        self,
        ticker: str,
        fundamentals: dict[str, float],
        sector_medians: dict[str, float] | None = None,
        sector: str | None = None,
    ) -> dict[str, float]:
        """Fundamental feature'lar hesapla."""
        features = {}

        if not fundamentals:
            return features

        # Ham çarpanlar
        for key in ["pe_ratio", "pb_ratio", "ev_ebitda", "ev_sales", "fcf_yield",
                     "dividend_yield", "roe", "roa", "roic", "profit_margin",
                     "gross_margin", "operating_margin", "debt_to_equity",
                     "current_ratio", "quick_ratio", "interest_coverage",
                     "asset_turnover", "inventory_turnover", "revenue_growth",
                     "earnings_growth", "fcf_growth"]:
            val = fundamentals.get(key)
            if val is not None:
                features[f"raw_{key}"] = round(float(val), 4)

        # Sektörel normalize
        if sector_medians:
            for key in ["pe_ratio", "pb_ratio", "ev_ebitda", "ev_sales", "profit_margin", "roe"]:
                val = fundamentals.get(key)
                median = sector_medians.get(key)
                if val and median and median > 0:
                    features[f"sector_norm_{key}"] = round(float(val / median), 4)
                    # Percentile within sector
                    features[f"sector_pctile_{key}"] = round(float(val / median), 4)

        # FCF merkezli
        fcf = fundamentals.get("free_cash_flow", 0)
        revenue = fundamentals.get("revenue", 0)
        market_cap = fundamentals.get("market_cap", 0)
        total_assets = fundamentals.get("total_assets", 0)

        if revenue and revenue > 0 and fcf:
            features["fcf_margin"] = round(float(fcf / revenue * 100), 4)
        if market_cap and market_cap > 0 and fcf:
            features["fcf_yield_pct"] = round(float(fcf / market_cap * 100), 4)
        if total_assets and total_assets > 0 and fcf:
            features["fcf_roa"] = round(float(fcf / total_assets * 100), 4)

        # Büyüme kalitesi
        rev_growth = fundamentals.get("revenue_growth", 0)
        earn_growth = fundamentals.get("earnings_growth", 0)
        fcf_growth = fundamentals.get("fcf_growth", 0)
        if rev_growth and earn_growth:
            features["earnings_quality"] = round(float(earn_growth / max(rev_growth, 0.01)), 4)
        if fcf_growth and earn_growth:
            features["fcf_quality"] = round(float(fcf_growth / max(earn_growth, 0.01)), 4)

        # Bilanço kalitesi skoru (0-100)
        quality_score = 50
        debt_eq = fundamentals.get("debt_to_equity", 0)
        current_ratio = fundamentals.get("current_ratio", 0)
        interest_cov = fundamentals.get("interest_coverage", 0)

        if debt_eq and debt_eq < 0.3:
            quality_score += 25
        elif debt_eq and debt_eq < 0.5:
            quality_score += 15
        elif debt_eq and debt_eq > 2:
            quality_score -= 25
        elif debt_eq and debt_eq > 1:
            quality_score -= 10

        if current_ratio and current_ratio > 2:
            quality_score += 15
        elif current_ratio and current_ratio > 1.5:
            quality_score += 10
        elif current_ratio and current_ratio < 1:
            quality_score -= 15

        if interest_cov and interest_cov > 5:
            quality_score += 10
        elif interest_cov and interest_cov < 2:
            quality_score -= 10

        features["balance_sheet_quality"] = round(float(min(100, max(0, quality_score))), 0)

        # Kârlılık kalitesi
        profit_margin = fundamentals.get("profit_margin", 0)
        gross_margin = fundamentals.get("gross_margin", 0)
        if profit_margin and gross_margin and gross_margin > 0:
            features["margin_stability"] = round(float(profit_margin / gross_margin), 4)

        # Value skoru (düşük PE + düşük PB + yüksek FCF yield)
        pe = fundamentals.get("pe_ratio", 0)
        pb = fundamentals.get("pb_ratio", 0)
        fcf_yld = fundamentals.get("fcf_yield", 0)
        value_score = 0
        if pe and pe > 0 and pe < 15:
            value_score += 30
        elif pe and pe < 25:
            value_score += 15
        if pb and pb > 0 and pb < 1.5:
            value_score += 30
        elif pb and pb < 3:
            value_score += 15
        if fcf_yld and fcf_yld > 0.05:
            value_score += 40
        elif fcf_yld and fcf_yld > 0.02:
            value_score += 20
        features["value_score"] = round(float(min(100, value_score)), 0)

        # Growth skoru
        growth_score = 0
        if rev_growth and rev_growth > 0.2:
            growth_score += 40
        elif rev_growth and rev_growth > 0.1:
            growth_score += 20
        if earn_growth and earn_growth > 0.2:
            growth_score += 40
        elif earn_growth and earn_growth > 0.1:
            growth_score += 20
        if fcf_growth and fcf_growth > 0.2:
            growth_score += 20
        features["growth_score"] = round(float(min(100, growth_score)), 0)

        # Quality skoru (ROE + marj + bilanço)
        roe = fundamentals.get("roe", 0)
        quality_score_2 = 0
        if roe and roe > 0.15:
            quality_score_2 += 40
        elif roe and roe > 0.1:
            quality_score_2 += 20
        if profit_margin and profit_margin > 0.2:
            quality_score_2 += 30
        elif profit_margin and profit_margin > 0.1:
            quality_score_2 += 15
        quality_score_2 += features.get("balance_sheet_quality", 50) * 0.3
        features["quality_score"] = round(float(min(100, quality_score_2)), 0)

        return features


# =====================================================
# MOTOR 5: KAP + HABER (Güçlendirilmiş - LLM Entegrasyonu)
# =====================================================

class KAPNewsMotor:
    """Yapılandırılmış extraction + LLM sentiment + Knowledge Graph."""

    # KAP olay türleri ve önem skorları
    KAP_EVENT_IMPORTANCE = {
        "FINANCIAL_REPORT": 1.0,
        "DIVIDEND": 0.8,
        "CAPITAL_INCREASE": 0.9,
        "MERGER_ACQUISITION": 1.0,
        "BOARD_CHANGE": 0.6,
        "SHARE_BUYBACK": 0.7,
        "CONTRACT": 0.7,
        "LAW_SUIT": 0.5,
        "REGULATORY": 0.6,
        "GUIDANCE": 0.9,
        "ANALYST_MEETING": 0.5,
        "OTHER": 0.3,
    }

    def compute(
        self,
        ticker: str,
        kap_events: list[dict],
        news_events: list[dict],
        llm_analysis: dict | None = None,
        as_of_date: str | None = None,
    ) -> dict[str, float]:
        """KAP + haber feature'ları hesapla."""
        features = {}

        # as_of_date ile temporal filtreleme (look-ahead bias önleme)
        if as_of_date:
            from datetime import datetime as _dt
            cutoff = _dt.fromisoformat(as_of_date)
            kap_events = [e for e in kap_events if e.get("date", "") and _dt.fromisoformat(e["date"].replace("Z", "+00:00").split("+")[0]) <= cutoff]
            news_events = [e for e in news_events if e.get("date", "") and _dt.fromisoformat(e["date"].replace("Z", "+00:00").split("+")[0]) <= cutoff]

        # === KAP ANALİZİ ===
        if kap_events:
            event_types = defaultdict(int)
            importance_scores = []
            sentiments = []
            surprise_scores = []
            dates = []

            for event in kap_events:
                etype = event.get("category", "OTHER")
                event_types[etype] += 1

                # Önem skoru
                base_importance = self.KAP_EVENT_IMPORTANCE.get(etype, 0.3)
                event_importance = event.get("importance", base_importance)
                importance_scores.append(event_importance)

                # Sentiment
                sentiment = event.get("sentiment", 0)
                sentiments.append(sentiment)

                # Surprise (beklentiden sapma)
                surprise = event.get("surprise", 0)
                surprise_scores.append(surprise)

                dates.append(event.get("date", ""))

            # Event sayıları
            for etype, count in event_types.items():
                features[f"kap_count_{etype.lower()}"] = count

            features["kap_total_events"] = len(kap_events)
            features["kap_avg_importance"] = round(float(np.mean(importance_scores)), 4)
            features["kap_max_importance"] = round(float(np.max(importance_scores)), 4)
            features["kap_importance_std"] = round(float(np.std(importance_scores)), 4)

            # Sentiment metrikleri
            features["kap_sentiment_avg"] = round(float(np.mean(sentiments)), 4)
            features["kap_sentiment_latest"] = round(float(sentiments[-1]), 4) if sentiments else 0
            features["kap_sentiment_std"] = round(float(np.std(sentiments)), 4)
            features["kap_sentiment_trend"] = round(
                float(np.mean(sentiments[-3:]) - np.mean(sentiments[:3])), 4
            ) if len(sentiments) >= 6 else 0

            # Surprise metrikleri
            if surprise_scores:
                features["kap_surprise_avg"] = round(float(np.mean(surprise_scores)), 4)
                features["kap_surprise_max"] = round(float(np.max(np.abs(surprise_scores))), 4)

            # Zaman ağırlıklı sentiment (yeni olaylar daha önemli)
            if sentiments and dates:
                weights = np.exp(-np.arange(len(sentiments)) * 0.1)[::-1]
                weighted_sent = np.average(sentiments, weights=weights)
                features["kap_sentiment_weighted"] = round(float(weighted_sent), 4)

            # KAP yoğunluğu (son 7 gün)
            recent_kap = [e for e in kap_events if self._is_recent(e.get("date", ""), hours=168)]
            features["kap_recent_count_7d"] = len(recent_kap)
            if recent_kap:
                features["kap_recent_sentiment"] = round(
                    float(np.mean([e.get("sentiment", 0) for e in recent_kap])), 4
                )

        # === HABER ANALİZİ ===
        if news_events:
            sentiments = [n.get("sentiment", 0) for n in news_events]
            importances = [n.get("importance", 0.5) for n in news_events]
            sources = [n.get("source", "unknown") for n in news_events]

            # Ağırlıklı sentiment
            if importances:
                weighted = sum(s * i for s, i in zip(sentiments, importances, strict=False)) / sum(importances)
                features["news_sentiment_weighted"] = round(float(weighted), 4)

            features["news_count_24h"] = len([n for n in news_events if self._is_recent(n.get("date", ""), hours=24)])
            features["news_count_7d"] = len([n for n in news_events if self._is_recent(n.get("date", ""), hours=168)])
            features["news_avg_importance"] = round(float(np.mean(importances)), 4)
            features["news_sentiment_std"] = round(float(np.std(sentiments)), 4)

            # Sentiment momentum
            recent = [s for s, n in zip(sentiments, news_events, strict=False)
                     if self._is_recent(n.get("date", ""), hours=72)]
            older = [s for s, n in zip(sentiments, news_events, strict=False)
                    if not self._is_recent(n.get("date", ""), hours=72)]

            if recent and older:
                features["sentiment_momentum"] = round(float(np.mean(recent) - np.mean(older)), 4)
                features["sentiment_momentum_accel"] = round(
                    float(np.mean(recent[:3]) - np.mean(recent[-3:])), 4
                ) if len(recent) >= 6 else 0

            # Kaynak çeşitliliği
            unique_sources = len(set(sources))
            features["news_source_diversity"] = unique_sources

            # Haber yoğunluğu (son 24 saat vs önceki 24 saat)
            today_news = [n for n in news_events if self._is_recent(n.get("date", ""), hours=24)]
            yesterday_news = [n for n in news_events
                            if not self._is_recent(n.get("date", ""), hours=24)
                            and self._is_recent(n.get("date", ""), hours=48)]
            if yesterday_news:
                features["news_intensity_change"] = round(
                    (len(today_news) / len(yesterday_news) - 1) * 100, 4
                )

        # === LLM ANALİZİ (eğer varsa) ===
        if llm_analysis:
            features["llm_overall_sentiment"] = round(float(llm_analysis.get("sentiment", 0)), 4)
            features["llm_confidence"] = round(float(llm_analysis.get("confidence", 0)), 4)
            features["llm_key_topics"] = len(llm_analysis.get("topics", []))
            features["llm_risk_score"] = round(float(llm_analysis.get("risk_score", 0)), 4)
            features["llm_opportunity_score"] = round(float(llm_analysis.get("opportunity_score", 0)), 4)

        # === KOMBİNE SENTIMENT ===
        kap_sent = features.get("kap_sentiment_weighted", features.get("kap_sentiment_avg", 0))
        news_sent = features.get("news_sentiment_weighted", 0)
        if kap_sent and news_sent:
            features["combined_sentiment"] = round(0.6 * kap_sent + 0.4 * news_sent, 4)
        elif kap_sent:
            features["combined_sentiment"] = round(kap_sent, 4)
        elif news_sent:
            features["combined_sentiment"] = round(news_sent, 4)

        return features

    def _is_recent(self, ts: str, hours: int = 24) -> bool:
        try:
            from datetime import datetime, timedelta
            if isinstance(ts, str) and ts:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                return False
            if t.tzinfo is None:
                t = t.replace(tzinfo=UTC)
            return (datetime.now(UTC) - t) < timedelta(hours=hours)
        except Exception as e:
            return False


# =====================================================
# MOTOR 6: KATALİZÖR (Güçlendirilmiş)
# =====================================================

class CatalystMotor:
    """Yaklaşan olaylar ayrı skor — zaman decay ile."""

    CATALYST_IMPACT = {
        "EARNINGS": 1.0,
        "DIVIDEND_DATE": 0.6,
        "ANNUAL_MEETING": 0.5,
        "PRODUCT_LAUNCH": 0.8,
        "REGULATORY_DECISION": 0.9,
        "CONTRACT_EXPIRY": 0.4,
        "SECTOR_EVENT": 0.5,
        "ECONOMIC_DATA": 0.3,
        "IPO_LOCKUP": 0.7,
        "OTHER": 0.3,
    }

    def compute(
        self,
        ticker: str,
        upcoming_events: list[dict],
        as_of_date: str | None = None,
    ) -> dict[str, float]:
        """Katalizör feature'ları hesapla."""
        features = {}

        # as_of_date ile temporal filtreleme (look-ahead bias önleme)
        if as_of_date and upcoming_events:
            from datetime import datetime as _dt
            cutoff = _dt.fromisoformat(as_of_date)
            filtered = []
            for event in upcoming_events:
                event_date = event.get("date", "")
                if event_date:
                    try:
                        ed = _dt.fromisoformat(event_date.replace("Z", "+00:00").split("+")[0])
                        if ed <= cutoff:
                            filtered.append(event)
                    except (ValueError, IndexError):
                        filtered.append(event)
                else:
                    filtered.append(event)
            upcoming_events = filtered

        if not upcoming_events:
            features["catalyst_count"] = 0
            features["catalyst_importance"] = 0
            features["catalyst_days_nearest"] = 999
            features["catalyst_time_decay_score"] = 0
            return features

        features["catalyst_count"] = len(upcoming_events)

        # Zaman decay ile ağırlıklandırılmış önem
        time_decay_scores = []
        importances = []
        days_list = []

        for event in upcoming_events:
            etype = event.get("type", "OTHER")
            base_impact = self.CATALYST_IMPACT.get(etype, 0.3)
            event_importance = event.get("importance", base_impact)
            days_until = event.get("days_until", 999)

            # Zaman decay: Yakın olaylar daha önemli
            time_weight = np.exp(-days_until / 30)  # 30 gün half-life
            decayed_score = event_importance * time_weight

            time_decay_scores.append(decayed_score)
            importances.append(event_importance)
            days_list.append(days_until)

        features["catalyst_importance"] = round(float(np.max(importances)), 4)
        features["catalyst_avg_importance"] = round(float(np.mean(importances)), 4)
        features["catalyst_days_nearest"] = min(days_list) if days_list else 999
        features["catalyst_time_decay_score"] = round(float(np.sum(time_decay_scores)), 4)

        # Katalizör türleri
        type_counts = defaultdict(int)
        for event in upcoming_events:
            etype = event.get("type", "unknown")
            type_counts[etype] += 1

        for etype, count in type_counts.items():
            features[f"catalyst_{etype.lower()}"] = count

        # Yakın katalizör var mı? (7 gün içinde)
        near_catalysts = [e for e in upcoming_events if e.get("days_until", 999) <= 7]
        features["catalyst_near_7d"] = len(near_catalysts)
        if near_catalysts:
            features["catalyst_near_importance"] = round(
                float(np.max([e.get("importance", 0) for e in near_catalysts])), 4
            )

        # Katalizör kümülasyonu (çok sayıda yakın olay = daha yüksek etki)
        if len(upcoming_events) >= 3:
            features["catalyst_cluster"] = 1.0
        else:
            features["catalyst_cluster"] = 0.0

        return features


# =====================================================
# MOTOR 7: "NEDEN DÜŞÜYOR?" (Güçlendirilmiş)
# =====================================================

class WhyFallingMotor:
    """Düşen bıçağı tutma hatasını önle — çok faktörlü analiz."""

    def compute(
        self,
        ticker: str,
        stock_return_5d: float,
        stock_return_20d: float,
        market_return_5d: float,
        market_return_20d: float,
        sector_return_5d: float,
        sector_return_20d: float,
        volume_change: float,
        volume_zscore: float,
        news_sentiment: float,
        kap_sentiment: float,
        rsi: float = 50,
        atr_pct: float = 0,
    ) -> dict[str, float]:
        """Düşüş nedeni sınıflandırması."""
        features = {}

        # Düşüş var mı?
        is_falling_5d = stock_return_5d < -2
        is_falling_20d = stock_return_20d < -5
        features["is_falling_5d"] = 1.0 if is_falling_5d else 0.0
        features["is_falling_20d"] = 1.0 if is_falling_20d else 0.0

        if not is_falling_5d and not is_falling_20d:
            features["falling_is_temporary"] = 0.5
            features["fall_severity"] = 0
            return features

        # Düşüş şiddeti
        features["fall_severity"] = round(abs(min(stock_return_5d, 0)), 4)

        # Market selloff tespiti (5d ve 20d)
        features["fall_market_selloff_5d"] = 1.0 if market_return_5d < -3 else 0.0
        features["fall_market_selloff_20d"] = 1.0 if market_return_20d < -5 else 0.0

        # Sector selloff tespiti
        features["fall_sector_selloff_5d"] = 1.0 if sector_return_5d < -5 else 0.0
        features["fall_sector_selloff_20d"] = 1.0 if sector_return_20d < -8 else 0.0

        # Company-specific (piyasa ve sektör düşmemişse)
        features["fall_company_specific_5d"] = 1.0 if (
            market_return_5d > -1 and sector_return_5d > -2 and stock_return_5d < -5
        ) else 0.0

        # Liquidity event (hacim patlaması + fiyat düşüşü)
        features["fall_liquidity_event"] = 1.0 if (
            volume_zscore > 2 and stock_return_5d < -5
        ) else 0.0

        # Temporary panic (hızlı düşüş + negatif sentiment düşük)
        features["fall_temporary_panic"] = 1.0 if (
            stock_return_5d < -10 and news_sentiment > -0.3
        ) else 0.0

        # Oversold bounce potential (RSI < 30 + düşüş şiddetli)
        features["fall_oversold_bounce"] = 1.0 if (
            rsi < 30 and stock_return_5d < -5
        ) else 0.0

        # High volatility crash (ATR yüksek + düşüş)
        features["fall_high_vol_crash"] = 1.0 if (
            atr_pct > 5 and stock_return_5d < -5
        ) else 0.0

        # Düşüş nedeni geçici mi kalıcı mı? (Çok faktörlü)
        temporary_score = 0
        if features.get("fall_market_selloff_5d", 0) == 1.0:
            temporary_score += 30
        if features.get("fall_sector_selloff_5d", 0) == 1.0:
            temporary_score += 20
        if features.get("fall_temporary_panic", 0) == 1.0:
            temporary_score += 25
        if features.get("fall_oversold_bounce", 0) == 1.0:
            temporary_score += 15
        if volume_zscore < 1:  # Düşük hacim = panik değil
            temporary_score += 10

        permanent_score = 0
        if features.get("fall_company_specific_5d", 0) == 1.0:
            permanent_score += 40
        if features.get("fall_liquidity_event", 0) == 1.0:
            permanent_score += 20
        if kap_sentiment < -0.5:
            permanent_score += 25
        if news_sentiment < -0.5:
            permanent_score += 15

        total = temporary_score + permanent_score
        if total > 0:
            features["falling_is_temporary"] = round(temporary_score / total, 4)
            features["falling_is_permanent"] = round(permanent_score / total, 4)
        else:
            features["falling_is_temporary"] = 0.5
            features["falling_is_permanent"] = 0.5

        # Catch falling knife risk (0 = güvenli, 1 = tehlikeli)
        risk_score = 0
        if features.get("fall_company_specific_5d", 0) == 1.0:
            risk_score += 40
        if features.get("fall_liquidity_event", 0) == 1.0:
            risk_score += 30
        if features.get("fall_high_vol_crash", 0) == 1.0:
            risk_score += 20
        if stock_return_20d < -15:
            risk_score += 10

        features["catch_falling_knife_risk"] = round(min(100, risk_score), 0)

        return features


# =====================================================
# MOTOR 8: MEAN REVERSION (YENİ)
# =====================================================

class MeanReversionMotor:
    """Ortalamaya dönüş sinyalleri."""

    def compute(
        self,
        ticker: str,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> dict[str, float]:
        """Mean reversion feature'ları hesapla."""
        features = {}

        if mask is not None:
            close = np.where(mask == 1, close, np.nan)
            high = np.where(mask == 1, high, np.nan)
            low = np.where(mask == 1, low, np.nan)

        valid_close = close[~np.isnan(close)]
        n = len(valid_close)

        if n < 20:
            return features

        # Bollinger Bands
        for period in [20, 50]:
            if n >= period:
                sma = np.mean(valid_close[-period:])
                std = np.std(valid_close[-period:])
                if std > 0:
                    bb_position = (valid_close[-1] - (sma - 2*std)) / (4*std)
                    features[f"bb_position_{period}d"] = round(float(max(0, min(1, bb_position))), 4)
                    features[f"bb_zscore_{period}d"] = round(float((valid_close[-1] - sma) / std), 4)
                    features[f"bb_width_{period}d"] = round(float(4*std / sma), 4)

        # RSI
        for period in [5, 14, 21]:
            if n >= period + 1:
                deltas = np.diff(valid_close[-(period+1):])
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                avg_gain = np.mean(gains)
                avg_loss = np.mean(losses)
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                    features[f"rsi_{period}d"] = round(float(rsi), 4)

        # Williams %R
        if n >= 14:
            highest_high = np.max(valid_close[-14:])
            lowest_low = np.min(valid_close[-14:])
            if highest_high != lowest_low:
                williams_r = (highest_high - valid_close[-1]) / (highest_high - lowest_low) * -100
                features["williams_r_14d"] = round(float(williams_r), 4)

        # Stochastic RSI — RSI serisi üzerinden hesaplanmalı
        if n >= 28:  # en az 28 gün gerekli (14 RSI + 14 Stochastic)
            rsi_series = []
            for i in range(14, n):
                subset = valid_close[i-14:i+1]
                if len(subset) >= 15:
                    deltas = np.diff(subset)
                    gains = np.where(deltas > 0, deltas, 0)
                    losses = np.where(deltas < 0, -deltas, 0)
                    avg_gain = np.mean(gains[:14])
                    avg_loss = np.mean(losses[:14])
                    for j in range(14, len(gains)):
                        avg_gain = (avg_gain * 13 + gains[j]) / 14
                        avg_loss = (avg_loss * 13 + losses[j]) / 14
                    if avg_loss > 0:
                        rsi_series.append(100 - (100 / (1 + avg_gain / avg_loss)))
                    else:
                        rsi_series.append(100)

            if len(rsi_series) >= 14:
                # Son 14 RSI değeri üzerinden Stochastic
                rsi_window = rsi_series[-14:]
                min_rsi = min(rsi_window)
                max_rsi = max(rsi_window)
                if max_rsi != min_rsi:
                    stoch_rsi = (rsi_series[-1] - min_rsi) / (max_rsi - min_rsi)
                    features["stoch_rsi"] = round(float(stoch_rsi), 4)
                else:
                    features["stoch_rsi"] = 0.5

        # CCI (Commodity Channel Index)
        if n >= 20:
            # F-006 düzeltmesi: tp = (high + low + close) / 3 olmalı
            valid_high_mr = high[~np.isnan(high)]
            valid_low_mr = low[~np.isnan(low)]
            n_hl = min(len(valid_high_mr), len(valid_low_mr), n)
            if n_hl >= 20:
                tp = (valid_high_mr[-20:] + valid_low_mr[-20:] + valid_close[-20:]) / 3
                sma_tp = np.mean(tp)
                std_tp = np.std(tp)
                if std_tp > 0:
                    current_tp = (valid_high_mr[-1] + valid_low_mr[-1] + valid_close[-1]) / 3
                    cci = (current_tp - sma_tp) / (0.015 * std_tp)
                    features["cci_20d"] = round(float(cci), 4)

        # Mean reversion signal (oversold + high quality)
        rsi_14 = features.get("rsi_14d", 50)
        bb_zscore = features.get("bb_zscore_20d", 0)
        features["mean_reversion_signal"] = 1.0 if (rsi_14 < 30 and bb_zscore < -2) else 0.0
        features["mean_reversion_strength"] = round(max(0, (30 - rsi_14) / 30 + abs(min(0, bb_zscore)) / 3), 4)

        return features


# =====================================================
# MOTOR 9: SEASONALITY (YENİ)
# =====================================================

class SeasonalityMotor:
    """Mevsimsel ve takvim etkileri."""

    def compute(
        self,
        ticker: str,
        close: np.ndarray,
        dates: list[str],
        mask: np.ndarray | None = None,
    ) -> dict[str, float]:
        """Mevsimsel feature'ları hesapla."""
        features = {}

        # M-001 düzeltmesi: Birleşik mask — close ve dates aynı filtreyle
        if mask is not None:
            # Hem mask=1 hem close NaN olmayan günleri filtrele
            combined_mask = (mask == 1) & (~np.isnan(close))
            valid_close = close[combined_mask]
            valid_dates = [d for d, m in zip(dates, combined_mask, strict=False) if m]
        else:
            valid_close = close[~np.isnan(close)]
            valid_dates = list(dates)

        if len(valid_close) < 252 or len(valid_dates) < 252:
            return features

        from datetime import datetime

        # Ay bazlı getiri
        monthly_returns = defaultdict(list)
        for i in range(1, len(valid_close)):
            if i < len(valid_dates):
                month = datetime.strptime(valid_dates[i], "%Y-%m-%d").month
                ret = (valid_close[i] / valid_close[i-1] - 1) * 100
                monthly_returns[month].append(ret)

        # Mevcut ay
        if valid_dates:
            current_month = datetime.strptime(valid_dates[-1], "%Y-%m-%d").month
            if monthly_returns[current_month]:
                features["seasonality_current_month_avg"] = round(
                    float(np.mean(monthly_returns[current_month])), 4
                )
                features["seasonality_current_month_win_rate"] = round(
                    float(sum(1 for r in monthly_returns[current_month] if r > 0) / len(monthly_returns[current_month])), 4
                )

        # En iyi/en kötü aylar
        month_avgs = {m: np.mean(rets) for m, rets in monthly_returns.items() if rets}
        if month_avgs:
            features["seasonality_best_month"] = max(month_avgs, key=month_avgs.get)
            features["seasonality_worst_month"] = min(month_avgs, key=month_avgs.get)
            features["seasonality_best_month_return"] = round(float(month_avgs[features["seasonality_best_month"]]), 4)
            features["seasonality_worst_month_return"] = round(float(month_avgs[features["seasonality_worst_month"]]), 4)

        # Gün bazlı (haftanın günü)
        if len(valid_dates) >= 20:
            dayofweek_returns = defaultdict(list)
            for i in range(1, len(valid_close)):
                if i < len(valid_dates):
                    dow = datetime.strptime(valid_dates[i], "%Y-%m-%d").weekday()
                    ret = (valid_close[i] / valid_close[i-1] - 1) * 100
                    dayofweek_returns[dow].append(ret)

            current_dow = datetime.strptime(valid_dates[-1], "%Y-%m-%d").weekday()
            if dayofweek_returns.get(current_dow):
                features["seasonality_current_dow_avg"] = round(
                    float(np.mean(dayofweek_returns[current_dow])), 4
                )

        # Yılın çeyreği
        if valid_dates:
            quarter = (datetime.strptime(valid_dates[-1], "%Y-%m-%d").month - 1) // 3 + 1
            features["seasonality_current_quarter"] = quarter

            quarterly_returns = defaultdict(list)
            for i in range(20, len(valid_close)):
                if i < len(valid_dates):
                    q = (datetime.strptime(valid_dates[i], "%Y-%m-%d").month - 1) // 3 + 1
                    ret = (valid_close[i] / valid_close[i-20] - 1) * 100
                    quarterly_returns[q].append(ret)

            if quarterly_returns.get(quarter):
                features["seasonality_current_quarter_avg"] = round(
                    float(np.mean(quarterly_returns[quarter])), 4
                )

        return features


# =====================================================
# ANA MOTOR — TÜM MOTORLARI BİRLEŞTİR
# =====================================================

class NineMotorEngine:
    """7 motoru birleştiren ana motor (artık 9 motor).

    Motorlar bağımsızdır — paralel çalıştırılarak Pipeline süresi kısaltılır.
    """

    def __init__(self):
        self.motor1 = RelativeStrengthMotor()
        self.motor2 = MomentumTrendMotor()
        self.motor3 = VolumeMicrostructureMotor()
        self.motor4 = FundamentalMotor()
        self.motor5 = KAPNewsMotor()
        self.motor6 = CatalystMotor()
        self.motor7 = WhyFallingMotor()
        self.motor8 = MeanReversionMotor()
        self.motor9 = SeasonalityMotor()
        self._pool = None  # Lazy-initialized thread pool

    def _get_pool(self):
        if self._pool is None:
            from concurrent.futures import ThreadPoolExecutor
            self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="motor")
        return self._pool

    def compute_all(
        self,
        ticker: str,
        df,
        mask: np.ndarray | None = None,
        benchmark_close: np.ndarray | None = None,
        sector_close: np.ndarray | None = None,
        peer_closes: dict[str, np.ndarray] | None = None,
        fundamentals: dict[str, float] | None = None,
        sector_medians: dict[str, float] | None = None,
        kap_events: list[dict] | None = None,
        news_events: list[dict] | None = None,
        upcoming_events: list[dict] | None = None,
        llm_analysis: dict | None = None,
        market_return_5d: float = 0,
        market_return_20d: float = 0,
        sector_return_5d: float = 0,
        sector_return_20d: float = 0,
        market_regime: str = "UNKNOWN",
        as_of_date: str | None = None,
    ) -> dict[str, float]:
        """Tüm 9 motoru paralel çalıştır ve feature'ları birleştir."""

        close = df["Close"].values if "Close" in df.columns else np.array([])
        open_ = df["Open"].values if "Open" in df.columns else close.copy()
        high = df["High"].values if "High" in df.columns else close.copy()
        low = df["Low"].values if "Low" in df.columns else close.copy()
        volume = df["Volume"].values if "Volume" in df.columns else np.ones(len(close))
        dates = df.index.strftime("%Y-%m-%d").tolist() if hasattr(df.index, 'strftime') else []

        # --- Paralel motor hesaplama ---
        from concurrent.futures import as_completed
        pool = self._get_pool()
        futures = {}

        # Motor 1: Relatif Güç (benchmark gerektirir)
        if benchmark_close is not None:
            futures[pool.submit(self.motor1.compute, ticker, close, benchmark_close, sector_close, peer_closes, mask)] = "m1"

        # Motor 2: Momentum + Trend
        futures[pool.submit(self.motor2.compute, ticker, close, high, low, volume, mask)] = "m2"

        # Motor 3: Hacim + Mikroyapı
        futures[pool.submit(self.motor3.compute, ticker, open_, close, high, low, volume, mask)] = "m3"

        # Motor 4: Fundamental
        if fundamentals:
            futures[pool.submit(self.motor4.compute, ticker, fundamentals, sector_medians)] = "m4"

        # Motor 5: KAP + Haber
        futures[pool.submit(self.motor5.compute, ticker, kap_events or [], news_events or [], llm_analysis, as_of_date)] = "m5"

        # Motor 6: Katalizör
        futures[pool.submit(self.motor6.compute, ticker, upcoming_events or [], as_of_date)] = "m6"

        # Motor 8: Mean Reversion
        futures[pool.submit(self.motor8.compute, ticker, close, high, low, mask)] = "m8"

        # Motor 9: Seasonality
        if dates:
            futures[pool.submit(self.motor9.compute, ticker, close, dates, mask)] = "m9"

        # Sonuçları topla
        all_features: dict[str, float] = {}
        for future in as_completed(futures):
            try:
                all_features.update(future.result())
            except Exception as e:
                logger.warning("Motor failed", motor=futures[future], error=str(e))

        # Motor 7: Neden Düşüyor? (diğer motorlardan gelen feature'lara bağlı — sıranlı)
        stock_ret_5d = all_features.get("roc_5d", 0)
        stock_ret_20d = all_features.get("roc_20d", 0)
        vol_change = all_features.get("volume_zscore_20d", 0)
        vol_zscore = all_features.get("volume_zscore_20d", 0)
        news_sent = all_features.get("news_sentiment_weighted", 0)
        kap_sent = all_features.get("kap_sentiment_avg", 0)
        rsi = all_features.get("rsi_14", 50)
        atr = all_features.get("atr_pct", 0)

        m7 = self.motor7.compute(
            ticker, stock_ret_5d, stock_ret_20d,
            market_return_5d, market_return_20d,
            sector_return_5d, sector_return_20d,
            vol_change, vol_zscore, news_sent, kap_sent, rsi, atr
        )
        all_features.update(m7)

        # NaN/Inf temizle
        cleaned = {}
        for k, v in all_features.items():
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                cleaned[k] = 0.0
            else:
                cleaned[k] = v

        # === FEATURE ALIASES ===
        # Ranking modeli ve cross-sectional engine'in beklediği isimlerle
        # motor çıktıları arasında eşleme. Var olan feature'ları ezme.
        # === FEATURE CONTRACT ALIASES ===
        # Ranking model ve cross-sectional engine'in beklediği canonical isimler.
        # Kural: dst zaten varsa EZMEZ (canonical source korunur).
        _ALIAS_MAP = [
            # (source_name, canonical_name, source_motor)
            # Motor 1
            ("rs_peer_rank_5d",            "rs_peer_rank",            "motor1"),
            # Motor 2
            ("breakout_failure_20d",       "breakout_failure",        "motor2"),
            ("recovery_strength_20d",      "recovery_strength",       "motor2"),
            # Motor 3
            ("volume_percentile_20d",      "volume_percentile",       "motor3"),
            ("volume_up_down_ratio_20d",   "volume_up_down_ratio",    "motor3"),
            ("tick_rule_20d",              "tick_rule",               "motor3"),
            ("vwap_deviation_20d",         "vwap_deviation",          "motor3"),
            # Motor 4
            ("raw_roe",                    "roe",                     "motor4"),
            ("raw_roa",                    "roa",                     "motor4"),
            ("raw_profit_margin",          "profit_margin_pct",       "motor4"),
            # Motor 7
            ("fall_market_selloff_5d",     "fall_market_selloff",     "motor7"),
            ("fall_sector_selloff_5d",     "fall_sector_selloff",     "motor7"),
            # Motor 8 (Mean Reversion) — isim tutarsızlığı düzeltmesi
            ("rsi_14d",                    "rsi_14",                  "motor8"),
            ("rsi_5d",                     "rsi_5",                   "motor8"),
            ("rsi_21d",                    "rsi_21",                  "motor8"),
            ("williams_r_14d",             "williams_r",              "motor8"),
            ("cci_20d",                    "cci",                     "motor8"),
        ]

        for src, dst, _motor in _ALIAS_MAP:
            if src in cleaned and dst not in cleaned:
                cleaned[dst] = cleaned[src]
                # else: canonical source zaten var, ezme

        # return_* → roc_* mapping (cross-sectional RANK_TARGETS için)
        for period in [1, 5, 20, 60]:
            roc_key = f"roc_{period}d"
            ret_key = f"return_{period}d"
            if roc_key in cleaned and ret_key not in cleaned:
                cleaned[ret_key] = cleaned[roc_key]

        # volume_zscore: calculator canonical, motor3 fallback
        if "volume_zscore" not in cleaned and "volume_zscore_20d" in cleaned:
            cleaned["volume_zscore"] = cleaned["volume_zscore_20d"]

        # Regime bilgisi ekle
        cleaned["regime"] = market_regime

        # Feature sayısı
        cleaned["_feature_count"] = len(cleaned)

        return cleaned


# Backward-compatible alias
SevenMotorEngine = NineMotorEngine

# Singleton
seven_motor_engine = NineMotorEngine()
