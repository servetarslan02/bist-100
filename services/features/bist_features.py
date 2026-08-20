"""
ALPHA BIST — BIST'e Özgü Feature Engine v1.0

BIST piyasasına özgü feature'lar:
- Kur hassasiyeti (USDTRY beta, FX impact)
- Enflasyon hassasiyeti (CPI sensitivity, real return)
- Faiz hassasiyeti (rate sensitivity, debt cost)
- Sektör momentum (sector relative strength)
- KAP etkisi (event frequency, sentiment trend)
- Yabancı yatırımcı (foreign ownership, flow direction)
- BIST-specific pattern'lar (açığa satış yasağı, fiyat limitleri)
- Likidite profili (spread, depth, market cap)
- Temettü dinamikleri (yield, payout, ex-date effect)
- Endeks ağırlığı (BIST100 weight, sector weight)

Kaynaklar:
- DergiPark: Forecasting BIST100 with Macro Indicators (2025)
- arXiv: Risk-Aware Financial Forecasting (2025)
- Springer: Financial Contagion Detection (2026)
- ScienceDirect: Foreign Portfolio Flows & Monetary Policy (2021)

FAZ 4: BIST-Specific Features
"""

import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


# =====================================================
# Data Classes
# =====================================================

@dataclass
class BISTFeatureSet:
    """BIST'e özgü feature set'i."""
    ticker: str
    timestamp: str

    # Kur hassasiyeti
    fx_beta: float = 0.0               # USDTRY'ye duyarlılık (beta)
    fx_revenue_impact: float = 0.0     # Döviz gelirlerinin payı
    fx_debt_impact: float = 0.0        # Döviz borcunun payı
    fx_net_exposure: float = 0.0       # Net döviz pozisyonu

    # Enflasyon hassasiyeti
    inflation_sensitivity: float = 0.0  # Enflasyona duyarlılık
    real_return_adj: float = 0.0       # Reel getiri düzeltmesi
    pricing_power: float = 0.0         # Fiyatlandırma gücü (0-1)

    # Faiz hassasiyeti
    rate_sensitivity: float = 0.0      # Faize duyarlılık
    debt_cost_impact: float = 0.0      # Borç maliyeti etkisi
    duration_exposure: float = 0.0     # Vade riski

    # Sektör dinamikleri
    sector_momentum_20d: float = 0.0   # Sektör 20 günlük momentum
    sector_relative_strength: float = 0.0  # Sektöre göre güç
    sector_rank: int = 0               # Sektör içi sıralama
    sector_beta: float = 0.0           # Sektöre beta

    # KAP etkisi
    kap_event_count_30d: int = 0       # Son 30 gün KAP olay sayısı
    kap_sentiment_trend: float = 0.0   # KAP sentiment trendi
    kap_financial_event_count: int = 0 # Finansal olay sayısı
    kap_dividend_event: bool = False   # Temettü olayı var mı

    # Yabancı yatırımcı
    foreign_ownership_pct: float = 0.0 # Yabancı sahiplik %
    foreign_flow_direction: float = 0.0 # Yabancı akış yönü (-1 ile +1)
    foreign_flow_momentum: float = 0.0 # Yabancı akış momentumu

    # Likidite
    avg_daily_volume: float = 0.0      # Ortalama günlük hacim
    volume_to_mcap: float = 0.0        # Hacim/şirket değeri
    bid_ask_spread_avg: float = 0.0    # Ortalama spread
    free_float_pct: float = 0.0        # Dolaşımdaki pay %

    # Temettü
    dividend_yield: float = 0.0        # Temettü verimi
    dividend_payout_ratio: float = 0.0 # Temettü ödeme oranı
    days_since_ex_date: int = 0        # Son temettü tarihinden gün
    dividend_growth_3y: float = 0.0    # 3 yıllık temettü büyümesi

    # Endeks
    bist100_weight: float = 0.0        # BIST100'deki ağırlık %
    bist30_member: bool = False        # BIST30 üyesi mi
    bist50_member: bool = False        # BIST50 üyesi mi

    # BIST pattern'ları
    circuit_breaker_active: bool = False  # Devre kesici tetiklendi mi
    price_limit_hit: bool = False         # Fiyat limiti vuruldu mu
    short_selling_allowed: bool = True    # Açığa satış serbest mi
    trade_suspension_days: int = 0        # İşlem durdurma gün sayısı

    # Kalite skorları
    piotroski_f: int = 0               # Piotroski F-Score (0-9)
    beneish_m: float = 0.0             # Beneish M-Score
    altman_z: float = 0.0              # Altman Z-Score

    def to_dict(self) -> Dict[str, Any]:
        """Dict'e çevir."""
        return {k: v for k, v in self.__dict__.items()}

    def to_feature_dict(self) -> Dict[str, float]:
        """Sadece sayısal feature'ları dict olarak döndür (model input için)."""
        result = {}
        for k, v in self.__dict__.items():
            if k in ('ticker', 'timestamp'):
                continue
            if isinstance(v, bool):
                result[f"bist_{k}"] = 1.0 if v else 0.0
            elif isinstance(v, (int, float)):
                result[f"bist_{k}"] = float(v)
        return result


# =====================================================
# BIST Feature Engine
# =====================================================

class BISTFeatureEngine:
    """BIST'e özgü feature hesaplama motoru.

    Kullanım:
        engine = BISTFeatureEngine()
        features = engine.compute_all(
            ticker="THYAO",
            price_history=prices,
            macro_data=macro,
            kap_events=kap_events,
            foreign_data=foreign,
        )
    """

    def __init__(self):
        # Sektör mapping (BIST'teki ana sektörler)
        self._sector_map = {
            "THYAO": "HAVACILIK", "ASELS": "SAVUNMA", "TUPRS": "ENERJI",
            "EREGL": "DEMIR_CELIK", "KCHMLAC": "KIMYA", "SAHOL": "HOLDING",
            "KONTR": "OTOMOTIV", "GARAN": "BANKACILIK", "AKBNK": "BANKACILIK",
            "ISCTR": "BANKACILIK", "HALKB": "BANKACILIK", "VAKBN": "BANKACILIK",
            "YKBNK": "BANKACILIK", "SISE": "CAM", "KOZAL": "MADENCILIK",
            "TCELL": "TELEKOM", "TTKOM": "TELEKOM", "BIMAS": "PERAKENDE",
            "MGROS": "PERAKENDE", "ULKER": "GIDA", "TATGD": "GIDA",
            "PGSUS": "HAVACILIK", "TOASO": "OTOMOTIV", "FROTO": "OTOMOTIV",
            "ARCLK": "DAYANIKLI", "VESTEL": "DAYANIKLI", "AEFES": "ICECEK",
            "ENKAI": "INSAAT", "EKGYO": "GAYRIMENKUL",
        }

        # Sektör-USDTRY korelasyonu (yaklaşık)
        self._fx_sector_sensitivity = {
            "BANKACILIK": 0.8,     # Yüksek: döviz borçları
            "ENERJI": 0.9,         # Yüksek: ithal enerji
            "HAVACILIK": 0.7,      # Yüksek: döviz gelir+borç
            "OTOMOTIV": 0.6,       # Orta: ihracat + ithalat
            "DEMIR_CELIK": 0.5,    # Orta: ihracat odaklı
            "HOLDING": 0.4,        # Düşük-orta: çeşitlendirilmiş
            "TELEKOM": 0.3,        # Düşük: TL gelirler
            "PERAKENDE": 0.2,      # Düşük: iç talep
            "GIDA": 0.2,           # Düşük: iç talep
            "INSAAT": 0.5,         # Orta: döviz borçları
            "GAYRIMENKUL": 0.4,    # Orta: döviz borçları
        }

    def compute_all(
        self,
        ticker: str,
        price_history: Optional[List[float]] = None,
        volume_history: Optional[List[float]] = None,
        macro_data: Optional[Dict[str, Any]] = None,
        kap_events: Optional[List[Dict]] = None,
        foreign_data: Optional[Dict[str, Any]] = None,
        fundamentals: Optional[Dict[str, Any]] = None,
        sector_data: Optional[Dict[str, Any]] = None,
        index_data: Optional[Dict[str, Any]] = None,
    ) -> BISTFeatureSet:
        """Tüm BIST feature'larını hesapla.

        Args:
            ticker: Hisse kodu
            price_history: Günlük kapanış fiyatları (son 252 gün)
            volume_history: Günlük hacimler
            macro_data: Makro veriler (USDTRY, enflasyon, faiz, vb.)
            kap_events: KAP olayları listesi
            foreign_data: Yabancı yatırımcı verileri
            fundamentals: Finansal veriler (bilanço, gelir tablosu)
            sector_data: Sektör verileri
            index_data: Endeks verileri (BIST100, BIST30)

        Returns:
            BISTFeatureSet
        """
        now = datetime.now(timezone.utc).isoformat()
        features = BISTFeatureSet(ticker=ticker, timestamp=now)

        sector = self._sector_map.get(ticker, "DIGER")

        # 1. Kur hassasiyeti
        self._compute_fx_features(features, ticker, sector, price_history, macro_data, fundamentals)

        # 2. Enflasyon hassasiyeti
        self._compute_inflation_features(features, sector, macro_data, fundamentals)

        # 3. Faiz hassasiyeti
        self._compute_rate_features(features, sector, macro_data, fundamentals)

        # 4. Sektör dinamikleri
        self._compute_sector_features(features, ticker, sector, price_history, sector_data)

        # 5. KAP etkisi
        self._compute_kap_features(features, kap_events)

        # 6. Yabancı yatırımcı
        self._compute_foreign_features(features, foreign_data)

        # 7. Likidite profili
        self._compute_liquidity_features(features, price_history, volume_history, fundamentals)

        # 8. Temettü dinamikleri
        self._compute_dividend_features(features, fundamentals, kap_events)

        # 9. Endeks ağırlığı
        self._compute_index_features(features, ticker, index_data)

        # 10. BIST pattern'ları
        self._compute_pattern_features(features, price_history, kap_events)

        # 11. Kalite skorları
        self._compute_quality_scores(features, fundamentals)

        return features

    # =====================================================
    # 1. KUR HASSASIYETİ
    # =====================================================

    def _compute_fx_features(
        self, features: BISTFeatureSet, ticker: str, sector: str,
        prices: Optional[List[float]], macro: Optional[Dict],
        fundamentals: Optional[Dict],
    ):
        """Döviz kuru hassasiyeti feature'ları."""
        # Sektörel FX hassasiyeti
        features.fx_beta = self._fx_sector_sensitivity.get(sector, 0.3)

        # Fundamental'dan FX etkisi
        if fundamentals:
            features.fx_revenue_impact = fundamentals.get("fx_revenue_pct", 0.0)
            features.fx_debt_impact = fundamentals.get("fx_debt_pct", 0.0)
            features.fx_net_exposure = (
                features.fx_revenue_impact - features.fx_debt_impact
            )

        # Fiyat-USDTRY korelasyonu (tarihsel)
        if prices and macro and macro.get("usdtry_history"):
            usdtry = macro["usdtry_history"]
            if len(prices) >= 20 and len(usdtry) >= 20:
                # Son 20 günlük korelasyon
                p_ret = self._returns(prices[-20:])
                f_ret = self._returns(usdtry[-20:])
                if len(p_ret) == len(f_ret) and len(p_ret) > 5:
                    corr = self._correlation(p_ret, f_ret)
                    features.fx_beta = round(corr, 4)

    # =====================================================
    # 2. ENFLASYON HASSASIYETİ
    # =====================================================

    def _compute_inflation_features(
        self, features: BISTFeatureSet, sector: str,
        macro: Optional[Dict], fundamentals: Optional[Dict],
    ):
        """Enflasyon hassasiyeti feature'ları."""
        if not macro:
            return

        cpi = macro.get("cpi_yoy", 0)
        ppi = macro.get("ppi_yoy", 0)

        # Sektörel enflasyon hassasiyeti
        inflation_sensitive_sectors = {
            "GIDA": 0.7, "PERAKENDE": 0.5, "DAYANIKLI": 0.4,
            "BANKACILIK": 0.3, "ENERJI": 0.6,
        }
        features.inflation_sensitivity = inflation_sensitive_sectors.get(sector, 0.3)

        # Reel getiri düzeltmesi
        if cpi > 0 and fundamentals:
            nominal_return = fundamentals.get("roe", 0)
            features.real_return_adj = nominal_return - cpi

        # Fiyatlandırma gücü
        if fundamentals:
            gross_margin = fundamentals.get("gross_margin", 0)
            # Yüksek marj = güçlü fiyatlandırma gücü
            features.pricing_power = min(gross_margin / 50.0, 1.0) if gross_margin > 0 else 0.0

    # =====================================================
    # 3. FAİZ HASSASIYETİ
    # =====================================================

    def _compute_rate_features(
        self, features: BISTFeatureSet, sector: str,
        macro: Optional[Dict], fundamentals: Optional[Dict],
    ):
        """Faiz hassasiyeti feature'ları."""
        if not macro:
            return

        policy_rate = macro.get("policy_rate", 0)

        # Sektörel faiz hassasiyeti
        rate_sensitive_sectors = {
            "BANKACILIK": 0.9, "GAYRIMENKUL": 0.8, "INSAAT": 0.7,
            "OTOMOTIV": 0.5, "DAYANIKLI": 0.4,
        }
        features.rate_sensitivity = rate_sensitive_sectors.get(sector, 0.3)

        # Borç maliyeti etkisi
        if fundamentals:
            debt_equity = fundamentals.get("debt_equity", 0)
            interest_coverage = fundamentals.get("interest_coverage", 10)
            # Yüksek borç + düşük coverage = yüksek hassasiyet
            if interest_coverage > 0:
                features.debt_cost_impact = min(debt_equity / max(interest_coverage, 1), 1.0)

    # =====================================================
    # 4. SEKTÖR DİNAMİKLERİ
    # =====================================================

    def _compute_sector_features(
        self, features: BISTFeatureSet, ticker: str, sector: str,
        prices: Optional[List[float]], sector_data: Optional[Dict],
    ):
        """Sektör dinamikleri feature'ları."""
        if not sector_data:
            return

        sector_returns = sector_data.get("sector_returns", {})
        sector_momentum = sector_data.get("sector_momentum", {})

        # Sektör momentum
        features.sector_momentum_20d = sector_momentum.get(sector, 0.0)

        # Sektöre göre göreli güç
        if prices and len(prices) >= 20:
            stock_return = (prices[-1] / prices[-20] - 1) * 100 if prices[-20] != 0 else 0
            sector_ret = sector_returns.get(sector, 0)
            features.sector_relative_strength = stock_return - sector_ret

        # Sektör içi sıralama
        sector_stocks = sector_data.get("sector_stocks", {}).get(sector, [])
        sector_returns_map = sector_data.get("sector_stock_returns", {}).get(sector, {})
        if sector_returns_map and prices and len(prices) >= 20:
            stock_return = (prices[-1] / prices[-20] - 1) * 100 if prices[-20] != 0 else 0
            # Tüm sektör hisselerinin getirilerine göre sırala
            all_returns = list(sector_returns_map.values()) + [stock_return]
            all_returns_sorted = sorted(all_returns, reverse=True)
            features.sector_rank = all_returns_sorted.index(stock_return) + 1
        elif sector_stocks:
            features.sector_rank = 1  # Sadece tek hisse varsa rank=1

    # =====================================================
    # 5. KAP ETKİSİ
    # =====================================================

    def _compute_kap_features(
        self, features: BISTFeatureSet,
        kap_events: Optional[List[Dict]],
    ):
        """KAP olay feature'ları."""
        if not kap_events:
            return

        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)

        # Son 30 gün olay sayısı
        recent_events = [
            e for e in kap_events
            if self._parse_date(e.get("date", "")) > thirty_days_ago
        ]
        features.kap_event_count_30d = len(recent_events)

        # Finansal olaylar
        financial_types = {"FINANCIAL_STATEMENT", "BALANCE_SHEET", "INCOME_STATEMENT"}
        features.kap_financial_event_count = sum(
            1 for e in recent_events if e.get("type") in financial_types
        )

        # Temettü olayı
        dividend_types = {"DIVIDEND", "CASH_DIVIDEND", "STOCK_DIVIDEND"}
        features.kap_dividend_event = any(
            e.get("type") in dividend_types for e in recent_events
        )

        # Sentiment trend (basit: pozitif/negatif olay oranı)
        positive_events = sum(1 for e in recent_events if e.get("sentiment", 0) > 0)
        negative_events = sum(1 for e in recent_events if e.get("sentiment", 0) < 0)
        total_sentiment = positive_events + negative_events
        if total_sentiment > 0:
            features.kap_sentiment_trend = (positive_events - negative_events) / total_sentiment

    # =====================================================
    # 6. YABANCI YATIRIMCI
    # =====================================================

    def _compute_foreign_features(
        self, features: BISTFeatureSet,
        foreign_data: Optional[Dict],
    ):
        """Yabancı yatırımcı feature'ları."""
        if not foreign_data:
            return

        features.foreign_ownership_pct = foreign_data.get("ownership_pct", 0.0)
        features.foreign_flow_direction = foreign_data.get("flow_direction", 0.0)
        features.foreign_flow_momentum = foreign_data.get("flow_momentum", 0.0)

    # =====================================================
    # 7. LİKİDİTE
    # =====================================================

    def _compute_liquidity_features(
        self, features: BISTFeatureSet,
        prices: Optional[List[float]],
        volumes: Optional[List[float]],
        fundamentals: Optional[Dict],
    ):
        """Likidite profili feature'ları."""
        if volumes and len(volumes) >= 20:
            features.avg_daily_volume = sum(volumes[-20:]) / 20

        if fundamentals:
            mcap = fundamentals.get("market_cap", 0)
            if mcap > 0 and features.avg_daily_volume > 0:
                # Hacim/şirket değeri oranı
                avg_price = prices[-1] if prices else 1
                daily_turnover = features.avg_daily_volume * avg_price
                features.volume_to_mcap = daily_turnover / mcap

            features.free_float_pct = fundamentals.get("free_float_pct", 0.0)
            features.bid_ask_spread_avg = fundamentals.get("avg_spread_pct", 0.0)

    # =====================================================
    # 8. TEMETTÜ
    # =====================================================

    def _compute_dividend_features(
        self, features: BISTFeatureSet,
        fundamentals: Optional[Dict],
        kap_events: Optional[List[Dict]],
    ):
        """Temettü dinamikleri feature'ları."""
        if fundamentals:
            features.dividend_yield = fundamentals.get("dividend_yield", 0.0)
            features.dividend_payout_ratio = fundamentals.get("payout_ratio", 0.0)
            features.dividend_growth_3y = fundamentals.get("dividend_growth_3y", 0.0)

        # Son temettü tarihinden gün
        if kap_events:
            dividend_events = [
                e for e in kap_events
                if e.get("type") in {"DIVIDEND", "CASH_DIVIDEND"}
            ]
            if dividend_events:
                latest = max(dividend_events, key=lambda e: e.get("date", ""))
                event_date = self._parse_date(latest.get("date", ""))
                if event_date:
                    features.days_since_ex_date = (datetime.now(timezone.utc) - event_date).days

    # =====================================================
    # 9. ENDEKS
    # =====================================================

    def _compute_index_features(
        self, features: BISTFeatureSet, ticker: str,
        index_data: Optional[Dict],
    ):
        """Endeks ağırlığı feature'ları."""
        if not index_data:
            return

        bist100_weights = index_data.get("bist100_weights", {})
        features.bist100_weight = bist100_weights.get(ticker, 0.0)

        bist30 = set(index_data.get("bist30", []))
        bist50 = set(index_data.get("bist50", []))
        features.bist30_member = ticker in bist30
        features.bist50_member = ticker in bist50

    # =====================================================
    # 10. BIST PATTERN'LARI
    # =====================================================

    def _compute_pattern_features(
        self, features: BISTFeatureSet,
        prices: Optional[List[float]],
        kap_events: Optional[List[Dict]],
    ):
        """BIST'e özgü pattern feature'ları."""
        if not prices or len(prices) < 5:
            return

        # Fiyat limiti kontrolü (BIST'te %10 günlük limit)
        daily_return = abs(prices[-1] / prices[-2] - 1) * 100 if prices[-2] != 0 else 0
        features.price_limit_hit = daily_return >= 9.5  # %10 limit'e yakın

        # Devre kesici (genellikle %5 ve %7 düşüşlerde)
        if len(prices) >= 2:
            drop = (prices[-1] / prices[-2] - 1) * 100
            features.circuit_breaker_active = drop <= -5.0

        # İşlem durdurma (KAP açıklaması sonrası)
        if kap_events:
            recent_suspensions = [
                e for e in kap_events
                if e.get("type") == "TRADE_SUSPENSION"
                and self._parse_date(e.get("date", "")) > datetime.now(timezone.utc) - timedelta(days=5)
            ]
            features.trade_suspension_days = len(recent_suspensions)

    # =====================================================
    # 11. KALİTE SKORLARI
    # =====================================================

    def _compute_quality_scores(
        self, features: BISTFeatureSet,
        fundamentals: Optional[Dict],
    ):
        """Finansal kalite skorları."""
        if not fundamentals:
            return

        # Piotroski F-Score (0-9)
        f_score = 0
        if fundamentals.get("net_income", 0) > 0: f_score += 1
        if fundamentals.get("roa", 0) > 0: f_score += 1
        if fundamentals.get("operating_cf", 0) > 0: f_score += 1
        if fundamentals.get("operating_cf", 0) > fundamentals.get("net_income", 0): f_score += 1
        if fundamentals.get("debt_ratio_improved", False): f_score += 1
        if fundamentals.get("current_ratio_improved", False): f_score += 1
        if fundamentals.get("gross_margin_improved", False): f_score += 1
        if fundamentals.get("asset_turnover_improved", False): f_score += 1
        if fundamentals.get("shares_outstanding_decreased", False): f_score += 1
        features.piotroski_f = f_score

        # Altman Z-Score
        total_assets = fundamentals.get("total_assets", 1)
        if total_assets > 0:
            wc_ta = fundamentals.get("working_capital", 0) / total_assets
            re_ta = fundamentals.get("retained_earnings", 0) / total_assets
            ebit_ta = fundamentals.get("ebit", 0) / total_assets
            mcap_tl = fundamentals.get("market_cap", 0)
            total_liabilities = fundamentals.get("total_liabilities", 1)
            sales_ta = fundamentals.get("revenue", 0) / total_assets

            features.altman_z = (
                1.2 * wc_ta +
                1.4 * re_ta +
                3.3 * ebit_ta +
                0.6 * (mcap_tl / max(total_liabilities, 1)) +
                1.0 * sales_ta
            )

        # Beneish M-Score (basitleştirilmiş)
        features.beneish_m = fundamentals.get("beneish_m_score", 0.0)

    # =====================================================
    # YARDIMCI
    # =====================================================

    @staticmethod
    def _returns(prices: List[float]) -> List[float]:
        """Günlük getiri serisi."""
        return [
            (prices[i] / prices[i - 1] - 1) if prices[i - 1] != 0 else 0
            for i in range(1, len(prices))
        ]

    @staticmethod
    def _correlation(x: List[float], y: List[float]) -> float:
        """Pearson korelasyonu."""
        n = min(len(x), len(y))
        if n < 3:
            return 0.0

        x, y = x[:n], y[:n]
        mean_x = sum(x) / n
        mean_y = sum(y) / n

        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

        if std_x == 0 or std_y == 0:
            return 0.0

        return cov / (std_x * std_y)

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Tarih parse et."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            try:
                return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                return None


# Singleton
bist_feature_engine = BISTFeatureEngine()
