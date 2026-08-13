"use client";

import { useEffect, useState } from "react";

interface WorldState {
  global_risk_appetite: number;
  usd_strength: number;
  us_rate_pressure: number;
  commodity_pressure: number;
  oil_pressure: number;
  turkey_macro_risk: number;
  geopolitical_risk: number;
  em_risk_appetite: number;
  vix_level: number;
  inflation_pressure: number;
  timestamp: string;
}

export default function WorldIntelligence() {
  const [worldState, setWorldState] = useState<WorldState | null>(null);

  useEffect(() => {
    async function fetchWorldState() {
      try {
        const res = await fetch("/api/world/state");
        if (res.ok) setWorldState(await res.json());
      } catch {}
    }
    fetchWorldState();
    const interval = setInterval(fetchWorldState, 30000);
    return () => clearInterval(interval);
  }, []);

  const factors = worldState ? [
    { label: "Global Risk Appetite", value: worldState.global_risk_appetite, invert: false },
    { label: "USD Strength", value: worldState.usd_strength, invert: false },
    { label: "US Rate Pressure", value: worldState.us_rate_pressure, invert: true },
    { label: "Commodity Pressure", value: worldState.commodity_pressure, invert: true },
    { label: "Oil Pressure", value: worldState.oil_pressure, invert: true },
    { label: "Turkey Macro Risk", value: worldState.turkey_macro_risk, invert: true },
    { label: "Geopolitical Risk", value: worldState.geopolitical_risk, invert: true },
    { label: "EM Risk Appetite", value: worldState.em_risk_appetite, invert: false },
    { label: "Inflation Pressure", value: worldState.inflation_pressure, invert: true },
  ] : [];

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-2">World Intelligence</h1>
      <p className="text-sm text-alpha-muted mb-6">
        Global macro state — event-driven, zaman içinde değişen latent faktörler
      </p>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <p className="text-xs text-alpha-muted uppercase">VIX Level</p>
          <p className={`text-2xl font-bold mt-1 ${(worldState?.vix_level || 0) > 25 ? "text-alpha-danger" : "text-alpha-accent"}`}>
            {worldState?.vix_level?.toFixed(1) || "—"}
          </p>
        </div>
        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <p className="text-xs text-alpha-muted uppercase">Global Risk</p>
          <p className="text-2xl font-bold mt-1">
            {worldState ? (worldState.global_risk_appetite * 100).toFixed(0) : "—"}%
          </p>
        </div>
        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <p className="text-xs text-alpha-muted uppercase">Turkey Macro</p>
          <p className={`text-2xl font-bold mt-1 ${(worldState?.turkey_macro_risk || 0) > 0.6 ? "text-alpha-warning" : "text-alpha-text"}`}>
            {worldState ? (worldState.turkey_macro_risk * 100).toFixed(0) : "—"}%
          </p>
        </div>
      </div>

      <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
        <h2 className="text-sm font-semibold mb-4">Latent Factors</h2>
        <div className="space-y-3">
          {factors.map(f => (
            <div key={f.label}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-alpha-muted">{f.label}</span>
                <span className="text-sm font-mono">{(f.value * 100).toFixed(0)}%</span>
              </div>
              <div className="w-full bg-alpha-border rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all ${
                    f.invert
                      ? f.value > 0.7 ? "bg-alpha-danger" : f.value > 0.4 ? "bg-alpha-warning" : "bg-alpha-accent"
                      : f.value > 0.6 ? "bg-alpha-accent" : f.value > 0.3 ? "bg-alpha-warning" : "bg-alpha-danger"
                  }`}
                  style={{ width: `${f.value * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 bg-alpha-surface border border-alpha-border rounded-lg p-4">
        <h2 className="text-sm font-semibold mb-2">Propagation Chain</h2>
        <p className="text-xs text-alpha-muted">
          Son olay → World State değişimi → BIST etkisi → Sektör etkisi → Hisse etkisi
        </p>
        <div className="mt-3 text-sm font-mono text-alpha-muted">
          FED_RATE_HIKE → USD +0.20 → EM_RISK -0.20 → BIST_BANK -0.56 → AKBNK/GARAN/YKBNK
        </div>
      </div>
    </div>
  );
}
