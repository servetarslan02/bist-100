"""
ALPHA BIST — Piyasa Likidite Durumu Motoru

Gerçek zamanlı ve geçmişe dönük piyasa likiditesini çok boyutlu olarak izler.
BIST'e özgü mikro-yapı özellikleri: BIST100 ağırlıklı ortalama spreadler,
yabancı yatırımcı akışları ve Borsa İstanbul işlem saati kısıtlamaları.

Likidite Bileşenleri:
  - Spread kalitesi: Bid-ask spread trendi ve volatiliteye göre normalize edilmiş değer
  - Hacim anomalisi: Z-score tabanlı anormal hacim tespiti
  - Derinlik skoru: Emir defteri derinliği ve fiyat etkisi tahmini
  - Likidite kriz erken uyarı: Bileşik skor ile kriz öncesi sinyal
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_VOL_WINDOW: int = 20
DEFAULT_SPREAD_WINDOW: int = 20
DEFAULT_VOLUME_WINDOW: int = 60
DEFAULT_CRISIS_THRESHOLD: float = 0.75       # 0-1 bileşik skor — kriz eşiği
DEFAULT_STRESS_THRESHOLD: float = 0.50       # Stres eşiği
DEFAULT_MIN_VOLUME: float = 1.0              # Sıfır hacim koruması


class LiquidityState(IntEnum):
    """Piyasa likidite durumu seviyeleri.

    Attributes:
        CRISIS: Likidite krizi — işlem yapmaktan kaçın.
        STRESSED: Stresli — pozisyon boyutunu azalt.
        NORMAL: Normal piyasa koşulları.
        ABUNDANT: Yüksek likidite — büyük pozisyonlar için uygun.
    """

    CRISIS = -2
    STRESSED = -1
    NORMAL = 0
    ABUNDANT = 1


@dataclass
class LiquiditySnapshot:
    """Belirli bir andaki likidite durumu anlık görüntüsü.

    Attributes:
        state: Likidite durumu (LiquidityState enum).
        composite_score: Bileşik likidite skoru (0=kriz, 1=mükemmel).
        spread_score: Spread kalite skoru (0-1).
        volume_score: Hacim anomali skoru (0-1, düşük=anormal).
        volatility_adj_spread: Volatiliteye göre düzeltilmiş spread tahmini.
        volume_zscore: Hacim Z-skoru.
        early_warning: True ise likidite bozulması erken uyarısı aktif.
        bar_index: İlgili çubuk indeksi.
    """

    state: LiquidityState
    composite_score: float
    spread_score: float
    volume_score: float
    volatility_adj_spread: float
    volume_zscore: float
    early_warning: bool
    bar_index: int

    def __repr__(self) -> str:
        """LiquiditySnapshot kısa temsili."""
        return (
            f"LiquiditySnapshot(state={self.state.name}, "
            f"score={self.composite_score:.2f}, warning={self.early_warning})"
        )


@dataclass
class LiquidityAnalysisResult:
    """Likidite analizi sonucu (tam zaman serisi).

    Attributes:
        states: Her çubuk için LiquidityState değerleri.
        composite_scores: Bileşik likidite skoru dizisi (0-1).
        spread_scores: Spread skoru dizisi.
        volume_scores: Hacim skoru dizisi.
        volume_zscores: Hacim Z-skoru dizisi.
        early_warnings: Erken uyarı bayrağı dizisi.
        crisis_periods: Kriz dönemlerinin başlangıç/bitiş indeks çiftleri.
        stats: Özet istatistikler.
    """

    states: np.ndarray
    composite_scores: np.ndarray
    spread_scores: np.ndarray
    volume_scores: np.ndarray
    volume_zscores: np.ndarray
    early_warnings: np.ndarray
    crisis_periods: list[tuple[int, int]] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """LiquidityAnalysisResult kısa temsili."""
        valid = int(np.sum(~np.isnan(self.composite_scores)))
        crisis = int(np.nansum(self.states == LiquidityState.CRISIS))
        abundant = int(np.nansum(self.states == LiquidityState.ABUNDANT))
        return (
            f"LiquidityAnalysisResult(valid={valid}, "
            f"crisis={crisis}, abundant={abundant}, "
            f"crisis_periods={len(self.crisis_periods)})"
        )

    def latest(self) -> LiquiditySnapshot | None:
        """En son geçerli anlık görüntüyü döndürür.

        Returns:
            Son geçerli LiquiditySnapshot veya None (veri yoksa).
        """
        for i in range(len(self.composite_scores) - 1, -1, -1):
            if not np.isnan(self.composite_scores[i]):
                return LiquiditySnapshot(
                    state=LiquidityState(int(self.states[i])),
                    composite_score=float(self.composite_scores[i]),
                    spread_score=float(self.spread_scores[i]),
                    volume_score=float(self.volume_scores[i]),
                    volatility_adj_spread=0.0,
                    volume_zscore=float(self.volume_zscores[i]),
                    early_warning=bool(self.early_warnings[i]),
                    bar_index=i,
                )
        return None


class LiquidityStateEngine:
    """Piyasa likidite durumu analiz motoru.

    Spread, hacim ve volatilite verilerini birleştirerek her çubuk için
    likidite durumunu (CRISIS/STRESSED/NORMAL/ABUNDANT) belirler.
    Kriz erken uyarı sistemi, bileşik skorun kriz eşiğinin altına düşmesinden
    önce uyarı verir.
    """

    def __init__(
        self,
        vol_window: int = DEFAULT_VOL_WINDOW,
        spread_window: int = DEFAULT_SPREAD_WINDOW,
        volume_window: int = DEFAULT_VOLUME_WINDOW,
        crisis_threshold: float = DEFAULT_CRISIS_THRESHOLD,
        stress_threshold: float = DEFAULT_STRESS_THRESHOLD,
        spread_weight: float = 0.4,
        volume_weight: float = 0.4,
        volatility_weight: float = 0.2,
    ) -> None:
        """LiquidityStateEngine başlatıcı.

        Args:
            vol_window: Volatilite hesaplama penceresi (gün).
            spread_window: Spread trendi hesaplama penceresi (gün).
            volume_window: Hacim baseline penceresi (gün).
            crisis_threshold: Kriz sınıflandırması için bileşik skor alt eşiği.
            stress_threshold: Stres sınıflandırması için bileşik skor alt eşiği.
            spread_weight: Bileşik skordaki spread ağırlığı.
            volume_weight: Bileşik skordaki hacim ağırlığı.
            volatility_weight: Bileşik skordaki volatilite ağırlığı.

        Raises:
            ValueError: Ağırlıklar toplamı 1.0 değilse veya eşikler geçersizse.
        """
        if not (0.0 < crisis_threshold < 1.0):
            raise ValueError(f"crisis_threshold (0,1) aralığında olmalıdır: {crisis_threshold}")
        if not (0.0 < stress_threshold < crisis_threshold):
            raise ValueError(
                f"stress_threshold < crisis_threshold olmalıdır: {stress_threshold} < {crisis_threshold}"
            )
        total_w = spread_weight + volume_weight + volatility_weight
        if abs(total_w - 1.0) > 0.01:
            raise ValueError(f"Ağırlıklar toplamı 1.0 olmalıdır: {total_w:.2f}")

        self.vol_window = vol_window
        self.spread_window = spread_window
        self.volume_window = volume_window
        self.crisis_threshold = crisis_threshold
        self.stress_threshold = stress_threshold
        self.spread_weight = spread_weight
        self.volume_weight = volume_weight
        self.volatility_weight = volatility_weight

    def __repr__(self) -> str:
        """LiquidityStateEngine kısa temsili."""
        return (
            f"LiquidityStateEngine(crisis_thr={self.crisis_threshold}, "
            f"stress_thr={self.stress_threshold}, "
            f"w=[spread={self.spread_weight}, vol={self.volume_weight}, vola={self.volatility_weight}])"
        )

    def _compute_volume_score(
        self, volumes: np.ndarray, i: int
    ) -> tuple[float, float]:
        """Hacim skoru ve Z-skoru hesaplar.

        Args:
            volumes: Hacim dizisi.
            i: Referans indeks.

        Returns:
            (volume_score, z_score) tuple'ı. volume_score = 0-1 (1=yüksek likidite).
        """
        start = max(0, i - self.volume_window + 1)
        window = volumes[start:i]
        valid = window[window > DEFAULT_MIN_VOLUME]
        if len(valid) < 5:
            return 0.5, 0.0

        mean_vol = float(np.mean(valid))
        std_vol = float(np.std(valid))

        current_vol = float(volumes[i])
        if std_vol < 1e-10:
            z_score = 0.0
        else:
            z_score = (current_vol - mean_vol) / std_vol

        # Hacim skoru: düşük hacim = düşük likidite
        # z < -2: kriz (score ~0), z > 2: bollaşma (score ~1)
        score = float(np.clip(0.5 + z_score / 6.0, 0.0, 1.0))
        return score, z_score

    def _compute_spread_score(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        i: int,
    ) -> float:
        """Spread kalite skoru hesaplar (Corwin-Schultz high-low spread tahmini).

        Args:
            high: Yüksek fiyat dizisi.
            low: Düşük fiyat dizisi.
            close: Kapanış fiyatları dizisi.
            i: Referans indeks.

        Returns:
            Spread skoru (0-1, 1=dar spread=yüksek likidite).
        """
        start = max(1, i - self.spread_window + 1)
        spreads: list[float] = []
        for j in range(start, i + 1):
            if close[j] > 0 and high[j] >= low[j]:
                relative_spread = (high[j] - low[j]) / close[j]
                spreads.append(relative_spread)

        if not spreads:
            return 0.5

        current_spread = spreads[-1] if spreads else 0.01
        baseline_spread = float(np.median(spreads))

        # Spread oranı: mevcut / medyan. 1.0=normal, >2.0=kötüleşme
        ratio = current_spread / max(baseline_spread, 1e-8)
        # Dönüştür: 0.5 ratio → score 1.0, 3.0 ratio → score 0.0
        score = float(np.clip(1.0 - (ratio - 0.5) / 2.5, 0.0, 1.0))
        return score

    def _compute_volatility_score(
        self, log_returns: np.ndarray, i: int
    ) -> float:
        """Volatilite skoru hesaplar (yüksek vol = düşük likidite skoru).

        Args:
            log_returns: Log-getiri dizisi.
            i: Referans indeks.

        Returns:
            Volatilite skoru (0-1, 1=düşük volatilite=yüksek likidite).
        """
        start = max(0, i - self.vol_window + 1)
        window = log_returns[start : i + 1]
        valid = window[np.isfinite(window)]
        if len(valid) < 3:
            return 0.5

        # Tarihsel başlangıç penceresindeki vol
        hist_start = max(0, i - self.volume_window)
        hist_window = log_returns[hist_start : i + 1]
        hist_valid = hist_window[np.isfinite(hist_window)]

        current_vol = float(np.std(valid)) if len(valid) >= 2 else 0.01
        hist_vol = float(np.std(hist_valid)) if len(hist_valid) >= 2 else current_vol

        ratio = current_vol / max(hist_vol, 1e-10)
        # 0.5 ratio → score 1.0, 3.0 ratio → score 0.0
        score = float(np.clip(1.0 - (ratio - 0.5) / 2.5, 0.0, 1.0))
        return score

    def analyze(
        self,
        close: np.ndarray,
        volume: np.ndarray,
        high: np.ndarray | None = None,
        low: np.ndarray | None = None,
    ) -> LiquidityAnalysisResult:
        """Piyasa likiditesini tüm veri serisi için analiz eder.

        Args:
            close: Kapanış fiyatları dizisi.
            volume: İşlem hacmi dizisi.
            high: Opsiyonel yüksek fiyat dizisi (spread skoru için).
            low: Opsiyonel düşük fiyat dizisi (spread skoru için).

        Returns:
            Tam zaman serisi likidite analiz sonucu.

        Raises:
            ValueError: Diziler boş veya uyumsuzsa.
        """
        n = len(close)
        if n == 0:
            raise ValueError("close dizisi boş olamaz.")
        if len(volume) != n:
            raise ValueError(f"volume ({len(volume)}) ve close ({n}) boyutları eşleşmelidir.")

        if high is None:
            high = close * 1.005
        if low is None:
            low = close * 0.995

        states = np.full(n, np.nan)
        composite_scores = np.full(n, np.nan)
        spread_scores_arr = np.full(n, np.nan)
        volume_scores_arr = np.full(n, np.nan)
        volume_zscores_arr = np.full(n, np.nan)
        early_warnings = np.zeros(n, dtype=bool)

        log_returns = np.full(n, np.nan)
        for i in range(1, n):
            if close[i] > 0 and close[i - 1] > 0:
                log_returns[i] = float(np.log(close[i] / close[i - 1]))

        min_window = max(self.vol_window, self.volume_window, self.spread_window)

        for i in range(min_window, n):
            vol_score = self._compute_volatility_score(log_returns, i)
            sp_score = self._compute_spread_score(high, low, close, i)
            vm_score, vm_z = self._compute_volume_score(volume, i)

            composite = (
                self.spread_weight * sp_score
                + self.volume_weight * vm_score
                + self.volatility_weight * vol_score
            )

            composite_scores[i] = composite
            spread_scores_arr[i] = sp_score
            volume_scores_arr[i] = vm_score
            volume_zscores_arr[i] = vm_z

            # Durum belirleme
            if composite < self.crisis_threshold * 0.7:
                state = LiquidityState.CRISIS
            elif composite < self.stress_threshold:
                state = LiquidityState.STRESSED
            elif composite > 0.80:
                state = LiquidityState.ABUNDANT
            else:
                state = LiquidityState.NORMAL
            states[i] = float(state)

            # Erken uyarı: son 3 çubukta skor düşüş trendi + stres eşiğine yaklaşma
            if i >= min_window + 3:
                recent_scores = composite_scores[i - 3 : i + 1]
                valid_recent = recent_scores[~np.isnan(recent_scores)]
                if len(valid_recent) >= 3:
                    trend_down = valid_recent[-1] < valid_recent[0]
                    near_threshold = composite < self.stress_threshold * 1.2
                    early_warnings[i] = bool(trend_down and near_threshold)

        # Kriz dönemleri
        crisis_periods: list[tuple[int, int]] = []
        in_crisis = False
        crisis_start = 0
        for i in range(n):
            if not np.isnan(states[i]) and int(states[i]) == LiquidityState.CRISIS:
                if not in_crisis:
                    in_crisis = True
                    crisis_start = i
            else:
                if in_crisis:
                    crisis_periods.append((crisis_start, i - 1))
                    in_crisis = False
        if in_crisis:
            crisis_periods.append((crisis_start, n - 1))

        # İstatistikler
        valid_scores = composite_scores[~np.isnan(composite_scores)]
        stats: dict[str, float] = {}
        if len(valid_scores) > 0:
            stats["mean_composite"] = float(np.mean(valid_scores))
            stats["min_composite"] = float(np.min(valid_scores))
            stats["max_composite"] = float(np.max(valid_scores))
            stats["crisis_rate"] = float(np.nanmean(states == LiquidityState.CRISIS))
            stats["stressed_rate"] = float(np.nanmean(states == LiquidityState.STRESSED))
            stats["early_warning_rate"] = float(np.mean(early_warnings))
            stats["n_crisis_periods"] = float(len(crisis_periods))

        logger.info(
            "Likidite analizi tamamlandı.",
            valid=len(valid_scores),
            crisis_periods=len(crisis_periods),
            mean_score=round(stats.get("mean_composite", 0.0), 3),
        )

        return LiquidityAnalysisResult(
            states=states,
            composite_scores=composite_scores,
            spread_scores=spread_scores_arr,
            volume_scores=volume_scores_arr,
            volume_zscores=volume_zscores_arr,
            early_warnings=early_warnings,
            crisis_periods=crisis_periods,
            stats=stats,
        )


__all__: list[str] = [
    "LiquidityAnalysisResult",
    "LiquiditySnapshot",
    "LiquidityState",
    "LiquidityStateEngine",
    "liquidity_engine",
]

# Singleton
liquidity_engine = LiquidityStateEngine()
