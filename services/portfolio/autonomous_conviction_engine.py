"""
ALPHA BIST — Autonomous Conviction & Dynamic Profit-Running Engine v1.0

Kuantitatif Otonom Portföy ve Dinamik Pozisyon Yönetimi:
1. Otonom Hisse Seçimi (Dinamik 0 ila 30 Hisse):
   - Sabit hisse sayısı zorlaması YOK.
   - Hurdle Rate (Alfa Barajı) ve İstatistiki Güven Skoru (Confidence) filtresi.
   - Kazanacağına inanıyorsa alır (1-30 hisse), inanmıyorsa %100 nakitte bekler.
2. Güven Skoruna Göre Dinamik Sermaye Dağılımı (Conviction-Weighted Sizing):
   - Güçlü hisseye yüksek sermaye payı (Fractional Kelly + Conviction Power Law).
   - Zayıf hisseye deneme payı / düşük pay.
   - Volatilite ve sektör korelasyon disiplini (düzenli getiri).
3. Kârı Koşturma & Dinamik Çıkış Yönetimi:
   - Kârı devam eden lider hisseleri gün kısıtı olmadan tutma (Let winners run).
   - Dinamik yükselen Trailing Stop (Kâr kilitleme).
   - Gücü biten / sinyali sönen hisseleri anında satma (Conviction Decay Exit).
   - Aşırı şişen hisselerde kısmi kâr alma (Profit Trimming).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import structlog

logger = structlog.get_logger()


class ExitAction(StrEnum):
    """Pozisyon çıkış kararı."""

    HOLD_AND_RUN = "HOLD_AND_RUN"  # Kârı koştur, tutmaya devam et
    FULL_EXIT = "FULL_EXIT"  # Gücü bitti / Trailing stop vuruldu / Tamamen çık
    TRIM_PROFIT = "TRIM_PROFIT"  # Aşırı şişti, kısmi kâr al (%30-%50 sat)
    STOP_LOSS = "STOP_LOSS"  # Zarar kes seviyesi vuruldu


@dataclass
class CandidateAsset:
    """Portföy için aday hisse."""

    ticker: str
    confidence_score: float  # Model güven skoru (0.00 - 1.00)
    expected_return: float  # Beklenen getiri (Yıllık alfa veya vade getirisi, örn 0.15 = %15)
    volatility: float  # Yıllıklandırılmış volatilite (0.25 = %25)
    sector: str = "OTHER"
    momentum_score: float = 50.0  # 0-100
    rsi: float = 50.0
    volume_flow_score: float = 50.0  # Para girişi (0-100)
    current_price: float = 0.0
    horizon_days: int = 20  # İşlem vadesi (gün)
    is_excess_alpha: bool = True  # Model getirisi benchmark üzeri net alfa mı?
    strategy_type: str = "SWING"  # SWING, ALPHA_RUNNER, BREAKOUT


@dataclass
class OpenPositionState:
    """Mevcut açık pozisyon durumu."""

    ticker: str
    entry_price: float
    current_price: float
    highest_price: float  # High Water Mark (Gördüğü en yüksek fiyat)
    entry_date: str
    holding_days: int
    current_confidence: float
    sector: str = "OTHER"
    quantity: int = 0
    trailing_stop_price: float = 0.0
    unrealized_pnl_pct: float = 0.0
    strategy_type: str = "SWING"


@dataclass
class AllocationPlan:
    """Otonom portföy dağılım planı."""

    selected_tickers: list[str]
    weights: dict[str, float]  # ticker -> weight (0.0 - 1.0)
    cash_weight: float
    total_exposure: float
    num_positions: int
    market_regime: str
    hurdle_rate_annual: float
    rejected_tickers: list[str] = field(default_factory=list)
    rejection_reasons: dict[str, str] = field(default_factory=dict)
    rationale: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class ExitDecision:
    """Tek bir hisse için çıkış / tutma kararı."""

    ticker: str
    action: ExitAction
    reason: str
    unrealized_pnl_pct: float
    current_confidence: float
    current_price: float
    trailing_stop_price: float
    suggested_trim_ratio: float = 0.0  # TRIM_PROFIT ise satılacak oran (örn 0.40)


class AutonomousConvictionEngine:
    """Otonom Fırsat, Dinamik Güven ve Kâr Koşturma Motoru."""

    def __init__(
        self,
        base_hurdle_rate: float = 0.35,  # BIST politika faizi / mevduat barajı (%35)
        min_entry_confidence: float = 0.60,  # Minimum giriş güven skoru
        exit_confidence_threshold: float = 0.48,  # Bu skorun altına düşerse SAT
        trailing_stop_pct: float = 0.06,  # Tepeden %6 geri çekilmede kârı kilitle
        max_single_stock_cap: float = 0.25,  # Çok yüksek güvende tek hisse tavanı (%25)
        min_single_stock_cap: float = 0.03,  # Minimum pozisyon eşiği (%3)
        max_sector_cap: float = 0.35,  # Maksimum sektör konsantrasyonu (%35)
        conviction_gamma: float = 2.0,  # Güven skoru üssü (yüksek güvenceye katlanarak pay ver)
    ):
        self.base_hurdle_rate = base_hurdle_rate
        self.min_entry_confidence = min_entry_confidence
        self.exit_confidence_threshold = exit_confidence_threshold
        self.trailing_stop_pct = trailing_stop_pct
        self.max_single_stock_cap = max_single_stock_cap
        self.min_single_stock_cap = min_single_stock_cap
        self.max_sector_cap = max_sector_cap
        self.conviction_gamma = conviction_gamma

        logger.info(
            "AutonomousConvictionEngine initialized",
            hurdle_rate=base_hurdle_rate,
            min_confidence=min_entry_confidence,
            exit_threshold=exit_confidence_threshold,
            trailing_stop=trailing_stop_pct,
            max_stock_cap=max_single_stock_cap,
        )

    def compute_dynamic_hurdle_rate(
        self,
        market_regime: str = "SIDEWAYS",
        macro_risk_free_rate: float | None = None,
        estimated_friction: float = 0.005,  # %0.5 komisyon + kayma
        is_excess_alpha: bool = True,
        horizon_days: int | None = None,
    ) -> float:
        """Piyasa rejimine, alfa hedefine ve vadeye göre dinamik eşik hesaplar.

        - is_excess_alpha=True ise: BIST-100 üzeri excess getiri barajı (documentation/01 %10-%20 hedefi).
        - is_excess_alpha=False ise: Nominal getiri barajı (politika faizi/mevduat + rejim primi + friction).
        - horizon_days belirtilmişse yıllık oran tutma vadesine indirgenir.
        """
        if is_excess_alpha:
            # BIST-100 üzeri Excess Alpha Hedefi (documentation/01 §1.7.2: %10-20 yıllık alfa)
            regime_alpha_hurdle = {
                "BULL": 0.08,      # Boğada %8 yıllık alfa yeterli
                "SIDEWAYS": 0.12,  # Yatayda %12 yıllık alfa
                "BEAR": 0.18,      # Ayıda %18 yıllık alfa
                "CRISIS": 0.25,    # Krizde %25 yıllık alfa
                "HIGH_VOL": 0.15,
            }.get(market_regime.upper(), 0.12)
            base_annual = regime_alpha_hurdle + estimated_friction
        else:
            rf = macro_risk_free_rate if macro_risk_free_rate is not None else self.base_hurdle_rate
            regime_premium = {
                "BULL": 0.05,  # Boğada fırsat maliyeti düşük, iştah yüksek
                "SIDEWAYS": 0.10,  # Yatayda seçici ol
                "BEAR": 0.25,  # Ayıda hisseye girmek için çok ciddi getiri vaadi lazım
                "CRISIS": 0.40,  # Krizde hisse almak için devasa iskontolu getiri şart
                "HIGH_VOL": 0.20,
            }.get(market_regime.upper(), 0.10)
            base_annual = rf + regime_premium + estimated_friction

        if horizon_days is not None and 0 < horizon_days < 252:
            horizon_hurdle = ((1.0 + base_annual) ** (horizon_days / 252.0)) - 1.0
            return round(float(horizon_hurdle), 4)

        return round(float(base_annual), 4)

    def evaluate_universe(
        self,
        candidates: list[CandidateAsset],
        market_regime: str = "SIDEWAYS",
        macro_risk_free_rate: float | None = None,
    ) -> tuple[list[CandidateAsset], dict[str, str]]:
        """Evrendeki hisseleri otonom süzer. Kazanacağına inanmadığını eler."""
        accepted: list[CandidateAsset] = []
        rejections: dict[str, str] = {}

        for c in candidates:
            # 1. Güven Skoru Denetimi
            if c.confidence_score < self.min_entry_confidence:
                rejections[c.ticker] = (
                    f"Yetersiz Güven Skoru ({c.confidence_score:.2f} < {self.min_entry_confidence:.2f})"
                )
                continue

            # 2. Beklenen Getiri vs Hurdle Rate
            # Adayın getiri ölçeğine göre (vade bazlı < %30 veya yıllıklandırılmış) dinamik hurdle uygula
            hurdle_rate = self.compute_dynamic_hurdle_rate(
                market_regime=market_regime,
                macro_risk_free_rate=macro_risk_free_rate,
                is_excess_alpha=c.is_excess_alpha,
                horizon_days=c.horizon_days if c.expected_return < 0.30 else None,
            )
            if c.expected_return <= hurdle_rate:
                rejections[c.ticker] = (
                    f"Getiri Alfa Barajını Geçemedi ({c.expected_return:.1%} <= {hurdle_rate:.1%})"
                )
                continue

            # 3. Aşırı Düşüş / Bıçak Tutma Riski
            if c.rsi < 20.0 and c.volume_flow_score < 25.0:
                rejections[c.ticker] = "Düşen Bıçak Riski (RSI < 20 ve Para Çıkışı Devam Ediyor)"
                continue

            accepted.append(c)

        logger.info(
            "Universe evaluated autonomously",
            total_candidates=len(candidates),
            accepted_count=len(accepted),
            rejected_count=len(rejections),
            regime=market_regime,
        )
        return accepted, rejections

    def allocate_conviction_portfolio(
        self,
        candidates: list[CandidateAsset],
        market_regime: str = "SIDEWAYS",
        macro_risk_free_rate: float | None = None,
    ) -> AllocationPlan:
        """Kabul edilen hisselere güven skoruna ve risk disiplinine göre otonom ağırlık dağıtır."""
        accepted, rejections = self.evaluate_universe(candidates, market_regime, macro_risk_free_rate)
        hurdle_rate = self.compute_dynamic_hurdle_rate(market_regime, macro_risk_free_rate)

        # Durum 0: Hiçbir hisse güven barajını geçemedi -> %100 Nakitte Bekle
        if not accepted:
            logger.info("No candidates passed the hurdle rate — remaining 100% in CASH")
            return AllocationPlan(
                selected_tickers=[],
                weights={},
                cash_weight=1.0,
                total_exposure=0.0,
                num_positions=0,
                market_regime=market_regime,
                hurdle_rate_annual=hurdle_rate,
                rejected_tickers=list(rejections.keys()),
                rejection_reasons=rejections,
                rationale="Piyasada pozitif alfa üretecek güvenli hisse bulunamadı, portföy nakitte korunuyor.",
            )

        # 1. Portföy Odaklanması (Maksimum 15 hisse): En yüksek model güvenine sahip adayları filtrele
        best_candidates = sorted(
            accepted,
            key=lambda x: x.confidence_score,
            reverse=True,
        )[:15]

        # 2. Ham Güven Ağırlıkları (Conviction Power Law + Inverse Volatility)
        # RawWeight = (Confidence^gamma) / (Volatility^2)
        raw_weights: dict[str, float] = {}
        for c in best_candidates:
            vol = max(c.volatility, 0.10)  # Aşırı düşük volatiliteye sıfıra bölme koruması
            conviction_term = c.confidence_score**self.conviction_gamma
            risk_term = 1.0 / (vol**2)
            raw_weights[c.ticker] = conviction_term * risk_term

        total_raw = sum(raw_weights.values())
        if total_raw <= 0:
            total_raw = 1.0

        normalized_weights = {t: w / total_raw for t, w in raw_weights.items()}

        # 3. Rejime Göre Maksimum Toplam Maruziyet (Exposure)
        max_regime_exposure = {
            "BULL": 0.98,  # Boğada neredeyse full hisse (%2 nakit)
            "SIDEWAYS": 0.80,  # Yatayda %20 nakit tamponu
            "BEAR": 0.45,  # Ayıda max %45 hisse, %55 nakit
            "CRISIS": 0.20,  # Krizde max %20 hisse, %80 nakit
            "HIGH_VOL": 0.50,
        }.get(market_regime.upper(), 0.80)

        # 4. Kısıtların Uygulanması (Tek hisse tavanı ve sektör tavanı)
        # Güven skoru 0.90+ olan hisseye %25'e kadar izin ver, düşük olana %8 tavan koy
        final_weights: dict[str, float] = {}
        sector_totals: dict[str, float] = {}

        # Güven skoruna göre sırala (en güçlüler önce limit alsın)
        sorted_candidates = sorted(best_candidates, key=lambda x: x.confidence_score, reverse=True)

        for c in sorted_candidates:
            target_w = normalized_weights[c.ticker] * max_regime_exposure

            # Dinamik Tek Hisse Tavanı: Güven skoruna göre %10 ile %25 arası esner
            dynamic_stock_cap = self.min_single_stock_cap + (
                self.max_single_stock_cap - self.min_single_stock_cap
            ) * (c.confidence_score**1.5)

            w = min(target_w, dynamic_stock_cap)

            # Sektör Konsantrasyon Tavanı
            current_sec_w = sector_totals.get(c.sector, 0.0)
            if current_sec_w + w > self.max_sector_cap:
                w = max(0.0, self.max_sector_cap - current_sec_w)

            # Toz Pozisyon Kontrolü
            if w >= self.min_single_stock_cap:
                final_weights[c.ticker] = round(w, 4)
                sector_totals[c.sector] = current_sec_w + w
            else:
                rejections[c.ticker] = f"Sektör/Tekil kısıt sonrası pozisyon toza dönüştü ({w:.1%})"

        # Ağırlıkları ölçekle
        total_allocated = sum(final_weights.values())
        if total_allocated > max_regime_exposure:
            scale = max_regime_exposure / total_allocated
            final_weights = {t: round(w * scale, 4) for t, w in final_weights.items()}
            total_allocated = sum(final_weights.values())

        cash_weight = round(1.0 - total_allocated, 4)

        return AllocationPlan(
            selected_tickers=list(final_weights.keys()),
            weights=final_weights,
            cash_weight=cash_weight,
            total_exposure=round(total_allocated, 4),
            num_positions=len(final_weights),
            market_regime=market_regime,
            hurdle_rate_annual=hurdle_rate,
            rejected_tickers=list(rejections.keys()),
            rejection_reasons=rejections,
            rationale=f"Rejim: {market_regime} | {len(final_weights)} hisse seçildi | Toplam Maruziyet: %{total_allocated*100:.1f} | Nakit: %{cash_weight*100:.1f}",
        )

    def evaluate_position_exits(
        self,
        positions: list[OpenPositionState],
        current_scores: dict[str, float],  # ticker -> new confidence score
        current_prices: dict[str, float],  # ticker -> current price
        trailing_stop_pct: float | None = None,
    ) -> list[ExitDecision]:
        """Açık pozisyonları kâr koşturma ve güç kaybına göre değerlendirir.

        Prensipler:
        1. Kârı Koştur (Let Winners Run): Model güveni yüksekse ve trailing stop vurulmamışsa TUT.
        2. Kârı Kilitle (Trailing Stop): Fiyat yükseldikçe stop seviyesini yukarı taşı.
        3. Güç Kaybında Çık (Conviction Decay): Güven skoru eşiğin altına düşerse SAT.
        4. Kısmi Kâr Al (Trim): Aşırı parabolik yükselişte (%35+ kâr) kısmi realize et.
        """
        ts_pct = trailing_stop_pct or self.trailing_stop_pct
        decisions: list[ExitDecision] = []

        for pos in positions:
            ticker = pos.ticker
            curr_p = current_prices.get(ticker, pos.current_price)
            curr_conf = current_scores.get(ticker, pos.current_confidence)

            # High water mark güncelle
            new_hwm = max(pos.highest_price, curr_p)

            # Dinamik Yükselen Trailing Stop Fiyatı
            new_ts_price = round(new_hwm * (1.0 - ts_pct), 2)
            active_ts_price = max(pos.trailing_stop_price, new_ts_price)

            # Anlık Kâr / Zarar %
            pnl_pct = (curr_p - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0.0

            # 1. Karar: Trailing Stop Seviyesi Vuruldu mu? (Kâr Kilitleme / Koruma)
            # Trailing stop mantığı: Fiyat daha önce kâr bölgesine girmişse (new_hwm >= entry * 1.02)
            # veya trailing stop maliyetin üstüne taşınmışsa, fiyat active_ts_price'ın altına düştüğü an
            # çıkış yapılır. "pnl_pct > 0.02" tuzak şartı kaldırılarak ölüm bölgesi kapatılmıştır.
            has_reached_profit = (new_hwm >= pos.entry_price * 1.02) or (active_ts_price >= pos.entry_price)
            if curr_p <= active_ts_price and has_reached_profit:
                decisions.append(
                    ExitDecision(
                        ticker=ticker,
                        action=ExitAction.FULL_EXIT,
                        reason=f"Trailing Stop Vuruldu (Zirveden %{ts_pct*100:.1f} çekilme, Stop: ₺{active_ts_price:.2f}, Kâr/Zarar: %{pnl_pct*100:.1f})",
                        unrealized_pnl_pct=round(pnl_pct, 4),
                        current_confidence=curr_conf,
                        current_price=curr_p,
                        trailing_stop_price=active_ts_price,
                    )
                )
                continue

            # 2. Karar: Sert Zarar Kes (Stop-Loss — standart hisse için -%7)
            sl_threshold = -0.07
            if pnl_pct <= sl_threshold:
                decisions.append(
                    ExitDecision(
                        ticker=ticker,
                        action=ExitAction.STOP_LOSS,
                        reason=f"Katı Zarar Kes Tetiklendi (Zarar: %{pnl_pct*100:.1f}, Eşik: %{sl_threshold*100:.1f})",
                        unrealized_pnl_pct=round(pnl_pct, 4),
                        current_confidence=curr_conf,
                        current_price=curr_p,
                        trailing_stop_price=active_ts_price,
                    )
                )
                continue

            # 3. Karar: Güç / Güven Kaybı (Conviction Decay — Kârı Bitti)
            if curr_conf < self.exit_confidence_threshold:
                decisions.append(
                    ExitDecision(
                        ticker=ticker,
                        action=ExitAction.FULL_EXIT,
                        reason=f"Model Güveni Çöktü ({curr_conf:.2f} < {self.exit_confidence_threshold:.2f}, Kâr/Zarar: %{pnl_pct*100:.1f})",
                        unrealized_pnl_pct=round(pnl_pct, 4),
                        current_confidence=curr_conf,
                        current_price=curr_p,
                        trailing_stop_price=active_ts_price,
                    )
                )
                continue

            # 4. Karar: Parabolik Kâr Alma (Trim Profit — %35+ kâr ve aşırı primlenme)
            if pnl_pct >= 0.35 and curr_conf < 0.75:
                decisions.append(
                    ExitDecision(
                        ticker=ticker,
                        action=ExitAction.TRIM_PROFIT,
                        reason=f"Parabolik Yükseliş: Kısmi Kâr Realizasyonu (Kâr: %{pnl_pct*100:.1f}, %40 Sat, Kalanı Sür)",
                        unrealized_pnl_pct=round(pnl_pct, 4),
                        current_confidence=curr_conf,
                        current_price=curr_p,
                        trailing_stop_price=active_ts_price,
                        suggested_trim_ratio=0.40,
                    )
                )
                continue

            # 5. Karar: Kârı Koştur! (Let Winners Run)
            decisions.append(
                ExitDecision(
                    ticker=ticker,
                    action=ExitAction.HOLD_AND_RUN,
                    reason=f"Güçlü Trend ve Yüksek Güven Devam Ediyor (Güven: {curr_conf:.2f}, Kâr: %{pnl_pct*100:.1f}, TS: {active_ts_price:.2f} TL)",
                    unrealized_pnl_pct=round(pnl_pct, 4),
                    current_confidence=curr_conf,
                    current_price=curr_p,
                    trailing_stop_price=active_ts_price,
                )
            )

        return decisions


# Singleton export
autonomous_conviction_engine = AutonomousConvictionEngine()
