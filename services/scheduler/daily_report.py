"""ALPHA BIST — Günlük Rapor Üretici (Institutional Daily Report Engine)

Her gün piyasa kapandıktan sonra otomatik rapor üretir.
Konsol (düz metin), Markdown (Telegram/Discord/Web) ve yapılandırılmış JSON çıktısı sağlar.
"""

from __future__ import annotations

from typing import Any

import orjson
import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "generate_daily_report",
    "generate_daily_report_dict",
    "generate_alert_message",
    "generate_anomaly_alert",
]


def generate_daily_report_dict(
    date: str,
    market_state: dict[str, Any],
    signals: list[dict[str, Any]],
    trade_plans: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
    portfolio: dict[str, Any],
    world_state: dict[str, Any],
) -> dict[str, Any]:
    """Günlük piyasa ve portföy durumunu yapılandırılmış sözlük formatında döndürür.

    Args:
        date: Rapor tarihi (YYYY-MM-DD).
        market_state: BIST piyasa genişliği, rejim ve anomali durumu.
        signals: Günün en yüksek inançlı model sinyalleri.
        trade_plans: Risk/getiri hesaplanmış işlem planları.
        anomalies: Tespit edilen hacim ve fiyat anomalileri.
        portfolio: Portföy sermaye, kâr/zarar ve nakit durumu.
        world_state: Küresel makro risk, VIX ve döviz verileri.

    Returns:
        dict[str, Any]: Yapılandırılmış kurumsal günlük rapor verisi.
    """
    return {
        "date": date,
        "market": {
            "regime": market_state.get("regime", "UNKNOWN"),
            "breadth_pct": round(float(market_state.get("breadth_pct", 0.0)), 2),
            "advancing": int(market_state.get("advancing", 0)),
            "declining": int(market_state.get("declining", 0)),
            "anomaly_count": int(market_state.get("anomaly_count", 0)),
        },
        "global_macro": {
            "vix_level": round(float(world_state.get("vix_level", 0.0)), 2),
            "usd_strength": round(float(world_state.get("usd_strength", 0.0)), 3),
            "turkey_macro_risk": round(float(world_state.get("turkey_macro_risk", 0.0)), 3),
            "global_risk_appetite": round(float(world_state.get("global_risk_appetite", 0.0)), 3),
        },
        "top_signals": signals[:10],
        "trade_plans": trade_plans,
        "anomalies": anomalies[:10],
        "portfolio_summary": {
            "capital": round(float(portfolio.get("capital", 0.0)), 2),
            "invested": round(float(portfolio.get("invested", 0.0)), 2),
            "cash": round(float(portfolio.get("cash", 0.0)), 2),
            "pnl": round(float(portfolio.get("pnl", 0.0)), 2),
            "pnl_pct": round(float(portfolio.get("pnl_pct", 0.0)), 2),
        },
        "statistics": {
            "scanned_count": len(signals),
            "signal_count": len(signals),
            "plan_count": len(trade_plans),
            "anomaly_count": len(anomalies),
        },
    }


def generate_daily_report(
    date: str,
    market_state: dict[str, Any],
    signals: list[dict[str, Any]],
    trade_plans: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
    portfolio: dict[str, Any],
    world_state: dict[str, Any],
    report_format: str = "text",
) -> str:
    """Günlük kurumsal piyasa ve işlem raporu metnini üretir.

    Args:
        date: Rapor tarihi (YYYY-MM-DD).
        market_state: Piyasa rejim ve genişlik verileri.
        signals: Üretilen model sinyalleri listesi.
        trade_plans: İşlem planları listesi.
        anomalies: Hacim/fiyat anomalileri listesi.
        portfolio: Portföy durum sözlüğü.
        world_state: Küresel göstergeler sözlüğü.
        report_format: Çıktı biçimi ("text", "markdown" veya "json").

    Returns:
        str: Biçimlendirilmiş rapor metni.
    """
    if report_format == "json":
        data = generate_daily_report_dict(date, market_state, signals, trade_plans, anomalies, portfolio, world_state)
        return orjson.dumps(data, option=orjson.OPT_INDENT_2).decode("utf-8")

    lines: list[str] = []

    if report_format == "markdown":
        lines.append(f"# 🏛️ ALPHA BIST — Günlük Kurumsal Rapor ({date})")
        lines.append("")
        lines.append("## 📊 Piyasa Durumu & Rejim")
        lines.append(f"- **Piyasa Rejimi:** `{market_state.get('regime', 'UNKNOWN')}`")
        lines.append(f"- **Piyasa Genişliği (Breadth):** %{float(market_state.get('breadth_pct', 0.0)):.1f}")
        lines.append(f"- **Yükselen / Düşen:** 🟢 {market_state.get('advancing', 0)} / 🔴 {market_state.get('declining', 0)}")
        lines.append(f"- **Anomali Adedi:** {market_state.get('anomaly_count', 0)}")
        lines.append("")
        lines.append("## 🌍 Küresel & Makro Göstergeler")
        lines.append(f"- **VIX Volatilite:** `{float(world_state.get('vix_level', 0.0)):.1f}`")
        lines.append(f"- **USD Gücü:** `{float(world_state.get('usd_strength', 0.0)):.2f}`")
        lines.append(f"- **Türkiye Makro Riski:** `{float(world_state.get('turkey_macro_risk', 0.0)):.2f}`")
        lines.append(f"- **Küresel Risk İştahı:** `{float(world_state.get('global_risk_appetite', 0.0)):.2f}`")
        lines.append("")
        lines.append("## 🎯 En Güçlü Sinyaller")
        if signals:
            lines.append("| Ticker | SPEC Skoru | Kategori | Son Fiyat |")
            lines.append("|---|---|---|---|")
            for s in signals[:10]:
                lines.append(f"| **{s.get('ticker', '')}** | {s.get('spec_score', 0):.0f} | `{s.get('spec_category', '')}` | ₺{float(s.get('price', 0.0)):.2f} |")
        else:
            lines.append("_Bugün eşik değerleri aşan yüksek inançlı sinyal oluşmadı._")
        lines.append("")
        if trade_plans:
            lines.append("## 💼 İşlem Planları")
            lines.append("| Ticker | Karar | Giriş | Hedef | Stop | R/R |")
            lines.append("|---|---|---|---|---|---|")
            for p in trade_plans:
                lines.append(f"| **{p.get('ticker', '')}** | `{p.get('action', '')}` | ₺{float(p.get('entry', 0)):.2f} | ₺{float(p.get('target', 0)):.2f} | ₺{float(p.get('stop', 0)):.2f} | {float(p.get('risk_reward', 0)):.1f} |")
            lines.append("")
        if portfolio:
            lines.append("## 💰 Portföy Durumu")
            lines.append(f"- **Toplam Sermaye:** ₺{float(portfolio.get('capital', 0)):,.0f}")
            lines.append(f"- **Yatırılan Sermaye:** ₺{float(portfolio.get('invested', 0)):,.0f}")
            lines.append(f"- **Serbest Nakit:** ₺{float(portfolio.get('cash', 0)):,.0f}")
            lines.append(f"- **Günlük Net K/Z:** ₺{float(portfolio.get('pnl', 0)):,.0f} (%{float(portfolio.get('pnl_pct', 0)):.2f})")
            lines.append("")
        lines.append("---")
        lines.append(f"*Toplam Taranan: {len(signals)} | Aktif Plan: {len(trade_plans)} | Anomali: {len(anomalies)}*")
        return "\n".join(lines)

    # Standart metin çıktısı
    lines.append("=" * 60)
    lines.append("ALPHA BIST — GÜNLÜK RAPOR")
    lines.append(f"Tarih: {date}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("📊 PİYASA DURUMU")
    lines.append(f"   Rejim: {market_state.get('regime', 'UNKNOWN')}")
    lines.append(f"   Breadth: {float(market_state.get('breadth_pct', 0)):.1f}%")
    lines.append(f"   Advancing: {market_state.get('advancing', 0)}")
    lines.append(f"   Declining: {market_state.get('declining', 0)}")
    lines.append(f"   Anomalies: {market_state.get('anomaly_count', 0)}")
    lines.append("")
    lines.append("🌍 DÜNYA DURUMU")
    lines.append(f"   VIX: {float(world_state.get('vix_level', 0)):.1f}")
    lines.append(f"   USD Strength: {float(world_state.get('usd_strength', 0)):.2f}")
    lines.append(f"   Turkey Macro: {float(world_state.get('turkey_macro_risk', 0)):.2f}")
    lines.append(f"   Global Risk: {float(world_state.get('global_risk_appetite', 0)):.2f}")
    lines.append("")
    lines.append("🎯 EN GÜÇLÜ SİNYALLER")
    lines.append(f"   {'Ticker':<8} {'SPEC':>5} {'Kategori':<15} {'Fiyat':>10}")
    lines.append(f"   {'-' * 40}")
    for s in signals[:10]:
        lines.append(
            f"   {s.get('ticker', ''):<8} {s.get('spec_score', 0):>5.0f} {s.get('spec_category', ''):<15} ₺{float(s.get('price', 0)):>8.2f}"
        )
    lines.append("")
    if trade_plans:
        lines.append("💼 İŞLEM PLANLARI")
        lines.append(f"   {'Ticker':<8} {'Karar':<6} {'Giriş':>10} {'Hedef':>10} {'Stop':>10} {'R/R':>5}")
        lines.append(f"   {'-' * 50}")
        for p in trade_plans:
            lines.append(
                f"   {p.get('ticker', ''):<8} {p.get('action', ''):<6} ₺{float(p.get('entry', 0)):>8.2f} ₺{float(p.get('target', 0)):>8.2f} ₺{float(p.get('stop', 0)):>8.2f} {float(p.get('risk_reward', 0)):>4.1f}"
            )
        lines.append("")
    if anomalies:
        lines.append("🚨 ANORMAL HACİM")
        for a in anomalies[:10]:
            lines.append(f"   {a.get('ticker', '')}: {float(a.get('score', 0)):.1f}σ — ₺{float(a.get('price', 0)):.2f}")
        lines.append("")
    if portfolio:
        lines.append("💰 PORTFÖY")
        lines.append(f"   Sermaye: ₺{float(portfolio.get('capital', 0)):,.0f}")
        lines.append(f"   Yatırılan: ₺{float(portfolio.get('invested', 0)):,.0f}")
        lines.append(f"   Nakit: ₺{float(portfolio.get('cash', 0)):,.0f}")
        lines.append(f"   P&L: ₺{float(portfolio.get('pnl', 0)):,.0f} ({float(portfolio.get('pnl_pct', 0)):.2f}%)")
        lines.append("")
    lines.append("📋 ÖZET")
    lines.append(f"   Taranan hisse: {len(signals)}")
    lines.append(f"   Üretilen sinyal: {len(signals)}")
    lines.append(f"   Trade planı: {len(trade_plans)}")
    lines.append(f"   Anomali: {len(anomalies)}")
    lines.append("=" * 60)

    return "\n".join(lines)


def generate_alert_message(signal: dict[str, Any]) -> str:
    """Tekil sinyal için anlık bildirim metni üretir.

    Args:
        signal: Sinyal verisi.

    Returns:
        str: Emoji ve önem derecesi içeren anlık mesaj.
    """
    ticker = signal.get("ticker", "")
    score = float(signal.get("spec_score", 0))
    category = signal.get("spec_category", "")
    price = float(signal.get("price", 0))

    if category == "HIGH_CONVICTION":
        return f"🔴 {ticker} — HIGH CONVICTION! SPEC={score:.0f}, Fiyat=₺{price:.2f}"
    elif category == "CANDIDATE":
        return f"🟠 {ticker} — CANDIDATE, SPEC={score:.0f}, Fiyat=₺{price:.2f}"
    elif category == "WATCH":
        return f"🟡 {ticker} — WATCH, SPEC={score:.0f}, Fiyat=₺{price:.2f}"
    return f"⚪ {ticker} — SPEC={score:.0f}, Fiyat=₺{price:.2f}"


def generate_anomaly_alert(anomaly: dict[str, Any]) -> str:
    """Anomali bildirimi üretir.

    Args:
        anomaly: Anomali verisi sözlüğü.

    Returns:
        str: Formatlanmış anomali bildirim metni.
    """
    ticker = anomaly.get("ticker", "")
    score = float(anomaly.get("score", 0))
    price = float(anomaly.get("price", 0))

    return f"🚨 {ticker} — ANORMAL HACİM! {score:.1f}σ, Fiyat=₺{price:.2f}"
