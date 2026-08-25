"""
ALPHA BIST — Günlük Rapor Üretici

Her gün piyasa kapandıktan sonra otomatik rapor üretir.
"""

from typing import Dict, List
import structlog

logger = structlog.get_logger()


def generate_daily_report(
    date: str,
    market_state: Dict,
    signals: List[Dict],
    trade_plans: List[Dict],
    anomalies: List[Dict],
    portfolio: Dict,
    world_state: Dict,
) -> str:
    """Günlük rapor üret."""

    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"ALPHA BIST — GÜNLÜK RAPOR")
    lines.append(f"Tarih: {date}")
    lines.append(f"{'='*60}")
    lines.append("")

    # Piyasa Durumu
    lines.append("📊 PİYASA DURUMU")
    lines.append(f"   Rejim: {market_state.get('regime', 'UNKNOWN')}")
    lines.append(f"   Breadth: {market_state.get('breadth_pct', 0):.1f}%")
    lines.append(f"   Advancing: {market_state.get('advancing', 0)}")
    lines.append(f"   Declining: {market_state.get('declining', 0)}")
    lines.append(f"   Anomalies: {market_state.get('anomaly_count', 0)}")
    lines.append("")

    # Dünya Durumu
    lines.append("🌍 DÜNYA DURUMU")
    lines.append(f"   VIX: {world_state.get('vix_level', 0):.1f}")
    lines.append(f"   USD Strength: {world_state.get('usd_strength', 0):.2f}")
    lines.append(f"   Turkey Macro: {world_state.get('turkey_macro_risk', 0):.2f}")
    lines.append(f"   Global Risk: {world_state.get('global_risk_appetite', 0):.2f}")
    lines.append("")

    # En Güçlü Sinyaller
    lines.append("🎯 EN GÜÇLÜ SİNYALLER")
    lines.append(f"   {'Ticker':<8} {'SPEC':>5} {'Kategori':<15} {'Fiyat':>10}")
    lines.append(f"   {'-'*40}")
    for s in signals[:10]:
        lines.append(f"   {s.get('ticker',''):<8} {s.get('spec_score',0):>5.0f} {s.get('spec_category',''):<15} ₺{s.get('price',0):>8.2f}")
    lines.append("")

    # Trade Planları
    if trade_plans:
        lines.append("💼 İŞLEM PLANLARI")
        lines.append(f"   {'Ticker':<8} {'Karar':<6} {'Giriş':>10} {'Hedef':>10} {'Stop':>10} {'R/R':>5}")
        lines.append(f"   {'-'*50}")
        for p in trade_plans:
            lines.append(f"   {p.get('ticker',''):<8} {p.get('action',''):<6} ₺{p.get('entry',0):>8.2f} ₺{p.get('target',0):>8.2f} ₺{p.get('stop',0):>8.2f} {p.get('risk_reward',0):>4.1f}")
        lines.append("")

    # Anomaliler
    if anomalies:
        lines.append("🚨 ANORMAL HACİM")
        for a in anomalies[:10]:
            lines.append(f"   {a.get('ticker','')}: {a.get('score',0):.1f}σ — ₺{a.get('price',0):.2f}")
        lines.append("")

    # Portföy
    if portfolio:
        lines.append("💰 PORTFÖY")
        lines.append(f"   Sermaye: ₺{portfolio.get('capital',0):,.0f}")
        lines.append(f"   Yatırılan: ₺{portfolio.get('invested',0):,.0f}")
        lines.append(f"   Nakit: ₺{portfolio.get('cash',0):,.0f}")
        lines.append(f"   P&L: ₺{portfolio.get('pnl',0):,.0f} ({portfolio.get('pnl_pct',0):.2f}%)")
        lines.append("")

    # Özet
    lines.append("📋 ÖZET")
    lines.append(f"   Taranan hisse: {len(signals)}")
    lines.append(f"   Üretilen sinyal: {len(signals)}")
    lines.append(f"   Trade planı: {len(trade_plans)}")
    lines.append(f"   Anomali: {len(anomalies)}")
    lines.append(f"{'='*60}")

    return "\n".join(lines)


def generate_alert_message(signal: Dict) -> str:
    """Sinyal bildirimi üret."""
    ticker = signal.get("ticker", "")
    score = signal.get("spec_score", 0)
    category = signal.get("spec_category", "")
    price = signal.get("price", 0)

    if category == "HIGH_CONVICTION":
        return f"🔴 {ticker} — HIGH CONVICTION! SPEC={score:.0f}, Fiyat=₺{price:.2f}"
    elif category == "CANDIDATE":
        return f"🟠 {ticker} — CANDIDATE, SPEC={score:.0f}, Fiyat=₺{price:.2f}"
    elif category == "WATCH":
        return f"🟡 {ticker} — WATCH, SPEC={score:.0f}, Fiyat=₺{price:.2f}"
    else:
        return f"⚪ {ticker} — SPEC={score:.0f}, Fiyat=₺{price:.2f}"


def generate_anomaly_alert(anomaly: Dict) -> str:
    """Anomali bildirimi üret."""
    ticker = anomaly.get("ticker", "")
    score = anomaly.get("score", 0)
    price = anomaly.get("price", 0)

    return f"🚨 {ticker} — ANORMAL HACİM! {score:.1f}σ, Fiyat=₺{price:.2f}"
