"""ALPHA BIST — Kurumsal Karar Motoru (Decision Engine v3.0).

Bu modül, mikroservislerden, makine öğrenimi modellerinden, piyasa rejimlerinden
ve teknik/temel analizlerden gelen tüm sinyalleri birleştirerek nihai alım/satım/bekleme
kararını (BUY, SELL, HOLD, NO_ACTION) üretir:

1. Çok Kaynaklı Kompozit Skorlama (Multi-Source Composite Scoring):
   - ML Modeli (%20), LLM/Ajan Sistemi (%12), Teknik Analiz (%16), Temel Analiz (%12),
     Haber Sentimenti (%7), Piyasa Rejimi (%7), Makro Stance (%9), Risk Toleransı (%9)
     ve Monte Carlo Olasılık Dağılımı (%8).
2. Rejime Duyarlı Dinamik Eşikler (Regime-Adaptive Thresholds):
   - Ayı (BEAR/PANIC/CRASH) piyasasında sermaye koruma amaçlı yüksek güven ve skor eşikleri.
   - Boğa (BULL/TREND) piyasasında trend takip odaklı dengeli eşikler.
3. BIST Fiyat Adımı (Tick Size) ve ATR Tabanlı Hedef/Zarar-Kes (Stop/Target):
   - BIST Pay Piyasası işlem yönergesine uygun dinamik fiyat adımı yuvarlaması (`round_to_bist_tick`).
   - 2.5x ATR dinamik stop mesafesi ve 1:2 Risk/Ödül oranı.
4. BIST Açığa Satış (Short-Sale) Güvenlik Filtresi:
   - Mevzuat veya sistem kısıtlamalarına göre açığa satış izni yoksa SHORT yönü güvenli moda alınır.
5. DuckDB & Polars Karar Denetim İzi (Decision Audit Trail):
   - Üretilen tüm kararlar kalıcı DuckDB günlüğüne kaydedilir ve Polars DataFrame olarak sunulur.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import trace

from services.core.bist_tick_size import round_to_bist_tick
from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.decision_engine")

# Varsayılan Karar Parametreleri
DEFAULT_MIN_SCORE: Final[float] = 60.0
DEFAULT_MIN_CONFIDENCE: Final[float] = 0.65
DEFAULT_STOP_FALLBACK_PCT: Final[float] = 6.5  # BIST ortalaması için makul stop yüzdesi
DEFAULT_DECISION_DB_PATH: Final[str] = "data/decision_audit.duckdb"


class Action(StrEnum):
    """Karar aksiyon türleri."""

    BUY = "BUY"  # Alım emri
    SELL = "SELL"  # Satış / Kar realizasyonu veya açığa satış
    HOLD = "HOLD"  # Mevcut pozisyonu koru
    NO_ACTION = "NO_ACTION"  # İşlem yapma / Eşiklerin altında


@dataclass(slots=True)
class DecisionInput:
    """Karar motoruna iletilen girdi parametreleri veri modeli."""

    ticker: str
    price: float
    features: dict[str, Any] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)
    regime: str = "UNKNOWN"
    ml_score: float = 50.0
    ml_confidence: float = 0.5
    news_sentiment: float = 0.0
    sector: str = ""
    market_cap: float = 0.0
    # ATR Bilgileri
    atr: float = 0.0
    atr_pct: float = 0.0
    # Ajan ve LLM Sinyalleri
    agent_direction: str = "NEUTRAL"
    agent_confidence: float = 0.0
    agent_score: float = 50.0
    # Makroekonomik Göstergeler
    macro_regime: str = "UNKNOWN"
    macro_stance: float = 0.0  # -1.0 (negatif) ile +1.0 (pozitif)
    macro_confidence: float = 0.0
    macro_impact: float = 0.0  # Sektörel makro etki
    # Model Tahminleri ve Simülasyon
    ml_return_5d: float = 0.0
    ml_return_20d: float = 0.0
    spec_score: float = 0.0
    world_alignment: float = 0.0
    sim_expected_return: float = 0.0
    sim_var_95: float = 0.0
    sim_prob_positive: float = 0.0
    ai_direction: str = "NEUTRAL"
    ai_confidence: float = 0.0
    max_position_pct: float = 10.0
    current_position_pct: float = 0.0
    portfolio_drawdown: float = 0.0
    avg_volume: float = 0.0
    spread_pct: float = 0.0
    allow_short: bool = False  # BIST açığa satış izni bayrağı

    def __repr__(self) -> str:
        """Nesnenin okunabilir hata ayıklama temsili."""
        return (
            f"DecisionInput(ticker={self.ticker!r}, price={self.price}, "
            f"regime={self.regime!r}, ml_score={self.ml_score:.1f}, conf={self.ml_confidence:.2f})"
        )


@dataclass(slots=True)
class Decision:
    """Karar motoru nihai çıktı veri modeli."""

    ticker: str
    action: str  # BUY, SELL, HOLD, NO_ACTION
    direction: str  # LONG, SHORT, NEUTRAL
    confidence: float
    score: float
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    target_price: float = 0.0
    stop_price: float = 0.0
    position_size: float = 0.0
    time_horizon: str = "1-5D"
    expected_return: float = 0.0
    conviction: str = "LOW"  # LOW, MEDIUM, HIGH
    llm_narrative: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serileştirilebilir sözlük temsili üretir."""
        return {
            "ticker": self.ticker,
            "action": self.action,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "score": round(self.score, 2),
            "reasons": self.reasons,
            "risks": self.risks,
            "target_price": self.target_price,
            "stop_price": self.stop_price,
            "position_size": self.position_size,
            "time_horizon": self.time_horizon,
            "expected_return": self.expected_return,
            "conviction": self.conviction,
            "llm_narrative": self.llm_narrative,
            "timestamp": self.timestamp.isoformat(),
        }

    def __repr__(self) -> str:
        """Nihai kararın okunabilir dökümü."""
        return (
            f"Decision(ticker={self.ticker!r}, action={self.action!r}, "
            f"direction={self.direction!r}, score={self.score:.1f}, conf={self.confidence:.2f}, "
            f"target={self.target_price}, stop={self.stop_price})"
        )


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Float değerleri güvenle dönüştürür; None/NaN/Inf durumlarında default döner."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return default


class DecisionEngine:
    """Kurumsal BIST Karar Motoru (Decision Engine).

    ML modelleri, teknik faktörler, temel rasyolar, makro göstergeler ve Monte Carlo
    simülasyonlarını dinamik piyasa rejimleri altında sentezler.
    """

    DEFAULT_STOP_FALLBACK = DEFAULT_STOP_FALLBACK_PCT

    def __init__(
        self,
        min_score: float = DEFAULT_MIN_SCORE,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        db_path: str = DEFAULT_DECISION_DB_PATH,
    ) -> None:
        """DecisionEngine motorunu başlatır.

        Args:
            min_score: Karar üretimi için gereken asgari kompozit skor.
            min_confidence: Karar üretimi için gereken asgari model güveni.
            db_path: Kararların saklanacağı DuckDB veritabanı yolu.
        """
        self._min_score = min_score
        self._min_confidence = min_confidence
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._init_db()
        logger.info("decision_engine_baslatildi", min_score=min_score, min_conf=min_confidence)

    def _init_db(self) -> None:
        """Kalıcı DuckDB karar denetim tablosunu hazırlar."""
        try:
            db_file = Path(self._db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(db_file))
            with self._lock:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS decision_audit_log (
                        id BIGINT PRIMARY KEY,
                        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                        ticker VARCHAR NOT NULL,
                        action VARCHAR NOT NULL,
                        direction VARCHAR NOT NULL,
                        confidence DOUBLE NOT NULL,
                        score DOUBLE NOT NULL,
                        target_price DOUBLE NOT NULL,
                        stop_price DOUBLE NOT NULL,
                        expected_return DOUBLE NOT NULL,
                        conviction VARCHAR NOT NULL,
                        reasons_json VARCHAR NOT NULL,
                        risks_json VARCHAR NOT NULL
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_decision_audit_id START 1;
                    """
                )
            logger.info("decision_audit_store_hazirlandi", db_path=self._db_path)
        except Exception as exc:
            logger.error("decision_db_baslatma_hatasi", error=str(exc), path=self._db_path)
            self._conn = None

    def close(self) -> None:
        """DuckDB bağlantısını kapatır."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as exc:
                    logger.debug("decision_db_kapatma_hatasi", error=str(exc))
                finally:
                    self._conn = None

    def _persist_decision(self, dec: Decision) -> None:
        """Alınan kararı kalıcı DuckDB günlüğüne kaydeder."""
        if self._conn is None:
            return

        with self._lock:
            try:
                reasons_str = orjson.dumps(dec.reasons).decode("utf-8")
                risks_str = orjson.dumps(dec.risks).decode("utf-8")
                self._conn.execute(
                    """
                    INSERT INTO decision_audit_log (
                        id, timestamp, ticker, action, direction, confidence,
                        score, target_price, stop_price, expected_return,
                        conviction, reasons_json, risks_json
                    ) VALUES (
                        nextval('seq_decision_audit_id'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    );
                    """,
                    [
                        dec.timestamp,
                        dec.ticker,
                        dec.action,
                        dec.direction,
                        dec.confidence,
                        dec.score,
                        dec.target_price,
                        dec.stop_price,
                        dec.expected_return,
                        dec.conviction,
                        reasons_str,
                        risks_str,
                    ],
                )
            except Exception as exc:
                logger.warning("decision_audit_kayit_hatasi", ticker=dec.ticker, error=str(exc))

    def _get_dynamic_thresholds(self, regime: str) -> tuple[float, float]:
        """Piyasa rejimine göre dinamik skor ve güven eşiklerini belirler."""
        regime_upper = (regime or "").upper()
        if any(r in regime_upper for r in ("BEAR", "PANIC", "CRASH")):
            return 68.0, 0.70  # Ayı piyasasında katı eşik (sermaye koruma)
        elif any(r in regime_upper for r in ("VOLATILE", "HIGH_VOL", "SIDEWAYS")):
            return 63.0, 0.65  # Yatay veya dalgalı piyasada seçici
        elif any(r in regime_upper for r in ("BULL", "TREND", "RECOVERY")):
            return 58.0, 0.60  # Boğa piyasasında trend takip
        return self._min_score, self._min_confidence

    @otel_trace("decision_engine.make_decision")
    def make_decision(
        self,
        ticker: str,
        signal: dict[str, Any],
        risk_check: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """B18 ve eski servislerle geriye dönük tam uyumlu karar arayüzü.

        Placeholder değerler yerine sinyalden DecisionInput sentezleyerek
        gerçek karar motorunu çalıştırır.
        """
        price = _safe_float(signal.get("price", signal.get("close", 0.0)))
        features = signal.get("features", {})
        inp = DecisionInput(
            ticker=ticker,
            price=price,
            features=features,
            signals=signal,
            regime=signal.get("regime", "UNKNOWN"),
            ml_score=_safe_float(signal.get("score", signal.get("fused_score", 50.0)), 50.0),
            ml_confidence=_safe_float(signal.get("confidence", signal.get("fused_confidence", 0.5)), 0.5),
            atr=_safe_float(features.get("atr_14", features.get("atr", 0.0))),
            atr_pct=_safe_float(features.get("atr_pct", 0.0)),
            allow_short=bool(signal.get("allow_short", False)),
        )
        dec = self.decide(inp)
        res_dict = dec.to_dict()
        if risk_check and not risk_check.get("passed", True):
            res_dict["action"] = Action.HOLD.value
            res_dict["risks"].append(f"Risk kontrolü engeli: {risk_check.get('reason', 'Bilinmiyor')}")
        return res_dict

    @otel_trace("decision_engine.decide")
    def decide(self, inp: DecisionInput) -> Decision:
        """Nihai işlem kararını fail-closed ve rejime duyarlı olarak üretir."""
        clean_ticker = (inp.ticker or "").strip().upper()

        # Sayısal Geçersizlik Koruması
        if math.isnan(inp.price) or math.isinf(inp.price) or inp.price <= 0:
            dec = Decision(
                ticker=clean_ticker,
                action=Action.NO_ACTION.value,
                direction="NEUTRAL",
                confidence=inp.ml_confidence,
                score=0.0,
                reasons=[f"Geçersiz veya pozitif olmayan hisse fiyatı: {inp.price}"],
            )
            self._persist_decision(dec)
            return dec

        # 1. Kompozit Skoru Hesapla
        score = self._calculate_composite_score(inp)

        # 2. Yönü Belirle
        direction = self._determine_direction(inp)

        # 3. Rejime Duyarlı Simetrik Eşik Kontrolü
        min_score, min_conf = self._get_dynamic_thresholds(inp.regime)
        max_bearish_score = 100.0 - min_score  # Simetrik ayı eşiği (örn: 100 - 60 = 40.0)

        is_bullish_qualified = direction == "LONG" and score >= min_score and inp.ml_confidence >= min_conf
        is_bearish_qualified = direction == "SHORT" and score <= max_bearish_score and inp.ml_confidence >= min_conf

        if not (is_bullish_qualified or is_bearish_qualified):
            dec = Decision(
                ticker=clean_ticker,
                action=Action.NO_ACTION.value,
                direction="NEUTRAL",
                confidence=inp.ml_confidence,
                score=score,
                reasons=[
                    f"Skor ({score:.1f}) veya güven ({inp.ml_confidence:.2f}) "
                    f"rejim eşiğini ({inp.regime}: min_bull={min_score}, max_bear={max_bearish_score}, min_conf={min_conf}) karşılamıyor."
                ],
            )
            self._persist_decision(dec)
            return dec

        # 4. BIST Açığa Satış Guard'ı ile Aksiyon Belirle
        action = self._determine_action(inp, direction)

        # 5. Stop ve Target Hesapla (BIST Tick Size ve ATR Bazlı)
        stop_price, target_price = self._calculate_stop_and_target(inp, direction)

        # 6. Risk Değerlendirmesi
        risks = self._assess_risks(inp)

        # 7. Gerekçeleri Oluştur
        reasons = self._generate_reasons(inp, score)

        # 8. Conviction (Kanaat Derecesi)
        if score >= 80.0 and inp.ml_confidence >= 0.80:
            conviction = "HIGH"
        elif score >= 60.0 and inp.ml_confidence >= 0.65:
            conviction = "MEDIUM"
        else:
            conviction = "LOW"

        dec = Decision(
            ticker=clean_ticker,
            action=action,
            direction=direction,
            confidence=inp.ml_confidence,
            score=score,
            reasons=reasons,
            risks=risks,
            target_price=target_price,
            stop_price=stop_price,
            expected_return=self._calculate_expected_return(inp, direction),
            conviction=conviction,
        )
        self._persist_decision(dec)
        return dec

    def _calculate_composite_score(self, inp: DecisionInput) -> float:
        """Tüm analitik bileşenleri güven-ağırlıklı ve simetrik harmanlar."""
        if inp.spec_score > 0:
            ml_weight = max(min(inp.ml_confidence, 1.0), 0.5)
            spec_weight = 1.0 - ml_weight
            ml_component = (inp.ml_score * ml_weight) + ((inp.spec_score * 0.9) * spec_weight)
        else:
            ml_component = inp.ml_score

        agent_component = inp.agent_score if inp.agent_confidence > 0.5 else 50.0

        components = {
            "ml_score": ml_component * 0.20,
            "agent": agent_component * 0.12,
            "technical": self._technical_score(inp) * 0.16,
            "fundamental": self._fundamental_score(inp) * 0.12,
            "sentiment": self._sentiment_score(inp) * 0.07,
            "regime": self._regime_score(inp) * 0.07,
            "macro": self._macro_score(inp) * 0.09,
            "risk": self._risk_score(inp) * 0.09,
            "monte_carlo": self._monte_carlo_score(inp) * 0.08,
        }

        total = sum(components.values())

        # Simetrik Getiri Bonusu / Cezası
        if inp.ml_return_5d > 3.0:
            total += 5.0
        elif inp.ml_return_5d < -3.0:
            total -= 5.0

        if inp.ml_return_20d > 8.0:
            total += 5.0
        elif inp.ml_return_20d < -8.0:
            total -= 5.0

        # Monte Carlo Bonus / Ceza
        if inp.sim_expected_return > 0 and inp.sim_prob_positive > 0.60:
            total += 3.0
        elif inp.sim_expected_return < 0 and inp.sim_prob_positive < 0.40:
            total -= 3.0

        return min(100.0, max(0.0, total))

    def _monte_carlo_score(self, inp: DecisionInput) -> float:
        """Monte Carlo simülasyon sonuçlarını puanlar."""
        score = 50.0
        if inp.sim_var_95 != 0:
            var_abs = abs(inp.sim_var_95)
            if var_abs < 5.0:
                score += 15.0
            elif var_abs < 10.0:
                score += 5.0
            elif var_abs > 20.0:
                score -= 15.0
            elif var_abs > 15.0:
                score -= 10.0

        if inp.sim_expected_return > 3.0:
            score += 10.0
        elif inp.sim_expected_return > 0:
            score += 5.0
        elif inp.sim_expected_return < -3.0:
            score -= 10.0
        elif inp.sim_expected_return < 0:
            score -= 5.0

        if inp.sim_prob_positive > 0.70:
            score += 10.0
        elif inp.sim_prob_positive > 0.55:
            score += 5.0
        elif inp.sim_prob_positive < 0.30:
            score -= 10.0
        elif inp.sim_prob_positive < 0.45:
            score -= 5.0

        return min(100.0, max(0.0, score))

    def _technical_score(self, inp: DecisionInput) -> float:
        """Teknik göstergeleri puanlar."""
        f = inp.features
        score = 50.0

        momentum = _safe_float(f.get("momentum_20d", 0))
        roc = _safe_float(f.get("roc_5d", 0))
        rsi = _safe_float(f.get("rsi_14", 50), 50.0)
        volume = _safe_float(f.get("volume_zscore", 0))
        bb = _safe_float(f.get("bb_position", 0.5), 0.5)

        score += momentum * 0.3
        score += roc * 0.3
        score += (rsi - 50.0) * 0.2
        score += volume * 0.1
        score += (bb - 0.5) * 20.0

        return min(100.0, max(0.0, score))

    def _fundamental_score(self, inp: DecisionInput) -> float:
        """Temel analiz göstergelerini puanlar."""
        f = inp.features
        score = 50.0

        fundamental = _safe_float(f.get("fundamental_score", 0))
        pe = _safe_float(f.get("pe_ratio", 15), 15.0)
        pb = _safe_float(f.get("pb_ratio", 1.5), 1.5)
        roe = _safe_float(f.get("roe", 0))

        score += fundamental * 0.4
        score += (20.0 - pe) * 1.0
        score += (2.0 - pb) * 10.0
        score += roe * 0.2

        return min(100.0, max(0.0, score))

    def _sentiment_score(self, inp: DecisionInput) -> float:
        """Haber ve sosyal medya sentimentini puanlar."""
        sentiment = min(1.0, max(-1.0, inp.news_sentiment))
        return 50.0 + (sentiment * 50.0)

    def _regime_score(self, inp: DecisionInput) -> float:
        """Piyasa rejim puanını belirler."""
        regime_scores: dict[str, float] = {
            "BULL": 80.0,
            "BULL_VOLATILE": 70.0,
            "BEAR": 30.0,
            "BEAR_VOLATILE": 25.0,
            "SIDEWAYS": 50.0,
            "SIDEWAYS_VOLATILE": 45.0,
            "RECOVERY": 65.0,
            "DISTRIBUTION": 35.0,
            "ACCUMULATION": 70.0,
            "CRASH": 20.0,
        }
        return regime_scores.get(inp.regime.upper(), 50.0)

    def _risk_score(self, inp: DecisionInput) -> float:
        """Risk toleransı ve oynaklık puanını belirler."""
        f = inp.features
        score = 50.0

        atr_pct = _safe_float(f.get("atr_pct", inp.atr_pct))
        if atr_pct > 0:
            score -= atr_pct * 2.0

        adx = _safe_float(f.get("adx", 25), 25.0)
        score += (adx - 25.0) * 0.5

        volume = _safe_float(f.get("volume_zscore", 0))
        score += volume * 0.5

        if inp.sim_var_95 != 0:
            var_abs = abs(inp.sim_var_95)
            score += max(-15.0, min(10.0, (10.0 - var_abs) * 0.8))

        return min(100.0, max(0.0, score))

    def _macro_score(self, inp: DecisionInput) -> float:
        """Makroekonomik rejim ve sektör etkilerini puanlar."""
        score = 50.0

        if inp.macro_stance != 0:
            score += inp.macro_stance * 20.0

        if inp.macro_confidence > 0.5:
            score += inp.macro_stance * 10.0

        if inp.macro_impact != 0:
            score += inp.macro_impact * 15.0

        regime_bonuses: dict[str, float] = {
            "EXPANSION": 5.0,
            "RISK_ON": 5.0,
            "CONTRACTION": -5.0,
            "STAGFLATION": -10.0,
            "RISK_OFF": -8.0,
            "REFLATION": 0.0,
        }
        score += regime_bonuses.get(inp.macro_regime.upper(), 0.0)

        return min(100.0, max(0.0, score))

    def _determine_direction(self, inp: DecisionInput) -> str:
        """Simetrik ve tarafsız sinyal entegrasyonuyla işlem yönünü belirler."""
        f = inp.features
        momentum = _safe_float(f.get("momentum_20d", 0))
        roc = _safe_float(f.get("roc_5d", 0))
        rsi = _safe_float(f.get("rsi_14", 50), 50.0)

        bullish_signals = sum([
            momentum > 0,
            roc > 0,
            rsi > 52.0,
            inp.ml_score > 55.0,
        ])

        bearish_signals = sum([
            momentum < 0,
            roc < 0,
            rsi < 48.0,
            inp.ml_score < 45.0,
        ])

        if bullish_signals >= 3:
            return "LONG"
        elif bearish_signals >= 3:
            return "SHORT"

        return "HOLD"

    def _determine_action(self, inp: DecisionInput, direction: str) -> str:
        """İşlem yönü ve BIST mevzuatına göre nihai aksiyonu belirler."""
        if inp.ml_confidence < self._min_confidence:
            return Action.NO_ACTION.value

        if direction == "LONG":
            return Action.BUY.value
        elif direction == "SHORT":
            # BIST açığa satış izni kontrolü (Fail-Closed)
            if not inp.allow_short:
                logger.debug("bist_aciga_satis_engeli_short_hold_yapildi", ticker=inp.ticker)
                return Action.HOLD.value
            return Action.SELL.value

        return Action.HOLD.value

    def _calculate_stop_and_target(
        self,
        inp: DecisionInput,
        direction: str,
    ) -> tuple[float, float]:
        """ATR bazlı dinamik stop ve hedef fiyatları BIST tick size kurallarına göre hesaplar."""
        price = inp.price
        atr = inp.atr
        atr_pct = inp.atr_pct

        if price <= 0:
            return 0.0, 0.0

        # Canonical ATR Formülasyonu
        if atr > 0:
            stop_distance = atr * 2.5
            stop_pct = (stop_distance / price) * 100.0
        elif atr_pct > 0:
            stop_pct = atr_pct * 1.5
        else:
            stop_pct = self.DEFAULT_STOP_FALLBACK

        # Sınırla: minimum %4.0, maksimum %10.0
        stop_pct = max(4.0, min(10.0, stop_pct))
        target_pct = stop_pct * 2.0  # 1:2 Risk / Getiri oranı

        if direction == "LONG":
            raw_stop = price * (1.0 - (stop_pct / 100.0))
            raw_target = price * (1.0 + (target_pct / 100.0))
        elif direction == "SHORT":
            raw_stop = price * (1.0 + (stop_pct / 100.0))
            raw_target = price * (1.0 - (target_pct / 100.0))
        else:
            return 0.0, 0.0

        # BIST Fiyat Adımı Yuvarlaması (bist_tick_size)
        valid_stop = round_to_bist_tick(raw_stop)
        valid_target = round_to_bist_tick(raw_target)

        return valid_stop, valid_target

    def _assess_risks(self, inp: DecisionInput) -> list[str]:
        """Karara ilişkin risk faktörlerini tespit eder."""
        risks = []
        f = inp.features

        if _safe_float(f.get("atr_pct", inp.atr_pct)) > 5.0:
            risks.append("Yüksek volatilite")

        rsi = _safe_float(f.get("rsi_14", 50), 50.0)
        if rsi > 80.0 or rsi < 20.0:
            risks.append("Aşırı alım/satım (RSI)")

        if inp.news_sentiment < -0.5:
            risks.append("Negatif haber sentimenti")

        if inp.ml_confidence < 0.75:
            risks.append("Düşük model güveni")

        if inp.sim_var_95 != 0 and abs(inp.sim_var_95) > 15.0:
            risks.append(f"MC VaR yüksek: %{abs(inp.sim_var_95):.1f}")

        if inp.sim_prob_positive < 0.35 and inp.sim_prob_positive > 0:
            risks.append(f"MC olasılık düşük: %{inp.sim_prob_positive * 100:.0f}")

        if inp.sim_expected_return < -5.0:
            risks.append(f"MC beklenen getiri negatif: %{inp.sim_expected_return:.1f}")

        if not risks:
            risks.append("Düşük risk profili")

        return risks

    def _generate_reasons(self, inp: DecisionInput, score: float) -> list[str]:
        """Kararın gerekçelerini metinsel olarak üretir."""
        reasons = []
        f = inp.features

        if _safe_float(f.get("momentum_20d", 0)) > 5.0:
            reasons.append("Güçlü momentum")

        if _safe_float(f.get("roc_5d", 0)) > 3.0:
            reasons.append("Pozitif kısa vadeli getiri")

        if _safe_float(f.get("volume_zscore", 0)) > 1.0:
            reasons.append("Yüksek hacim onayı")

        if inp.news_sentiment > 0.3:
            reasons.append("Pozitif haber sentimenti")

        if score > 80.0:
            reasons.append("Çok yüksek composite skor")

        if not reasons:
            reasons.append("Teknik ve temel göstergeler uyumlu")

        return reasons

    def _calculate_expected_return(self, inp: DecisionInput, direction: str) -> float:
        """Çok kaynaklı harmanlanmış beklenen getiri tahmini üretir."""
        if direction not in ("LONG", "SHORT"):
            return 0.0

        f = inp.features
        raw_momentum = (_safe_float(f.get("momentum_20d", 0)) + _safe_float(f.get("roc_5d", 0))) / 2.0

        if inp.ml_return_5d != 0 or inp.sim_expected_return != 0:
            expected = (raw_momentum * 0.3) + (inp.ml_return_5d * 0.4) + (inp.sim_expected_return * 0.3)
        else:
            expected = raw_momentum

        if direction == "SHORT":
            expected = -abs(expected) if expected > 0 else expected
        elif direction == "LONG":
            expected = abs(expected) if expected < 0 and raw_momentum > 0 else expected

        return round(float(expected), 2)

    def decide_from_canonical(self, score: Any, price: float = 0.0) -> Decision:
        """CanonicalScore nesnesinden BIST tick kurallarına uygun nihai karar üretir."""
        from services.core.canonical_scoring import CanonicalScore

        if not isinstance(score, CanonicalScore):
            raise TypeError(f"CanonicalScore bekleniyordu, alınan: {type(score)}")

        # Eşik Kontrolleri
        if score.confidence < self._min_confidence:
            dec = Decision(
                ticker=score.ticker,
                action=Action.NO_ACTION.value,
                direction="NEUTRAL",
                confidence=score.confidence,
                score=score.opportunity_score,
                reasons=[f"Confidence eşik altında: {score.confidence:.2f} < {self._min_confidence}"],
            )
            self._persist_decision(dec)
            return dec

        if score.opportunity_score < self._min_score:
            dec = Decision(
                ticker=score.ticker,
                action=Action.NO_ACTION.value,
                direction="NEUTRAL",
                confidence=score.confidence,
                score=score.opportunity_score,
                reasons=[f"Skor eşik altında: {score.opportunity_score:.1f} < {self._min_score}"],
            )
            self._persist_decision(dec)
            return dec

        direction = score.direction
        if direction == "NEUTRAL":
            action = Action.HOLD.value
        elif direction == "LONG":
            action = Action.BUY.value
        else:
            action = Action.SELL.value

        # Risk Skoru Kontrolü
        if score.risk_score < 30.0 and action in (Action.BUY.value, Action.SELL.value):
            action = Action.HOLD.value
            direction = "NEUTRAL"

        # BIST Fiyat Adımlı Stop ve Target Hesaplama
        stop_price = 0.0
        target_price = 0.0
        if price > 0 and action in (Action.BUY.value, Action.SELL.value):
            vec_dict = getattr(score.vector, "__dict__", {})
            atr = _safe_float(vec_dict.get("atr", 0.0))
            atr_pct = _safe_float(vec_dict.get("atr_pct", 0.0))

            if atr > 0:
                stop_distance = atr * 2.5
                stop_pct = (stop_distance / price) * 100.0
            elif atr_pct > 0:
                stop_pct = atr_pct * 1.5
            else:
                stop_pct = self.DEFAULT_STOP_FALLBACK

            stop_pct = max(4.0, min(10.0, stop_pct))
            target_pct = stop_pct * 2.0

            if direction == "LONG":
                raw_stop = price * (1.0 - (stop_pct / 100.0))
                raw_target = price * (1.0 + (target_pct / 100.0))
            elif direction == "SHORT":
                raw_stop = price * (1.0 + (stop_pct / 100.0))
                raw_target = price * (1.0 - (target_pct / 100.0))
            else:
                raw_stop, raw_target = 0.0, 0.0

            stop_price = round_to_bist_tick(raw_stop) if raw_stop > 0 else 0.0
            target_price = round_to_bist_tick(raw_target) if raw_target > 0 else 0.0

        # Conviction
        if score.opportunity_score >= 80.0 and score.confidence >= 0.80:
            conviction = "HIGH"
        elif score.opportunity_score >= 65.0 and score.confidence >= 0.65:
            conviction = "MEDIUM"
        else:
            conviction = "LOW"

        # Nedenler & Riskler
        reasons = []
        v = score.vector
        if getattr(v, "momentum", 0) > 65:
            reasons.append(f"Momentum güçlü: {v.momentum:.0f}")
        if getattr(v, "relative_strength", 0) > 65:
            reasons.append(f"Relatif güç yüksek: {v.relative_strength:.0f}")
        if getattr(v, "fundamental", 0) > 65:
            reasons.append(f"Fundamental pozitif: {v.fundamental:.0f}")
        if getattr(v, "news_sentiment", 0) > 65:
            reasons.append(f"Sentiment olumlu: {v.news_sentiment:.0f}")
        if not reasons:
            reasons.append("Genel kompozit skor eşiği aşıldı")

        risks = []
        if getattr(v, "risk", 50) < 40:
            risks.append(f"Yüksek risk faktörü: {v.risk:.0f}")
        if getattr(v, "data_quality", 100) < 60:
            risks.append(f"Düşük veri kalitesi: {v.data_quality:.0f}")
        if not risks:
            risks.append("Belirgin risk tespit edilmedi")

        dec = Decision(
            ticker=score.ticker,
            action=action,
            direction=direction,
            confidence=score.confidence,
            score=score.opportunity_score,
            reasons=reasons,
            risks=risks,
            stop_price=stop_price,
            target_price=target_price,
            conviction=conviction,
        )
        self._persist_decision(dec)
        return dec

    def export_decisions_to_polars(self, limit: int = 100) -> pl.DataFrame:
        """Kalıcı DuckDB karar geçmişini sıfır kopyalı Polars DataFrame olarak dışa aktarır."""
        if self._conn is None:
            return pl.DataFrame()

        with self._lock:
            try:
                arrow_table = self._conn.execute(
                    """
                    SELECT id, timestamp, ticker, action, direction, confidence,
                           score, target_price, stop_price, expected_return,
                           conviction, reasons_json, risks_json
                    FROM decision_audit_log
                    ORDER BY id DESC
                    LIMIT ?;
                    """,
                    [limit],
                ).arrow()
                return pl.from_arrow(arrow_table)  # type: ignore[return-value]
            except Exception as exc:
                logger.error("decision_history_polars_hatasi", error=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        """Karar motorunun okunabilir durum temsili."""
        return (
            f"DecisionEngine(min_score={self._min_score}, min_conf={self._min_confidence}, "
            f"db_path={self._db_path!r})"
        )


# Global Tekil Nesne (Singleton)
decision_engine: Final[DecisionEngine] = DecisionEngine()

__all__: Final[list[str]] = [
    "Action",
    "DEFAULT_DECISION_DB_PATH",
    "DEFAULT_MIN_CONFIDENCE",
    "DEFAULT_MIN_SCORE",
    "DEFAULT_STOP_FALLBACK_PCT",
    "Decision",
    "DecisionEngine",
    "DecisionInput",
    "decision_engine",
]
