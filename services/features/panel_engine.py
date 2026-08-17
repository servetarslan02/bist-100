"""
ALPHA BIST — Panel Feature Engine v1.0 (Vectorized / Batch)

Amaç:
    FeatureCalculator (scalar, mask-aware) ile BİREBİR AYNI sonuçları üreten,
    tek geçişli (single-pass) vektörize feature motoru.

Neden:
    Backtest engine v4.0 her (ticker, gün) çifti için feature'ları sıfırdan
    hesaplıyordu (FeatureCache tarih bazlı olduğu için hiç hit olmuyordu).
    Bu motor, skor hesaplamasında kullanılan feature'ları (rsi_14, momentum_20d,
    roc_5d, volume_zscore) her hisse için TÜM tarihlere tek seferde hesaplar.

Finansal eşdeğerlilik garantisi:
    - TradabilityMask.compute_mask (prev_close=None) semantiği birebir korunur.
      Kural 5 (>%30 sıçrama) pencere başlangıcında atlandığı için, pencere
      başlangıcı kural-5'e takılan (ticker, gün) çiftleri FALLBACK işaretlenir
      ve engine tarafından scalar yoldan yeniden hesaplanır.
    - "Son K geçerli değer" semantiği (invalid günler atlanır) prefix-sum
      ve rank dizileri ile birebir uygulanır.
    - Feature'lar scalar yoldaki gibi 4 ondalık basamağa yuvarlanır.

Bellek:
    Hisse başına 4 × float64 × n_bar. 1000 hisse × 252 gün ≈ 8 MB panel.

KURAL: Bu modül FeatureCalculator'ı DEĞİŞTİRMEZ; sadece aynı sonucu
       vektörize üretir. Şüpheli (borderline) durumlarda engine scalar
       yola düşer — finansal sonuç asla değişmez.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()

# Skoru etkileyen feature'lar (engine_v4._compute_score / backtest_runner._compute_score)
SCORE_FEATURES = ("rsi_14", "momentum_20d", "roc_5d", "volume_zscore")

# RSI / momentum / roc / volume-zscore parametreleri (calculator.py ile aynı)
RSI_PERIOD = 14
MOMENTUM_PERIOD = 20
ROC_PERIOD = 5
VOL_WINDOW = 20
REQUIRED_BARS = 60  # FeatureCalculator._required_bars


@dataclass
class TickerPanel:
    """Tek hisse için tüm tarihlere hesaplanmış feature paneli."""
    dates: pd.Index                 # Hisse kendi tarih index'i (sıralı)
    open_: np.ndarray               # float64 (n,)
    close: np.ndarray               # float64 (n,)
    rsi_14: np.ndarray              # (n,) — pos < lookback-1 için NaN
    momentum_20d: np.ndarray
    roc_5d: np.ndarray
    volume_zscore: np.ndarray
    fallback: np.ndarray            # bool (n,) — bu pos scalar yoldan hesaplanmalı
    use_scalar: bool = False        # Tüm hisse scalar yola düşsün (sırasız index vb.)


@dataclass
class PanelStore:
    """Tüm evrenin panel verisi."""
    panels: Dict[str, TickerPanel] = field(default_factory=dict)
    lookback: int = 60
    compute_seconds: float = 0.0


class PanelFeatureEngine:
    """Vektörize batch feature motoru.

    Kullanım:
        engine = PanelFeatureEngine()
        store = engine.compute(market_data, lookback=120)
        feats = engine.features_at(store, ticker, pos)  # {rsi_14, ...} veya None
    """

    def __init__(self, tradability_mask: Optional[Any] = None):
        if tradability_mask is None:
            from ..core.tradability_mask import TradabilityMask
            tradability_mask = TradabilityMask()
        self._tm = tradability_mask

    # ------------------------------------------------------------------
    # PUBLIC
    # ------------------------------------------------------------------

    def compute(
        self,
        market_data: Dict[str, pd.DataFrame],
        lookback: int,
    ) -> PanelStore:
        """Tüm hisseler için feature panelini tek geçişte hesapla."""
        import time as _time
        t0 = _time.time()
        store = PanelStore(lookback=lookback)

        for ticker, df in market_data.items():
            if df is None or df.empty or len(df) < lookback:
                continue
            store.panels[ticker] = self._compute_ticker(ticker, df, lookback)

        store.compute_seconds = _time.time() - t0
        logger.info("Panel features computed",
                    tickers=len(store.panels),
                    seconds=round(store.compute_seconds, 3))
        return store

    def features_at(
        self,
        panel: TickerPanel,
        pos: int,
        lookback: int,
    ) -> Optional[Dict[str, float]]:
        """(ticker, pos) için feature dict döndür.

        None → bu nokta için scalar (legacy) yol kullanılmalı.
        """
        if panel.use_scalar or pos < lookback - 1:
            return None
        if panel.fallback[pos]:
            return None
        rsi = panel.rsi_14[pos]
        mom = panel.momentum_20d[pos]
        roc = panel.roc_5d[pos]
        volz = panel.volume_zscore[pos]
        if np.isnan(rsi) or np.isnan(mom) or np.isnan(roc) or np.isnan(volz):
            return None
        return {
            "rsi_14": float(rsi),
            "momentum_20d": float(mom),
            "roc_5d": float(roc),
            "volume_zscore": float(volz),
        }

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------

    def _compute_ticker(
        self,
        ticker: str,
        df: pd.DataFrame,
        lookback: int,
    ) -> TickerPanel:
        """Tek hisse için vektörize panel hesabı."""
        n = len(df)
        idx = df.index

        open_ = df["Open"].values.astype(np.float64) if "Open" in df.columns \
            else df["Close"].values.astype(np.float64)
        high = df["High"].values.astype(np.float64)
        low = df["Low"].values.astype(np.float64)
        close = df["Close"].values.astype(np.float64)
        volume = df["Volume"].values.astype(np.float64) if "Volume" in df.columns \
            else np.ones(n)

        nan = np.full(n, np.nan)
        fallback = np.zeros(n, dtype=bool)

        # Sıralı olmayan index → scalar yola düş (legacy davranışı koru)
        if not idx.is_monotonic_increasing:
            return TickerPanel(idx, open_, close, nan.copy(), nan.copy(),
                               nan.copy(), nan.copy(), fallback, use_scalar=True)

        # ---- Mask (TradabilityMask ile birebir, prev_close=None) ----
        try:
            mask_res = self._tm.compute_mask(ticker, open_, high, low, close, volume)
            raw_mask = mask_res.mask if hasattr(mask_res, "mask") else mask_res
            if raw_mask is None or len(raw_mask) != n:
                return TickerPanel(idx, open_, close, nan.copy(), nan.copy(),
                                   nan.copy(), nan.copy(), fallback, use_scalar=True)
            global_mask = np.asarray(raw_mask)
        except Exception:
            return TickerPanel(idx, open_, close, nan.copy(), nan.copy(),
                               nan.copy(), nan.copy(), fallback, use_scalar=True)

        # Kural 5 (>%30 sıçrama) pencere başlangıcında scalar yolda atlanır.
        # Pencere başlangıcı bu kurala takılan pozisyonlar fallback'tir.
        with np.errstate(divide="ignore", invalid="ignore"):
            prev_close = np.concatenate([[close[0]], close[:-1]])
            jump = np.abs(close / prev_close - 1.0)
        rule5 = np.zeros(n, dtype=bool)
        rule5[1:] = (jump[1:] > 0.30) & (close[:-1] > 0)

        # maskA: kural 5 hariç satır-bazlı kurallar (1,2,3,6)
        # NOT: Negasyon bazlı yazım — NaN karşılaştırmaları False ürettiği için
        # scalar yoldaki "kural tetiklenmez → satır geçer" semantiği birebir korunur.
        with np.errstate(divide="ignore", invalid="ignore"):
            gap = np.abs(close / open_ - 1.0)
        maskA = (
            ~(close <= 0)                                   # kural 1
            & ~(volume <= 0)                                # kural 2
            & ~(high < low) & ~(high < close) & ~(low > close)  # kural 3
            & ~((open_ > 0) & (gap > 0.20))                 # kural 6
        )

        discrepancy = maskA & rule5 & (global_mask == 0)
        if np.any(discrepancy):
            disc_rows = np.flatnonzero(discrepancy)
            # window start s = pos - lookback + 1  →  pos = s + lookback - 1
            fallback_pos = disc_rows + lookback - 1
            fallback_pos = fallback_pos[fallback_pos < n]
            fallback[fallback_pos] = True

        # ---- Geçerlilik dizileri (scalar: where(mask==1, x, nan) sonra ~isnan) ----
        g = global_mask == 1
        valid_c = g & ~np.isnan(close)
        valid_v = g & ~np.isnan(volume)

        # ---- Close tabanlı feature'lar (son K geçerli değer semantiği) ----
        rsi = self._panel_rsi(close, valid_c, lookback, RSI_PERIOD)
        mom = self._panel_ratio(close, valid_c, lookback, MOMENTUM_PERIOD)
        roc = self._panel_ratio(close, valid_c, lookback, ROC_PERIOD)
        volz = self._panel_volume_zscore(volume, valid_v, lookback, VOL_WINDOW)

        # Scalar yoldaki gibi 4 ondalık yuvarlama
        rsi = np.round(rsi, 4)
        mom = np.round(mom, 4)
        roc = np.round(roc, 4)
        volz = np.round(volz, 4)

        return TickerPanel(idx, open_, close, rsi, mom, roc, volz, fallback)

    # ---- Vektörize "son K geçerli değer" primitifleri ----

    @staticmethod
    def _window_counts(valid: np.ndarray, lookback: int) -> np.ndarray:
        """Her pos için penceredeki [pos-L+1, pos] geçerli satır sayısı."""
        n = len(valid)
        cv = np.concatenate([[0], np.cumsum(valid)])
        counts = np.zeros(n, dtype=np.int64)
        # counts[pos] = cv[pos+1] - cv[pos-L+1]
        pos = np.arange(n)
        start = np.maximum(pos - lookback + 1, 0)
        counts = cv[pos + 1] - cv[start]
        return counts

    def _panel_ratio(
        self,
        close: np.ndarray,
        valid: np.ndarray,
        lookback: int,
        period: int,
    ) -> np.ndarray:
        """momentum/roc: (valid[-1]/valid[-period-1] - 1) * 100.

        Scalar: len(valid_window) <= period → 0.
        """
        n = len(close)
        out = np.zeros(n)
        counts = self._window_counts(valid, lookback)
        vrows = np.flatnonzero(valid)
        if len(vrows) == 0:
            return out
        cv = np.cumsum(valid)  # cv[pos] = pos dahil geçerli sayısı
        r_hi = cv - 1          # her pos için son geçerli satırın rankı

        ok = (counts > period) & (np.arange(n) >= lookback - 1)
        pos_ok = np.flatnonzero(ok)
        last_row = vrows[r_hi[pos_ok]]
        ref_row = vrows[r_hi[pos_ok] - period]
        c_last = close[last_row]
        c_ref = close[ref_row]
        with np.errstate(divide="ignore", invalid="ignore"):
            val = np.where(c_ref != 0, (c_last / c_ref - 1.0) * 100.0, 0.0)
        out[pos_ok] = val
        out[np.arange(n) < lookback - 1] = np.nan
        return out

    def _panel_rsi(
        self,
        close: np.ndarray,
        valid: np.ndarray,
        lookback: int,
        period: int,
    ) -> np.ndarray:
        """RSI: son `period` geçerli delta üzerinden (Wilder DEĞİL — calculator ile aynı).

        Scalar: len(valid_window) < period + 1 → 50.
        avg_gain = mean(gains[-period:]), avg_loss = mean(losses[-period:])
        avg_loss == 0 → 100; aksi halde 100 - 100/(1 + rs).
        """
        n = len(close)
        out = np.full(n, 50.0)
        counts = self._window_counts(valid, lookback)
        vrows = np.flatnonzero(valid)
        if len(vrows) < period + 1:
            out[np.arange(n) < lookback - 1] = np.nan
            return out

        # Rank uzayında delta/gain/loss
        vc = close[vrows]
        delta = np.diff(vc)                      # rank r >= 1 ↔ delta[r-1]
        gains = np.where(delta > 0, delta, 0.0)
        losses = np.where(delta < 0, -delta, 0.0)
        Gp = np.concatenate([[0.0], np.cumsum(gains)])   # Gp[k] = sum gain[0..k-1]
        Lp = np.concatenate([[0.0], np.cumsum(losses)])

        cv = np.cumsum(valid)
        r_hi = cv - 1

        ok = (counts >= period + 1) & (np.arange(n) >= lookback - 1)
        pos_ok = np.flatnonzero(ok)
        rh = r_hi[pos_ok]            # >= period
        # son period delta: ranklar rh-period+1 .. rh  ↔  delta index rh-period .. rh-1
        sum_g = Gp[rh] - Gp[rh - period]
        sum_l = Lp[rh] - Lp[rh - period]
        avg_g = sum_g / period
        avg_l = sum_l / period

        rsi_vals = np.where(
            avg_l == 0,
            100.0,
            100.0 - 100.0 / (1.0 + avg_g / np.where(avg_l == 0, 1.0, avg_l)),
        )
        out[pos_ok] = rsi_vals
        out[np.arange(n) < lookback - 1] = np.nan
        return out

    def _panel_volume_zscore(
        self,
        volume: np.ndarray,
        valid: np.ndarray,
        lookback: int,
        window: int,
    ) -> np.ndarray:
        """Volume z-score: son `window` geçerli hacim üzerinden.

        Scalar: len < window → 0; std == 0 → 0; np.std = population (ddof=0).
        """
        n = len(volume)
        out = np.zeros(n)
        counts = self._window_counts(valid, lookback)
        vrows = np.flatnonzero(valid)
        if len(vrows) < window:
            out[np.arange(n) < lookback - 1] = np.nan
            return out

        vv = volume[vrows]
        Sp = np.concatenate([[0.0], np.cumsum(vv)])
        S2p = np.concatenate([[0.0], np.cumsum(vv * vv)])

        cv = np.cumsum(valid)
        r_hi = cv - 1

        ok = (counts >= window) & (np.arange(n) >= lookback - 1)
        pos_ok = np.flatnonzero(ok)
        rh = r_hi[pos_ok]
        # son window değer: ranklar rh-window+1 .. rh
        s1 = Sp[rh + 1] - Sp[rh + 1 - window]
        s2 = S2p[rh + 1] - S2p[rh + 1 - window]
        mean = s1 / window
        var = s2 / window - mean * mean
        var = np.maximum(var, 0.0)
        std = np.sqrt(var)
        v_last = vv[rh]
        z = np.where(std != 0, (v_last - mean) / np.where(std == 0, 1.0, std), 0.0)
        out[pos_ok] = z
        out[np.arange(n) < lookback - 1] = np.nan
        return out
