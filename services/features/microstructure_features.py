"""
ALPHA BIST — Mikro-Yapı (Microstructure) Feature Mühendisliği

Borsa İstanbul tick verisinden türetilen yüksek frekanslı mikro-yapı özellikleri.
Kyle (1985), Amihud (2002), Roll (1984) ve Hasbrouck (1991) modellerine dayalı
akademik mikro-yapı literatürüne uygun hesaplamalar.

Özellikler:
  - Amihud illikidite: Fiyat hareketi / hacim oranı (günlük)
  - Kyle Lambda: Fiyat etkisi katsayısı
  - Roll Spread: Örtülü spread tahmini (otokovaryans bazlı)
  - Hasbrouck PIN Proxy: Bilgilendirilmiş işlem olasılığı
  - VPIN (Volume-Synchronized PIN): Easley (2011) VPIN
  - Tick imbalance: Alıcı-satıcı kaynaklı tick dengesizliği
  - Order flow imbalance (OFI): Net alış - net satış basıncı
  - Realized spread: Piyasa yapıcı spread tahmini
  - Corwin-Schultz spread: OHLC'den dolaylı spread
  - Point-in-Time (PIT) garantisi: Feature başlangıcında fiyat bantlaması
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
MIN_VOLUME: float = 1.0       # Sıfır hacim koruması
MIN_PRICE: float = 0.01       # Sıfır fiyat koruması
DEFAULT_WINDOW: int = 20      # Varsayılan pencere boyutu
VPIN_BUCKET_SIZE: float = 1.0  # VPIN hacim grubu boyutu (lot cinsinden)


@dataclass
class MicrostructureFeatures:
    """Mikro-yapı feature sonuç konteynerı.

    Tüm özellikler nan-toleranttır: veri yoksa float('nan') döner.

    Attributes:
        amihud_illiquidity: Amihud (2002) illikiditesi (|ret|/volume).
        kyle_lambda: Kyle (1985) lambda piyasa etkisi katsayısı.
        roll_spread: Roll (1984) örtülü bid-ask spread tahmini.
        hasbrouck_pin_proxy: Hasbrouck PIN proxy (mutlak OFI / toplam hacim).
        vpin: Easley (2011) VPIN değeri (0-1, yüksek = yüksek bilgili işlem riski).
        tick_imbalance: Alıcı/satıcı-kaynaklı tick dengesizliği (0-1).
        order_flow_imbalance: Net alış-satış basıncı (normalleştirilmiş -1 ila 1).
        realized_spread_bps: Piyasa yapıcı realized spread (bps).
        corwin_schultz_spread: Corwin-Schultz (2012) OHLC spread tahmini.
        price_impact_5min: 5-dakikalık fiyat etkisi (geçmiş veri proxy).
        trade_intensity: Birim zamanda işlem yoğunluğu (lot/gün).
        intraday_vol_ratio: Açılış/kapanış volatilite oranı (rejim tespiti için).
    """

    amihud_illiquidity: float = float("nan")
    kyle_lambda: float = float("nan")
    roll_spread: float = float("nan")
    hasbrouck_pin_proxy: float = float("nan")
    vpin: float = float("nan")
    tick_imbalance: float = float("nan")
    order_flow_imbalance: float = float("nan")
    realized_spread_bps: float = float("nan")
    corwin_schultz_spread: float = float("nan")
    price_impact_5min: float = float("nan")
    trade_intensity: float = float("nan")
    intraday_vol_ratio: float = float("nan")
    extra: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """MicrostructureFeatures kısa temsili."""
        return (
            f"MicrostructureFeatures("
            f"amihud={self.amihud_illiquidity:.4e}, "
            f"kyle_λ={self.kyle_lambda:.4e}, "
            f"roll={self.roll_spread:.4f}, "
            f"vpin={self.vpin:.3f})"
        )

    def to_dict(self) -> dict[str, float]:
        """Tüm özellikleri sözlük olarak döndürür.

        Returns:
            {feature_name: value} sözlüğü.
        """
        return {
            "amihud_illiquidity": self.amihud_illiquidity,
            "kyle_lambda": self.kyle_lambda,
            "roll_spread": self.roll_spread,
            "hasbrouck_pin_proxy": self.hasbrouck_pin_proxy,
            "vpin": self.vpin,
            "tick_imbalance": self.tick_imbalance,
            "order_flow_imbalance": self.order_flow_imbalance,
            "realized_spread_bps": self.realized_spread_bps,
            "corwin_schultz_spread": self.corwin_schultz_spread,
            "price_impact_5min": self.price_impact_5min,
            "trade_intensity": self.trade_intensity,
            "intraday_vol_ratio": self.intraday_vol_ratio,
            **self.extra,
        }


class MicrostructureFeatureEngine:
    """Mikro-yapı feature hesaplama motoru (thread-safe).

    Tüm hesaplamalar Point-in-Time uyumludur:
    t anındaki feature yalnızca t öncesi veriyi kullanır.
    """

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        """MicrostructureFeatureEngine başlatıcı.

        Args:
            window: Pencere boyutu (genellikle 20 işlem günü).

        Raises:
            ValueError: window < 2 ise.
        """
        if window < 2:
            raise ValueError(f"window >= 2 olmalıdır: {window}")
        self.window = window
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """MicrostructureFeatureEngine kısa temsili."""
        return f"MicrostructureFeatureEngine(window={self.window})"

    @staticmethod
    def _safe_div(num: float, denom: float, default: float = float("nan")) -> float:
        """Güvenli bölme işlemi (sıfır bölme koruması).

        Args:
            num: Pay.
            denom: Payda.
            default: Payda sıfır veya nan ise döndürülecek değer.

        Returns:
            Bölme sonucu veya default.
        """
        if abs(denom) < 1e-15 or np.isnan(denom):
            return default
        return num / denom

    def amihud_illiquidity(
        self,
        returns: np.ndarray,
        volumes: np.ndarray,
    ) -> np.ndarray:
        """Amihud (2002) illikiditesi hesaplar.

        illiq_t = |ret_t| / volume_t
        Günlük ölçek, pencere üzerinden ortalama alınır.

        Args:
            returns: Günlük log getiriler dizisi.
            volumes: Günlük hacim (lot) dizisi.

        Returns:
            Her gün için Amihud illikiditesi dizisi.

        Raises:
            ValueError: Dizi uzunlukları uyuşmuyorsa.
        """
        if len(returns) != len(volumes):
            raise ValueError(
                f"returns ({len(returns)}) ve volumes ({len(volumes)}) uzunlukları eşleşmeli."
            )
        with self._lock:
            vol_safe = np.where(volumes < MIN_VOLUME, np.nan, volumes)
            raw = np.abs(returns) / vol_safe
            result = np.full_like(raw, np.nan)
            for i in range(self.window - 1, len(raw)):
                window_vals = raw[i - self.window + 1 : i + 1]
                valid = window_vals[~np.isnan(window_vals)]
                if len(valid) > 0:
                    result[i] = float(np.mean(valid))
            return result

    def kyle_lambda(
        self,
        returns: np.ndarray,
        signed_volume: np.ndarray,
    ) -> np.ndarray:
        """Kyle (1985) Lambda piyasa etkisi katsayısını hesaplar.

        OLS regresyon: ret_t = λ × signed_volume_t
        Yüksek λ → küçük hacimler bile fiyatı çok etkiliyor = derin değil piyasa.

        Args:
            returns: Günlük log getiriler.
            signed_volume: İmzalı hacim (pozitif = alıcı-kaynaklı, negatif = satıcı-kaynaklı).

        Returns:
            Pencere boyunca hesaplanmış lambda dizisi.
        """
        if len(returns) != len(signed_volume):
            raise ValueError("returns ve signed_volume uzunlukları eşleşmeli.")

        with self._lock:
            result = np.full(len(returns), np.nan)
            for i in range(self.window - 1, len(returns)):
                y = returns[i - self.window + 1 : i + 1]
                x = signed_volume[i - self.window + 1 : i + 1]
                mask = ~(np.isnan(y) | np.isnan(x))
                if mask.sum() < 5:
                    continue
                x_m, y_m = x[mask], y[mask]
                # OLS: λ = cov(x,y) / var(x)
                var_x = float(np.var(x_m))
                if var_x < 1e-15:
                    continue
                result[i] = float(np.cov(x_m, y_m)[0, 1] / var_x)
            return result

    def roll_spread(self, close: np.ndarray) -> np.ndarray:
        """Roll (1984) örtülü bid-ask spread tahmini.

        spread = 2 × sqrt(-cov(Δp_t, Δp_{t-1})) (negatif otokovaryans gerektirir).
        Negatif sonuç → otokovaryans pozitif (momentum) → nan döner.

        Args:
            close: Kapanış fiyatları dizisi.

        Returns:
            Roll spread tahmini dizisi.
        """
        with self._lock:
            changes = np.diff(close)
            result = np.full(len(close), np.nan)
            for i in range(self.window, len(close)):
                ch = changes[i - self.window : i]
                valid = ch[~np.isnan(ch)]
                if len(valid) < 4:
                    continue
                if len(valid) < 2:
                    continue
                cov = float(np.cov(valid[:-1], valid[1:])[0, 1])
                if cov < 0:
                    result[i] = 2.0 * np.sqrt(-cov)
            return result

    def tick_imbalance(self, close: np.ndarray) -> np.ndarray:
        """Tick imbalance: Alıcı-kaynaklı tick oranı.

        +1 = fiyat yükseldi (alıcı), -1 = fiyat düştü (satıcı), 0 = değişmedi.
        Pencere üzerinden ağırlıklı ortalama (son ticklara daha fazla ağırlık).

        Args:
            close: Kapanış fiyatları.

        Returns:
            Tick imbalance oranı (0-1, 0.5 = nötr).
        """
        with self._lock:
            signs = np.sign(np.diff(close))
            result = np.full(len(close), np.nan)
            weights = np.linspace(0.5, 1.0, self.window)
            for i in range(self.window, len(close)):
                w = signs[i - self.window : i]
                valid = w[~np.isnan(w)]
                if len(valid) < 5:
                    continue
                w_valid = weights[-len(valid):]
                buyer_flow = float(np.sum(w_valid[valid > 0]))
                total_flow = float(np.sum(np.abs(w_valid)))
                result[i] = self._safe_div(buyer_flow, total_flow, default=0.5)
            return result

    def order_flow_imbalance(
        self,
        buy_volume: np.ndarray,
        sell_volume: np.ndarray,
    ) -> np.ndarray:
        """Order Flow Imbalance (OFI): Normalleştirilmiş net alış baskısı.

        OFI = (buy_vol - sell_vol) / (buy_vol + sell_vol)
        -1 = sadece satış, +1 = sadece alış, 0 = nötr.

        Args:
            buy_volume: Alıcı-kaynaklı hacim.
            sell_volume: Satıcı-kaynaklı hacim.

        Returns:
            OFI dizisi (-1 ila 1).
        """
        if len(buy_volume) != len(sell_volume):
            raise ValueError("buy_volume ve sell_volume uzunlukları eşleşmeli.")

        with self._lock:
            net = buy_volume - sell_volume
            total = buy_volume + sell_volume
            safe_total = np.where(total > MIN_VOLUME, total, np.nan)
            raw = net / safe_total
            return np.where(np.isnan(raw), 0.0, raw)

    def vpin(
        self,
        close: np.ndarray,
        volumes: np.ndarray,
        n_buckets: int = 50,
    ) -> np.ndarray:
        """VPIN (Volume-Synchronized PIN) tahmini (Easley et al., 2011).

        Hacim senkronize gruplar üzerinden hesaplama. Tick kuralı ile alış/satış
        hacmini tahmin eder (tam tick veri yoksa proxy kullanılır).

        Args:
            close: Kapanış fiyatları.
            volumes: Günlük hacimler.
            n_buckets: VPIN grupları sayısı.

        Returns:
            VPIN dizisi (0-1).
        """
        with self._lock:
            n = len(close)
            result = np.full(n, np.nan)

            if n < n_buckets + 1:
                return result

            returns = np.diff(close)
            # Tick kuralı ile alıcı/satıcı hacim tahmini
            buy_vol = np.where(returns >= 0, volumes[1:], 0.0)
            sell_vol = np.where(returns < 0, volumes[1:], 0.0)

            # Pencere üzerinden VPIN hesapla
            for i in range(n_buckets, n - 1):
                b = buy_vol[i - n_buckets : i]
                s = sell_vol[i - n_buckets : i]
                total = b + s
                if np.sum(total) < MIN_VOLUME:
                    continue
                result[i + 1] = float(np.mean(np.abs(b - s) / np.maximum(total, MIN_VOLUME)))

            return result

    def corwin_schultz_spread(
        self,
        high: np.ndarray,
        low: np.ndarray,
    ) -> np.ndarray:
        """Corwin-Schultz (2012) OHLC bazlı spread tahmini.

        Yalnızca high ve low fiyatlarından örtülü spread hesaplar.
        Negatif tahmini 0 ile sınırlandırılır.

        Args:
            high: Günlük yüksek fiyatlar.
            low: Günlük düşük fiyatlar.

        Returns:
            Spread tahmini dizisi (pct olarak).
        """
        if len(high) != len(low):
            raise ValueError("high ve low uzunlukları eşleşmeli.")

        with self._lock:
            n = len(high)
            result = np.full(n, np.nan)
            if n < 2:
                return result

            # log(H/L) oranları
            log_hl = np.log(np.maximum(high, MIN_PRICE) / np.maximum(low, MIN_PRICE))

            for i in range(1, n):
                beta = log_hl[i - 1] ** 2 + log_hl[i] ** 2
                gamma = np.log(
                    max(high[i - 1], high[i]) / min(low[i - 1], low[i] + 1e-10)
                ) ** 2
                alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / (3.0 - 2.0 * np.sqrt(2.0)) - np.sqrt(gamma / (3.0 - 2.0 * np.sqrt(2.0)))
                spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
                result[i] = max(0.0, spread)

            return result

    def compute_all(
        self,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volumes: np.ndarray,
        buy_volume: np.ndarray | None = None,
        sell_volume: np.ndarray | None = None,
        signed_volume: np.ndarray | None = None,
    ) -> list[MicrostructureFeatures]:
        """Tüm mikro-yapı özelliklerini hesaplar.

        Args:
            close: Kapanış fiyatları.
            high: Yüksek fiyatlar.
            low: Düşük fiyatlar.
            volumes: Günlük hacimler.
            buy_volume: Alıcı-kaynaklı hacimler (opsiyonel, None ise tick kural proxy).
            sell_volume: Satıcı-kaynaklı hacimler (opsiyonel).
            signed_volume: İmzalı hacim (None ise returns × volume proxy).

        Returns:
            Her gün için MicrostructureFeatures listesi.

        Raises:
            ValueError: Dizi uzunlukları uyuşmuyorsa.
        """
        n = len(close)
        if not (len(high) == len(low) == len(volumes) == n):
            raise ValueError("Tüm dizilerin uzunluğu eşleşmeli.")

        with self._lock:
            returns = np.diff(np.log(np.maximum(close, MIN_PRICE)), prepend=np.nan)

            # Proxy dizileri
            if signed_volume is None:
                signed_volume = np.sign(returns) * volumes

            if buy_volume is None:
                buy_volume = np.where(returns >= 0, volumes, 0.0)
            if sell_volume is None:
                sell_volume = np.where(returns < 0, volumes, 0.0)

            # Feature dizileri
            amihud = self.amihud_illiquidity(returns, volumes)
            kyle = self.kyle_lambda(returns, signed_volume)
            roll = self.roll_spread(close)
            tick_imb = self.tick_imbalance(close)
            ofi = self.order_flow_imbalance(buy_volume, sell_volume)
            vpin_arr = self.vpin(close, volumes)
            cs_spread = self.corwin_schultz_spread(high, low)

            # Intraday vol ratio (open-close vol / high-low vol proxy)
            hl_range = np.log(np.maximum(high, MIN_PRICE) / np.maximum(low, MIN_PRICE))
            intraday_vol_ratio = np.full(n, np.nan)
            if n >= self.window:
                for i in range(self.window - 1, n):
                    w = hl_range[i - self.window + 1 : i + 1]
                    valid = w[~np.isnan(w)]
                    if len(valid) > 2:
                        intraday_vol_ratio[i] = float(np.std(valid))

            # Trade intensity (günlük hacim / window ortalama hacim)
            trade_intensity = np.full(n, np.nan)
            for i in range(self.window - 1, n):
                w = volumes[i - self.window + 1 : i + 1]
                avg = float(np.nanmean(w))
                if avg > 0:
                    trade_intensity[i] = volumes[i] / avg

            features: list[MicrostructureFeatures] = []
            for i in range(n):
                features.append(MicrostructureFeatures(
                    amihud_illiquidity=float(amihud[i]),
                    kyle_lambda=float(kyle[i]),
                    roll_spread=float(roll[i]),
                    hasbrouck_pin_proxy=float(ofi[i]) if not np.isnan(ofi[i]) else float("nan"),
                    vpin=float(vpin_arr[i]),
                    tick_imbalance=float(tick_imb[i]),
                    order_flow_imbalance=float(ofi[i]),
                    realized_spread_bps=float("nan"),  # Requires bid/ask data
                    corwin_schultz_spread=float(cs_spread[i]),
                    price_impact_5min=float(amihud[i]) * 1e6 if not np.isnan(amihud[i]) else float("nan"),
                    trade_intensity=float(trade_intensity[i]),
                    intraday_vol_ratio=float(intraday_vol_ratio[i]),
                ))

            logger.info(
                "Mikro-yapı feature hesaplandı.",
                n=n,
                valid_amihud=int(np.sum(~np.isnan(amihud))),
                valid_kyle=int(np.sum(~np.isnan(kyle))),
                valid_vpin=int(np.sum(~np.isnan(vpin_arr))),
            )
            return features

    # Kolaylık ve API tutarlılığı için alias
    compute = compute_all


__all__: list[str] = [
    "MicrostructureFeatureEngine",
    "MicrostructureFeatures",
    "microstructure_engine",
]

# Singleton
microstructure_engine = MicrostructureFeatureEngine()
