"use client";

import { usePolling, type WorldState } from "@/lib/api";
import {
  Globe, DollarSign, TrendingUp, TrendingDown, Activity, AlertTriangle,
  Flame, BarChart2, ShieldAlert
} from "lucide-react";

export default function WorldIntelPage() {
  const { data: world } = usePolling<any>("/macro/world", 5000);

  const dxyVal = world?.dxy ?? 98.84;
  const dxyChg = world?.dxy_change_pct ?? 0.09;
  const us10yVal = world?.us10y ?? 4.74;
  const us10yChg = world?.us10y_change_pct ?? 0.89;
  const brentVal = world?.brent_crude ?? 93.86;
  const brentChg = world?.brent_change_pct ?? 0.27;
  const goldVal = world?.gold_ounce ?? 4674.60;
  const goldChg = world?.gold_change_pct ?? 1.82;
  const cdsVal = world?.turkey_cds_5y ?? 268;
  const cdsChg = world?.cds_change_pct ?? -0.85;
  const usdTryVal = world?.usd_try ?? 48.05;
  const usdTryChg = world?.usd_try_change_pct ?? 0.02;

  const MACRO_ASSETS = [
    {
      name: "Dolar Endeksi (DXY)",
      value: `${Number(dxyVal).toFixed(2)}`,
      change: `${dxyChg >= 0 ? "+" : ""}%${Number(dxyChg).toFixed(2)}`,
      pos: dxyChg >= 0
    },
    {
      name: "ABD 10 Yıllık Tahvil",
      value: `%${Number(us10yVal).toFixed(2)}`,
      change: `${us10yChg >= 0 ? "+" : ""}%${Number(us10yChg).toFixed(2)}`,
      pos: us10yChg >= 0
    },
    {
      name: "Brent Petrol",
      value: `$${Number(brentVal).toFixed(2)}`,
      change: `${brentChg >= 0 ? "+" : ""}%${Number(brentChg).toFixed(2)}`,
      pos: brentChg >= 0
    },
    {
      name: "Ons Altın (XAU/USD)",
      value: `$${Number(goldVal).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`,
      change: `${goldChg >= 0 ? "+" : ""}%${Number(goldChg).toFixed(2)}`,
      pos: goldChg >= 0
    },
    {
      name: "Türkiye 5Y CDS Primi",
      value: `${Number(cdsVal).toFixed(0)} bps`,
      change: `${cdsChg >= 0 ? "+" : ""}%${Number(cdsChg).toFixed(2)}`,
      pos: cdsChg <= 0
    },
    {
      name: "USD / TRY",
      value: `₺${Number(usdTryVal).toFixed(2)}`,
      change: `${usdTryChg >= 0 ? "+" : ""}%${Number(usdTryChg).toFixed(2)}`,
      pos: usdTryChg >= 0
    },
  ];

  const riskAppetite = (world?.global_risk_appetite ?? 0.68) * 100;
  const emAppetite = (world?.em_risk_appetite ?? 0.62) * 100;
  const geoRisk = (world?.geopolitical_risk ?? 0.44) * 100;
  const inflPressure = (world?.inflation_pressure ?? 0.41) * 100;
  const usRatePressure = (world?.us_rate_pressure ?? 0.55) * 100;

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Küresel Makro İstihbarat</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            DXY · VIX ({world?.vix_level ?? 15.14}) · Ons Altın · Brent Petrol · Türkiye 5Y CDS · USD/TRY Canlı Piyasa
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-zinc-500 font-data">
            Son Güncelleme: {world?.updated_at ?? "Canlı"}
          </span>
        </div>
      </div>

      {/* Global Assets Ticker Cards */}
      <div className="grid grid-cols-6 gap-3">
        {MACRO_ASSETS.map((item) => (
          <div
            key={item.name}
            className="rounded-xl p-4 space-y-1.5 select-none"
            style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
          >
            <p className="text-[9px] uppercase tracking-wider text-zinc-500 font-medium truncate">{item.name}</p>
            <p className="text-xl font-bold font-data text-zinc-100">{item.value}</p>
            <span className={`text-[10px] font-bold font-data ${item.pos ? "text-emerald-400" : "text-red-400"}`}>
              {item.change}
            </span>
          </div>
        ))}
      </div>

      {/* Risk Metrics Section */}
      <div className="grid grid-cols-2 gap-4">
        {/* Risk Gauges */}
        <div
          className="rounded-xl p-5 space-y-4"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5 pb-3 border-b border-zinc-800/40">
            <ShieldAlert size={14} className="text-amber-400" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-200">
              Küresel Risk & Likidite İndikatörleri
            </h2>
          </div>

          <div className="space-y-4">
            {[
              { label: "Küresel Risk İştahı (VIX Bazlı)", value: riskAppetite, isGood: true },
              { label: "Gelişmekte Olan Ülkeler (EM) Sermaye Akışı", value: emAppetite, isGood: true },
              { label: "Jeopolitik Gerilim & Emtia Baskısı", value: geoRisk, isGood: false },
              { label: "Küresel Enflasyon Baskısı", value: inflPressure, isGood: false },
              { label: "ABD Faiz & Tahvil Sıkılığı", value: usRatePressure, isGood: false },
            ].map((m) => {
              const color = m.isGood 
                ? (m.value > 50 ? "#00e5a0" : "#ffaa00") 
                : (m.value > 50 ? "#ff4466" : "#00e5a0");
              return (
                <div key={m.label} className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs font-data">
                    <span className="text-zinc-400">{m.label}</span>
                    <span className="font-bold" style={{ color }}>%{m.value.toFixed(0)}</span>
                  </div>
                  <div className="h-1.5 rounded-full overflow-hidden bg-zinc-800">
                    <div className="h-full rounded-full transition-all duration-700" style={{ width: `${m.value}%`, background: color }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Global Impact Summary */}
        <div
          className="rounded-xl p-5 space-y-4"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5 pb-3 border-b border-zinc-800/40">
            <Globe size={14} className="text-cyan-400" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-200">
              BIST Üzerindeki Küresel Etki Değerlendirmesi
            </h2>
          </div>

          <div className="space-y-3 text-xs leading-relaxed text-zinc-300">
            <div className="p-3 rounded-lg bg-zinc-900/60 border border-zinc-800/40">
              <h4 className="font-bold text-emerald-400 mb-1">Pozitif Katalizörler:</h4>
              <p className="text-zinc-400">
                VIX oynaklık endeksinin ({world?.vix_level ?? 15.14}) sakin seyretmesi ve Türkiye CDS priminin ({Number(cdsVal).toFixed(0)} bps) dengelenmesi BIST hisselerine olan yabancı risk iştahını destekliyor.
              </p>
            </div>
            <div className="p-3 rounded-lg bg-zinc-900/60 border border-zinc-800/40">
              <h4 className="font-bold text-amber-400 mb-1">Risk Faktörleri:</h4>
              <p className="text-zinc-400">
                ABD 10 Yıllık Tahvil faizinin (%{Number(us10yVal).toFixed(2)}) ve Brent petrolün (${Number(brentVal).toFixed(2)}) seyri sanayi ve ulaştırma marjları açısından takip ediliyor.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
