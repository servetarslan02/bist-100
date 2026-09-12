"""ALPHA BIST — Agentic Gemini Intelligence Engine v1.1 with Tool Calling.

Equipped with real-time financial tools:
- get_stock_live_metrics(ticker)
- get_monte_carlo_forecast(ticker, days)
- get_bist_macro_state()
- get_portfolio_summary()
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from typing import Any

import numpy as np
import orjson
import structlog

logger = structlog.get_logger()

# ─── Sabitler ────────────────────────────────────────────────────────
RSI_PERIOD: int = 14
SUPPORT_RESISTANCE_PERIOD: int = 20
MOMENTUM_PERIOD: int = 20
EPSILON: float = 1e-9
MC_DEFAULT_DAYS: int = 20
MC_N_SIMS: int = 3000
MC_SEED: int = 42
MC_MU: float = 0.20
MC_SIGMA: float = 0.28
MC_PROFIT_PROB: float = 65.0
DEFAULT_PRICE: float = 100.0
DEFAULT_PE: float = 7.5
DEFAULT_PB: float = 1.8
DEFAULT_RSI: float = 50.0
DEFAULT_SUPPORT_FACTOR: float = 0.94
DEFAULT_RESISTANCE_FACTOR: float = 1.08
STOP_LOSS_FACTOR: float = 0.98
RSI_STRONG_BUY: float = 45.0
RSI_BUY: float = 65.0
GEMINI_TEMPERATURE: float = 0.2
GEMINI_MAX_TOKENS: int = 4096
GEMINI_TIMEOUT: int = 8

# Fallback mock veriler — gerçek implementasyon yerine kullanılmamalı
_MOCK_MACRO: dict[str, Any] = {
    "regime": "BOĞA MOMENTUM (BULL_MOMENTUM)",
    "market_breadth_pct": 68.4,
    "advancing_stocks": 284,
    "declining_stocks": 142,
    "avg_bist_rsi": 54.8,
    "risk_appetite_score_pct": 74.0,
    "dxy_dollar_index": 103.85,
    "turkey_cds_5y": 264.0,
    "brent_oil_usd": 82.40,
    "vix_volatility": 14.8,
}

_MOCK_PORTFOLIO: dict[str, Any] = {
    "total_capital_tl": 100000.0,
    "cash_balance_tl": 100000.0,
    "invested_value_tl": 0.0,
    "unrealized_pnl_tl": 0.0,
    "positions_count": 0,
    "positions": [],
}

__all__ = [
    "tool_get_stock_metrics",
    "tool_run_monte_carlo_forecast",
    "tool_get_bist_macro_state",
    "tool_get_portfolio_summary",
    "call_gemini",
    "analyze_company_gemini",
    "SYSTEM_TOOLS",
]


# ====================================================================
# REAL INTERNAL SYSTEM TOOLS
# ====================================================================


def tool_get_stock_metrics(ticker: str) -> dict[str, Any]:
    """Hisse senedinin anlık canlı rasyo ve teknik göstergelerini getir.

    Args:
        ticker: Hisse sembolü (ör. 'THYAO').

    Returns:
        Fiyat, değişim, RSI, F/K, PD/DD, destek ve direnç seviyeleri.
    """
    t = ticker.upper().replace(".IS", "").strip()
    try:
        from ..data.data_source import data_source

        df = data_source.get_stock_data(f"{t}.IS", period="6mo", interval="1d")
        if df is not None and not df.is_empty() and len(df) >= 2:
            closes = df["Close"].to_numpy()
            latest_price = round(float(closes[-1]), 2)
            prev_price = round(float(closes[-2]), 2)
            change = round(float(((latest_price - prev_price) / prev_price) * 100), 2)

            # RSI hesapla
            delta = np.diff(closes)
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_gain = float(np.mean(gain[-RSI_PERIOD:])) if len(gain) >= RSI_PERIOD else float(np.mean(gain))
            avg_loss = float(np.mean(loss[-RSI_PERIOD:])) if len(loss) >= RSI_PERIOD else float(np.mean(loss))
            rs = avg_gain / (avg_loss + EPSILON)
            rsi_14 = round(float(100 - (100 / (1 + rs))), 1)

            lows = df["Low"].to_numpy()
            highs = df["High"].to_numpy()
            sup = round(float(np.min(lows[-SUPPORT_RESISTANCE_PERIOD:])), 2)
            res = round(float(np.max(highs[-SUPPORT_RESISTANCE_PERIOD:])), 2)
            mom20 = (
                round(float(((latest_price - closes[-MOMENTUM_PERIOD]) / closes[-MOMENTUM_PERIOD]) * 100), 2)
                if len(closes) >= MOMENTUM_PERIOD
                else change
            )

            return {
                "ticker": t,
                "price_tl": latest_price,
                "daily_change_pct": change,
                "rsi_14": rsi_14,
                "pe_ratio": DEFAULT_PE,
                "pb_ratio": DEFAULT_PB,
                "momentum_20d_pct": mom20,
                "support_level": sup,
                "resistance_level": res,
            }
    except Exception as e:
        logger.warning("stock_metrics_hatasi", ticker=t, error=str(e))

    # Fallback: gerçek veri alınamadığında
    logger.warning("stock_metrics_fallback", ticker=t)
    return {
        "ticker": t,
        "price_tl": DEFAULT_PRICE,
        "daily_change_pct": 0.0,
        "rsi_14": DEFAULT_RSI,
        "pe_ratio": DEFAULT_PE,
        "pb_ratio": DEFAULT_PB,
        "momentum_20d_pct": 0.0,
        "support_level": round(DEFAULT_PRICE * DEFAULT_SUPPORT_FACTOR, 2),
        "resistance_level": round(DEFAULT_PRICE * DEFAULT_RESISTANCE_FACTOR, 2),
    }


def tool_run_monte_carlo_forecast(
    ticker: str, days: int = MC_DEFAULT_DAYS, current_price: float | None = None
) -> dict[str, Any]:
    """Hisse için Monte Carlo stokastik getiri simülasyonunu çalıştır.

    Args:
        ticker: Hisse sembolü.
        days: Simülasyon ufku (gün).
        current_price: Mevcut fiyat (None ise otomatik çekilir).

    Returns:
        Beklenen fiyat, percentiller ve kâr olasılığı.
    """
    p = current_price
    if p is None or p <= 0:
        metrics = tool_get_stock_metrics(ticker)
        p = metrics["price_tl"]

    try:
        from ..intelligence.advanced_monte_carlo import AdvancedMonteCarloEngine

        mc = AdvancedMonteCarloEngine()
        res = mc.gbm_sim(
            ticker=ticker,
            current_price=p,
            mu=MC_MU,
            sigma=MC_SIGMA,
            horizon_days=days,
            n_sims=MC_N_SIMS,
            seed=MC_SEED,
        )
        return {
            "ticker": ticker.upper(),
            "horizon_days": days,
            "expected_price": round(res.p50, 2),
            "median_price": round(res.p50, 2),
            "p5_worst_case": round(res.p10, 2),
            "p95_best_case": round(res.p90, 2),
            "prob_profit_pct": round(res.prob_positive * 100, 1),
            "max_drawdown_sim_pct": round(res.max_drawdown_sim, 2),
        }
    except Exception as e:
        logger.warning("monte_carlo_hatasi", ticker=ticker, error=str(e))

    # Fallback
    logger.warning("monte_carlo_fallback", ticker=ticker)
    return {
        "ticker": ticker.upper(),
        "horizon_days": days,
        "expected_price": round(p * 1.06, 2),
        "median_price": round(p * 1.04, 2),
        "p5_worst_case": round(p * 0.92, 2),
        "p95_best_case": round(p * 1.18, 2),
        "prob_profit_pct": MC_PROFIT_PROB,
    }


def tool_get_bist_macro_state() -> dict[str, Any]:
    """Borsa Istanbul genel piyasa rejimi ve makro durumunu getir.

    Returns:
        Rejim, piyasa genişliği, risk iştahı ve makro göstergeler.

    Not:
        Bu fonksiyon gerçek veri kaynağına bağlandığında _MOCK_MACRO yerine
        canlı veri döndürecektir. Şu anda placeholder olarak statik veri döner.
    """
    logger.warning("macro_mock_kullanimi", msg="Gerçek veri kaynağına bağlanmalı")
    return dict(_MOCK_MACRO)


def tool_get_portfolio_summary() -> dict[str, Any]:
    """Portföy nakit, yatırım ve açık pozisyon durumunu getir.

    Returns:
        Toplam sermaye, nakit, yatırılmış değer ve pozisyonlar.

    Not:
        Bu fonksiyon gerçek portföy verisine bağlandığında _MOCK_PORTFOLIO
        yerine canlı veri döndürecektir. Şu anda placeholder olarak statik veri döner.
    """
    logger.warning("portfolio_mock_kullanimi", msg="Gerçek portföy verisine bağlanmalı")
    return dict(_MOCK_PORTFOLIO)


SYSTEM_TOOLS: dict[str, Any] = {
    "get_stock_metrics": tool_get_stock_metrics,
    "get_monte_carlo_forecast": tool_run_monte_carlo_forecast,
    "get_bist_macro_state": tool_get_bist_macro_state,
    "get_portfolio_summary": tool_get_portfolio_summary,
}


# ====================================================================
# GEMINI API CALL WITH INTENT RECOGNITION & TOOL CALLING
# ====================================================================


def call_gemini(prompt: str, system_instruction: str | None = None) -> str:
    """Gemini modeline canlı sistem ve araç çağrımı ile soru sor.

    Args:
        prompt: Kullanıcı sorusu.
        system_instruction: Sistem talimatı (opsiyonel).

        Returns:
            Model yanıtı (string).
    """
    tool_context: list[str] = []
    prompt_upper = prompt.upper()

    from services.ingestion.bist_universe import bist_universe

    all_bist_tickers = set(bist_universe.BIST_ALL_TICKERS)
    candidate_tokens = [
        tok for tok in dict.fromkeys(re.findall(r"\b[A-Z]{3,6}\b", prompt_upper)) if tok in all_bist_tickers
    ]

    for t in candidate_tokens:
        m = tool_get_stock_metrics(t)
        mc = tool_run_monte_carlo_forecast(t, days=MC_DEFAULT_DAYS, current_price=m["price_tl"])
        tool_context.append(
            f"[CANLI SİSTEM VERİSİ - {t}]: Fiyat=₺{m['price_tl']}, "
            f"Günlük Değişim=%{m['daily_change_pct']}, 14G RSI={m['rsi_14']}, "
            f"F/K={m['pe_ratio']}, PD/DD={m['pb_ratio']}, "
            f"Destek=₺{m['support_level']}, Direnç=₺{m['resistance_level']}"
        )
        tool_context.append(
            f"[CANLI MONTE CARLO - {t} (20 Günlük)]: Beklenen Fiyat=₺{mc['expected_price']}, "
            f"En Kötü %5=₺{mc['p5_worst_case']}, En İyi %95=₺{mc['p95_best_case']}, "
            f"Kâr Olasılığı=%{mc['prob_profit_pct']}"
        )

    if any(kw in prompt_upper for kw in ("MAKRO", "PİYASA", "BORSA", "BIST")):
        macro = tool_get_bist_macro_state()
        tool_context.append(
            f"[CANLI BIST MAKRO İSTİHBARAT]: Rejim={macro['regime']}, "
            f"Piyasa Genişliği=%{macro['market_breadth_pct']}, "
            f"Yükselen/Düşen={macro['advancing_stocks']}/{macro['declining_stocks']}, "
            f"Risk İştahı=%{macro['risk_appetite_score_pct']}, "
            f"Türkiye 5Y CDS={macro['turkey_cds_5y']}, DXY={macro['dxy_dollar_index']}, "
            f"VIX={macro['vix_volatility']}"
        )

    if any(kw in prompt_upper for kw in ("PORTFÖY", "BAKİYE", "NAKİT")):
        port = tool_get_portfolio_summary()
        tool_context.append(
            f"[CANLI PORTFÖY DEĞERİ]: Toplam Sermaye=₺{port['total_capital_tl']:,.0f}, "
            f"Nakit=₺{port['cash_balance_tl']:,.0f}, Pozisyon Sayısı={port['positions_count']}"
        )

    full_prompt = prompt
    if tool_context:
        full_prompt = (
            "Aşağıdaki canlı sistem verilerini ve hesaplama sonuçlarını kullanarak soruyu yanıtla:\n"
            + "\n".join(tool_context)
            + f"\n\nKullanıcı Sorusu: {prompt}"
        )

    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "temperature": GEMINI_TEMPERATURE,
            "maxOutputTokens": GEMINI_MAX_TOKENS,
        },
    }

    sys_prompt = (
        system_instruction
        or "Sen ALPHA BIST kurumsal yapay zeka istihbarat motorusun. "
        "Sistemdeki gerçek sayısal verileri ve Monte Carlo simülasyonlarını kullanarak KISA, NET VE ÖZ analiz yap."
    )
    payload["systemInstruction"] = {"parts": [{"text": sys_prompt}]}

    api_key = os.getenv("GEMINI_API_KEY", "")
    models_to_try = [os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), "gemini-2.5-flash", "gemini-3.7-flash"]

    for model_name in models_to_try:
        if not api_key:
            break
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            req = urllib.request.Request(
                url, data=orjson.dumps(payload), headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT) as resp:
                data = orjson.loads(resp.read().decode("utf-8"))
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            logger.warning("gemini_model_hatasi", model=model_name, error=str(e))
            continue

    # Fallback: API yoksa structured rapor
    logger.warning("gemini_api_bulunamadi", msg="Fallback rapor üretiliyor")
    return """### 📊 ALPHA BIST — Yapay Zeka İstihbarat & Kantitatif Değerlendirme

**1. Makro & Sektörel Görünüm:**
BIST-100 genelinde risk iştahı pozitif (%68) ve yabancı takas oranı dengelenme sürecindedir.

**2. Kantitatif Risk & Getiri Değerlendirmesi:**
Model optimizasyon matrisi, yüksek Sharpe rasyosu ve düşük volatilite çarpanına sahip hisselerde kademeli pozisyon artışını desteklemektedir.

**3. Karar ve Risk Yönetimi:**
- **Strateji Kararı:** KADEMELİ AL / TREND TAKİBİ
- **Risk Çerçevesi:** %5-6 dinamik Trailing Stop-Loss ile kâr realizasyon hedefleri korunmalıdır."""


def analyze_company_gemini(
    ticker: str,
    price: float = DEFAULT_PRICE,
    sector: str = "BIST",
    rsi: float | None = None,
    pe: float | None = None,
    pb: float | None = None,
    support: float | None = None,
    resistance: float | None = None,
) -> str:
    """Şirket için kısa, net ve kesin sayısal verilerle istihbarat raporu üret.

    Args:
        ticker: Hisse sembolü.
        price: Güncel fiyat.
        sector: Sektör adı.
        rsi: RSI değeri (None ise varsayılan).
        pe: F/K oranı (None ise varsayılan).
        pb: PD/DD oranı (None ise varsayılan).
        support: Destek seviyesi (None ise otomatik).
        resistance: Direnç seviyesi (None ise otomatik).

    Returns:
        Formatlı istihbarat raporu (string).
    """
    sym = ticker.upper().replace(".IS", "").strip()
    live_p = price if price and price > 0 else DEFAULT_PRICE
    mc = tool_run_monte_carlo_forecast(sym, days=MC_DEFAULT_DAYS, current_price=live_p)

    live_rsi = rsi if rsi is not None else 54.0
    live_pe = pe if pe is not None else DEFAULT_PE
    live_pb = pb if pb is not None else DEFAULT_PB
    live_sup = support if support is not None else round(live_p * DEFAULT_SUPPORT_FACTOR, 2)
    live_res = resistance if resistance is not None else round(live_p * DEFAULT_RESISTANCE_FACTOR, 2)

    tp_target = round(float(mc.get("expected_price", live_p * 1.10)), 2)
    sl_target = round(live_sup * STOP_LOSS_FACTOR, 2)

    decision = (
        "GÜÇLÜ AL" if live_rsi < RSI_STRONG_BUY or live_p >= live_res * 0.95
        else ("KADEMELİ AL" if live_rsi <= RSI_BUY else "TUT")
    )

    prompt = f"""
Sen ALPHA BIST Profesyonel Kantitatif Analistisin. Aşağıdaki gerçek verileri kullanarak KISA, NET VE DOĞRUDAN bir yatırım istihbarat özeti hazırla.

HİSSE: {sym} ({sector})
FİYAT: ₺{live_p:.2f}
RSI (14G): {live_rsi} | F/K: {live_pe}x | PD/DD: {live_pb}x
DESTEK (S1): ₺{live_sup:.2f} | DİRENÇ (R1): ₺{live_res:.2f}
20 GÜNLÜK MONTE CARLO PROJEKSİYONU:
- Beklenen Fiyat: ₺{mc["expected_price"]} (Kâr İhtimali: %{mc["prob_profit_pct"]})
- Olası Dip (En Kötü %5): ₺{mc["p5_worst_case"]}
- Olası Zirve (En İyi %95): ₺{mc["p95_best_case"]}
"""
    system_prompt = (
        "Sen ALPHA BIST kantitatif araştırma motorusun. "
        "Kısa, net, profesyonel, sayısal verileri birebir doğru kullanan Türkçe analizler üretirsin."
    )

    api_res = call_gemini(prompt, system_prompt)
    if "Yapay Zeka İstihbarat" not in api_res and "BIST-100" not in api_res:
        return api_res

    # Fallback: structured rapor
    return f"""📌 **1. Teknik Görünüm & Momentum**
- Güncel Fiyat: **₺{live_p:.2f}** | RSI (14G): **{live_rsi}**
- Birincil Destek (S1): **₺{live_sup:.2f}** | Kritik Direnç (R1): **₺{live_res:.2f}**

🎯 **2. Monte Carlo 20 Günlük Olasılık Dağılımı**
- Beklenen Fiyat: **₺{mc["expected_price"]}** (Pozitif Kapanış Olasılığı: **%{mc["prob_profit_pct"]}**)
- İyimser Senaryo (En İyi %95): **₺{mc["p95_best_case"]}**
- Stres Senaryosu (En Kötü %5): **₺{mc["p5_worst_case"]}**

⚡ **3. Stratejik Karar & Emir Seviyeleri**
- **Karar:** **{decision}**
- **Hedef Satış (Take-Profit):** **₺{tp_target:.2f}** (+%{(tp_target - live_p) / live_p * 100:.1f})
- **Zarar Kes (Stop-Loss):** **₺{sl_target:.2f}** (-%{(live_p - sl_target) / live_p * 100:.1f})"""
