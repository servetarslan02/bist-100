"use client";

import { usePolling, type WorldState } from "@/lib/api";
import {
  Globe, DollarSign, TrendingUp, TrendingDown, Activity, AlertTriangle,
  Flame, BarChart2, ShieldAlert
} from "lucide-react";

export default function WorldIntelPage() {
  const { data: world } = usePolling<WorldState>("/world/state", 5000);

  const MACRO_ASSETS = [
    {
      name: "Dolar Endeksi (DXY)",
      value: (world as any)?.dxy ? `${(world as any).dxy.toFixed(2)}` : "103.85",
      change: `${((world as any)?.dxy_change_pct ?? 0.35) >= 0 ? "+" : ""}%${((world as any)?.dxy_change_pct ?? 0.35).toFixed(2)}`,
      pos: ((world as any)?.dxy_change_pct ?? 0.35) >= 0
    },
    {
      name: "ABD 10 Yıllık Tahvil",
      value: (world as any)?.us10y ? `%${(world as any).us10y.toFixed(2)}` : "%4.28",
      change: "-2 bps",
      pos: false
    },
    {
      name: "Brent Petrol",
      value: (world as any)?.brent_crude ? `$${(world as any).brent_crude.toFixed(2)}` : "$82.40",
      change: "-%1.10",
      pos: false
    },
    {
      name: "Ons Altın (XAU/USD)",
      value: (world as any)?.gold_ounce ? `$${(world as any).gold_ounce.toLocaleString("en-US")}` : "$2,485",
      change: "+%0.65",
      pos: true
    },
    {
      name: "Türkiye 5Y CDS Primi",
      value: (world as any)?.turkey_cds_5y ? `${(world as any).turkey_cds_5y.toFixed(0)} bps` : "264 bps",
      change: "-4 bps",
      pos: false
    },
    {
      name: "USD / TRY",
      value: (world as any)?.usd_try ? `₺${(world as any).usd_try.toFixed(2)}` : "₺33.85",
      change: "+%0.12",
      pos: true
    },
  ];

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Küresel Makro İstihbarat</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            DXY · VIX · Emtia Fiyat Baskısı · CDS & Türkiye Risk Primi · Küresel Risk İştahı
          </p>
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
              { label: "Küresel Risk İştahı", value: (world?.global_risk_appetite ?? 0.65) * 100, isGood: true },
              { label: "Gelişmekte Olan Ülkeler (EM) Sermaye Akışı", value: (world?.em_risk_appetite ?? 0.58) * 100, isGood: true },
              { label: "Jeopolitik Gerilim Baskısı", value: (world?.geopolitical_risk ?? 0.42) * 100, isGood: false },
              { label: "Küresel Enflasyon Baskısı", value: (world?.inflation_pressure ?? 0.38) * 100, isGood: false },
              { label: "ABD Faiz & Likidite Sıkılığı", value: (world?.us_rate_pressure ?? 0.52) * 100, isGood: false },
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
              <p className="text-zinc-400">Türkiye CDS priminin 260 bps bandına gerilemesi ve yabancı tahvil girişlerindeki artış BIST bankacılık ve holding hisselerine pozitif yansıyor.</p>
            </div>
            <div className="p-3 rounded-lg bg-zinc-900/60 border border-zinc-800/40">
              <h4 className="font-bold text-amber-400 mb-1">Risk Faktörleri:</h4>
              <p className="text-zinc-400">Dolar endeksindeki güçlenme (DXY &gt; 103.5) gelişmekte olan piyasalara para giriş hızını sınırlıyor.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
