# Seven Motors Feature Engine
# Core feature motors for BIST quantitative analysis

from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# === Düşüş Analizi Sabitleri ===
DEFAULT_FALL_5D_THRESHOLD: float = -2.0          # 5 günlük düşüş eşiği (%)
DEFAULT_FALL_20D_THRESHOLD: float = -5.0         # 20 günlük düşüş eşiği (%)
DEFAULT_MARKET_SELL_5D_THRESHOLD: float = -3.0   # Piyasa 5 günlük satış eşiği (%)
DEFAULT_MARKET_SELL_20D_THRESHOLD: float = -5.0  # Piyasa 20 günlük satış eşiği (%)
DEFAULT_SECTOR_SELL_5D_THRESHOLD: float = -5.0   # Sektör 5 günlük satış eşiği (%)
DEFAULT_SECTOR_SELL_20D_THRESHOLD: float = -8.0  # Sektör 20 günlük satış eşiği (%)
DEFAULT_MARKET_FLAT_5D: float = -1.0             # Piyasa durgun eşiği (%)
DEFAULT_SECTOR_FLAT_5D: float = -2.0             # Sektör durgun eşiği (%)
DEFAULT_COMPANY_SPECIFIC_DROP: float = -5.0      # Şirkete özgü düşüş eşiği (%)
DEFAULT_VOLUME_ZSCORE_HIGH: float = 2.0          # Hacim z-score yüksek eşik
DEFAULT_VOLUME_ZSCORE_LOW: float = 1.0           # Hacim z-score düşük eşik
DEFAULT_PANIC_DROP_5D: float = -10.0             # Panik satış eşiği (%)
DEFAULT_PANIC_SENTIMENT: float = -0.3            # Panik sentiment eşiği
DEFAULT_OVERSOLD_RSI: float = 30.0               # Aşırı satım RSI eşiği
DEFAULT_HIGH_VOL_ATR: float = 5.0                # Yüksek volatilite ATR eşiği (%)
DEFAULT_NEG_SENTIMENT_STRONG: float = -0.5       # Güçlü negatif sentiment eşiği
DEFAULT_DEEP_DRAWDOWN: float = -15.0             # Derin düşüş eşiği (%)
DEFAULT_RISK_CAP: float = 100.0                  # Risk skoru üst sınır


class RelativeStrengthMotor:
    """Computes relative strength features vs benchmark."""

    def compute(
        self,
        ticker: str,
        stock_close: np.ndarray,
        benchmark_close: np.ndarray,
    ) -> dict[str, float]:
        """Compute relative strength features.

        Args:
            ticker: Stock ticker
            stock_close: Stock closing prices
            benchmark_close: Benchmark closing prices

        Returns:
            Dict of feature_name -> value
        """
        result: dict[str, float] = {}

        if len(stock_close) < 20 or len(benchmark_close) < 20:
            return result

        # Relative strength (stock / benchmark ratio)
        with np.errstate(divide="ignore", invalid="ignore"):
            rs = np.where(benchmark_close > 0, stock_close / benchmark_close, np.nan)
        rs = rs[np.isfinite(rs)]
        if len(rs) < 5:
            return result

        # RS momentum (5d, 20d)
        result["rs_5d"] = float((rs[-1] / rs[-5] - 1.0) * 100) if len(rs) >= 5 else 0.0
        result["rs_20d"] = float((rs[-1] / rs[-20] - 1.0) * 100) if len(rs) >= 20 else 0.0

        # RS trend (linear regression slope)
        if len(rs) >= 20:
            x = np.arange(20)
            slope = np.polyfit(x, rs[-20:], 1)[0]
            result["rs_trend"] = float(slope)

        return result


class SeasonalityMotor:
    """Computes seasonality features based on historical patterns."""

    def compute(
        self,
        ticker: str,
        close_arr: np.ndarray,
        dates_list: list | None = None,
    ) -> dict[str, float]:
        """Compute seasonality features.

        Args:
            ticker: Stock ticker
            close_arr: Closing prices (at least 252 days)
            dates_list: Optional list of dates for calendar effects

        Returns:
            Dict of feature_name -> value
        """
        result: dict[str, float] = {}

        if len(close_arr) < 252:
            return result

        # Monthly returns pattern
        returns = np.diff(np.log(close_arr))
        if len(returns) < 20:
            return result

        # Recent vs historical momentum
        ret_5d = float((close_arr[-1] / close_arr[-5] - 1.0) * 100) if len(close_arr) >= 5 else 0.0
        ret_20d = float((close_arr[-1] / close_arr[-20] - 1.0) * 100) if len(close_arr) >= 20 else 0.0
        ret_60d = float((close_arr[-1] / close_arr[-60] - 1.0) * 100) if len(close_arr) >= 60 else 0.0

        result["seasonality_5d"] = ret_5d
        result["seasonality_20d"] = ret_20d
        result["seasonality_60d"] = ret_60d

        # Volatility regime
        vol_recent = float(np.std(returns[-20:])) if len(returns) >= 20 else 0.0
        vol_hist = float(np.std(returns[-252:])) if len(returns) >= 252 else float(np.std(returns))
        result["seasonality_vol_ratio"] = vol_recent / vol_hist if vol_hist > 1e-10 else 1.0

        return result


class MomentumMotor:
    """Momentum feature hesaplama motoru."""

    def compute(self, ticker: str, close: np.ndarray, lookback: int = 20) -> dict[str, float]:
        """Momentum feature'larını hesapla.

        Args:
            ticker: Hisse senedi kodu.
            close: Kapanış fiyatları dizisi.
            lookback: Geriye bakış penceresi.

        Returns:
            Feature dict'i: momentum_mean, momentum_std.
        """
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        returns = np.diff(np.log(close[-lookback:]))
        result["momentum_mean"] = float(np.mean(returns))
        result["momentum_std"] = float(np.std(returns))
        return result


class VolumeMotor:
    """Hacim feature hesaplama motoru."""

    def compute(self, ticker: str, volume: np.ndarray, lookback: int = 20) -> dict[str, float]:
        """Hacim feature'larını hesapla.

        Args:
            ticker: Hisse senedi kodu.
            volume: Hacim dizisi.
            lookback: Geriye bakış penceresi.

        Returns:
            Feature dict'i: volume_ratio.
        """
        result: dict[str, float] = {}
        if len(volume) < lookback:
            return result
        vol_arr = volume[-lookback:]
        avg = np.mean(vol_arr)
        result["volume_ratio"] = float(vol_arr[-1] / avg) if avg > 0 else 1.0
        return result


class VolatilityMotor:
    """Volatilite feature hesaplama motoru."""

    def compute(self, ticker: str, close: np.ndarray, lookback: int = 20) -> dict[str, float]:
        """Volatilite feature'larını hesapla.

        Args:
            ticker: Hisse senedi kodu.
            close: Kapanış fiyatları dizisi.
            lookback: Geriye bakış penceresi.

        Returns:
            Feature dict'i: volatility.
        """
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        returns = np.diff(np.log(close[-lookback:]))
        result["volatility"] = float(np.std(returns) * np.sqrt(252))
        return result


class MeanReversionMotor:
    """Ortalama geri dönüş feature hesaplama motoru."""

    def compute(self, ticker: str, close: np.ndarray, lookback: int = 20) -> dict[str, float]:
        """Ortalama geri dönüş feature'larını hesapla.

        Args:
            ticker: Hisse senedi kodu.
            close: Kapanış fiyatları dizisi.
            lookback: Geriye bakış penceresi.

        Returns:
            Feature dict'i: mean_reversion.
        """
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        sma = np.mean(close[-lookback:])
        result["mean_reversion"] = float((close[-1] - sma) / sma) if sma > 0 else 0.0
        return result


class MicrostructureMotor:
    """Mikro yapı feature hesaplama motoru."""

    def compute(
        self, ticker: str, high: np.ndarray, low: np.ndarray, close: np.ndarray, lookback: int = 20
    ) -> dict[str, float]:
        """Mikro yapı feature'larını hesapla.

        Args:
            ticker: Hisse senedi kodu.
            high: En yüksek fiyat dizisi.
            low: En düşük fiyat dizisi.
            close: Kapanış fiyatları dizisi.
            lookback: Geriye bakış penceresi.

        Returns:
            Feature dict'i: spread.
        """
        result: dict[str, float] = {}
        if len(close) < lookback:
            return result
        hl_range = high[-lookback:] - low[-lookback:]
        result["spread"] = float(np.mean(hl_range / close[-lookback:])) if np.all(close[-lookback:] > 0) else 0.0
        return result


class WhyFallingMotor:
    """Düşen bıçağı tutma hatasını önle — çok faktörlü analiz."""

    def __repr__(self) -> str:
        return "WhyFallingMotor()"

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
        """Düşüş nedeni sınıflandırması — çok faktörlü analiz.

        Düşüşün geçici mi kalıcı mı olduğunu belirler.
        Piyasa geneli satış, sektör satışı, şirket olayları,
        likidite krizi ve aşırı satım koşullarını analiz eder.

        Args:
            ticker: Hisse senedi kodu.
            stock_return_5d: Hisse 5 günlük getiri (%).
            stock_return_20d: Hisse 20 günlük getiri (%).
            market_return_5d: Piyasa 5 günlük getiri (%).
            market_return_20d: Piyasa 20 günlük getiri (%).
            sector_return_5d: Sektör 5 günlük getiri (%).
            sector_return_20d: Sektör 20 günlük getiri (%).
            volume_change: Hacim değişimi.
            volume_zscore: Hacim z-score.
            news_sentiment: Haber sentiment skoru (-1 ile +1).
            kap_sentiment: KAP sentiment skoru (-1 ile +1).
            rsi: RSI değeri (varsayılan 50).
            atr_pct: ATR yüzdesi (varsayılan 0).

        Returns:
            Feature dict'i: is_falling, fall_severity, falling_is_temporary, catch_falling_knife_risk vb.
        """
        features: dict[str, float] = {}

        # Düşüş var mı?
        is_falling_5d = stock_return_5d < DEFAULT_FALL_5D_THRESHOLD
        is_falling_20d = stock_return_20d < DEFAULT_FALL_20D_THRESHOLD
        features["is_falling_5d"] = 1.0 if is_falling_5d else 0.0
        features["is_falling_20d"] = 1.0 if is_falling_20d else 0.0

        # Geriye uyumluluk: why_falling anahtarı
        features["why_falling"] = 1.0 if (is_falling_5d or is_falling_20d) else 0.0

        if not is_falling_5d and not is_falling_20d:
            features["falling_is_temporary"] = 0.5
            features["fall_severity"] = 0.0
            return features

        # Düşüş şiddeti
        features["fall_severity"] = round(abs(min(stock_return_5d, 0)), 4)

        # Market selloff tespiti (5d ve 20d)
        features["fall_market_selloff_5d"] = 1.0 if market_return_5d < DEFAULT_MARKET_SELL_5D_THRESHOLD else 0.0
        features["fall_market_selloff_20d"] = 1.0 if market_return_20d < DEFAULT_MARKET_SELL_20D_THRESHOLD else 0.0

        # Sector selloff tespiti
        features["fall_sector_selloff_5d"] = 1.0 if sector_return_5d < DEFAULT_SECTOR_SELL_5D_THRESHOLD else 0.0
        features["fall_sector_selloff_20d"] = 1.0 if sector_return_20d < DEFAULT_SECTOR_SELL_20D_THRESHOLD else 0.0

        # Company-specific (piyasa ve sektör düşmemişse)
        features["fall_company_specific_5d"] = (
            1.0
            if (
                market_return_5d > DEFAULT_MARKET_FLAT_5D
                and sector_return_5d > DEFAULT_SECTOR_FLAT_5D
                and stock_return_5d < DEFAULT_COMPANY_SPECIFIC_DROP
            )
            else 0.0
        )

        # Liquidity event (hacim patlaması + fiyat düşüşü)
        features["fall_liquidity_event"] = (
            1.0 if (volume_zscore > DEFAULT_VOLUME_ZSCORE_HIGH and stock_return_5d < DEFAULT_COMPANY_SPECIFIC_DROP) else 0.0
        )

        # Temporary panic (hızlı düşüş + negatif sentiment düşük)
        features["fall_temporary_panic"] = (
            1.0 if (stock_return_5d < DEFAULT_PANIC_DROP_5D and news_sentiment > DEFAULT_PANIC_SENTIMENT) else 0.0
        )

        # Oversold bounce potential (RSI < 30 + düşüş şiddetli)
        features["fall_oversold_bounce"] = (
            1.0 if (rsi < DEFAULT_OVERSOLD_RSI and stock_return_5d < DEFAULT_COMPANY_SPECIFIC_DROP) else 0.0
        )

        # High volatility crash (ATR yüksek + düşüş)
        features["fall_high_vol_crash"] = (
            1.0 if (atr_pct > DEFAULT_HIGH_VOL_ATR and stock_return_5d < DEFAULT_COMPANY_SPECIFIC_DROP) else 0.0
        )

        # Düşüş nedeni geçici mi kalıcı mı? (Çok faktörlü)
        temporary_score = 0.0
        if features.get("fall_market_selloff_5d", 0) == 1.0:
            temporary_score += SCORE_MARKET_SELL_5D
        if features.get("fall_sector_selloff_5d", 0) == 1.0:
            temporary_score += SCORE_SECTOR_SELL_5D
        if features.get("fall_temporary_panic", 0) == 1.0:
            temporary_score += SCORE_TEMPORARY_PANIC
        if features.get("fall_oversold_bounce", 0) == 1.0:
            temporary_score += SCORE_OVERSOLD_BOUNCE
        if volume_zscore < DEFAULT_VOLUME_ZSCORE_LOW:
            temporary_score += SCORE_LOW_VOLUME

        permanent_score = 0.0
        if features.get("fall_company_specific_5d", 0) == 1.0:
            permanent_score += SCORE_COMPANY_SPECIFIC
        if features.get("fall_liquidity_event", 0) == 1.0:
            permanent_score += SCORE_LIQUIDITY_EVENT
        if kap_sentiment < DEFAULT_NEG_SENTIMENT_STRONG:
            permanent_score += SCORE_KAP_NEGATIVE
        if news_sentiment < DEFAULT_NEG_SENTIMENT_STRONG:
            permanent_score += SCORE_NEWS_NEGATIVE

        total = temporary_score + permanent_score
        if total > 0:
            features["falling_is_temporary"] = round(temporary_score / total, 4)
            features["falling_is_permanent"] = round(permanent_score / total, 4)
        else:
            features["falling_is_temporary"] = 0.5
            features["falling_is_permanent"] = 0.5

        # Catch falling knife risk (0 = güvenli, 1 = tehlikeli)
        risk_score = 0.0
        if features.get("fall_company_specific_5d", 0) == 1.0:
            risk_score += SCORE_PERMANENT_COMPANY
        if features.get("fall_liquidity_event", 0) == 1.0:
            risk_score += SCORE_PERMANENT_LIQUIDITY
        if features.get("fall_high_vol_crash", 0) == 1.0:
            risk_score += SCORE_HIGH_VOL_CRASH
        if stock_return_20d < DEFAULT_DEEP_DRAWDOWN:
            risk_score += SCORE_DEEP_DRAWDOWN

        features["catch_falling_knife_risk"] = int(min(DEFAULT_RISK_CAP, risk_score))

        return features


__all__: list[str] = ["RelativeStrengthMotor", "SeasonalityMotor", "MomentumMotor", "VolumeMotor", "VolatilityMotor", "MeanReversionMotor", "MicrostructureMotor", "WhyFallingMotor"]
