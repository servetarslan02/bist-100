"use client";

import { useEffect, useState } from "react";

interface AssetData {
  instrument: { symbol: string; name: string; sector: string };
  features: Record<string, string>;
}

export default function AssetIntelligence() {
  const [ticker, setTicker] = useState("THYAO");
  const [data, setData] = useState<AssetData | null>(null);
  const [loading, setLoading] = useState(false);

  async function fetchAsset(t: string) {
    setLoading(true);
    try {
      const res = await fetch(`/api/market/instrument/${t}`);
      if (res.ok) setData(await res.json());
    } catch {}
    setLoading(false);
  }

  useEffect(() => { fetchAsset(ticker); }, [ticker]);

  const f = data?.features || {};

  return (
    <div className="p-6">
      <div className="flex items-center gap-4 mb-6">
        <h1 className="text-2xl font-bold">Asset Intelligence</h1>
        <input
          type="text"
          value={ticker}
          onChange={e => setTicker(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === "Enter" && fetchAsset(ticker)}
          className="bg-alpha-bg border border-alpha-border rounded px-3 py-1.5 text-sm font-mono w-32 focus:outline-none focus:border-alpha-accent"
          placeholder="Ticker..."
        />
      </div>

      {loading ? (
        <div className="text-alpha-muted text-center py-8">Loading...</div>
      ) : !data ? (
        <div className="text-alpha-muted text-center py-8">Enter a ticker</div>
      ) : (
        <div className="space-y-4">
          <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
            <h2 className="text-lg font-bold text-alpha-accent">{data.instrument.symbol}</h2>
            <p className="text-sm text-alpha-muted">{data.instrument.name} • {data.instrument.sector}</p>
          </div>

          <div className="grid grid-cols-4 gap-4">
            <StatCard label="RSI" value={f.rsi_14} format="1" />
            <StatCard label="MOM 5D" value={f.momentum_5d} format="pct" />
            <StatCard label="MOM 20D" value={f.momentum_20d} format="pct" />
            <StatCard label="Vol Z" value={f.volume_zscore} format="2" />
            <StatCard label="ATR 14" value={f.atr_14_pct} format="pct" />
            <StatCard label="BB Position" value={f.bb_position} format="2" />
            <StatCard label="MACD" value={f.macd} format="2" />
            <StatCard label="ADX" value={f.adx} format="1" />
          </div>

          <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Edge Decomposition</h3>
            <div className="space-y-2 text-sm">
              <EdgeRow label="Volume Anomaly" value={f.volume_zscore} threshold={2.0} />
              <EdgeRow label="Price Momentum" value={f.roc_5d} threshold={2.0} />
              <EdgeRow label="Trend Strength" value={f.adx} threshold={25} />
              <EdgeRow label="Volatility" value={f.volatility_ratio} threshold={1.5} />
              <EdgeRow label="RSI Extreme" value={f.rsi_14} threshold={70} />
            </div>
          </div>

          <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">WHY?</h3>
            <p className="text-sm text-alpha-muted">
              Bu varlığın mevcut durumu: {
                parseFloat(f.rsi_14 || "50") > 70 ? "Aşırı alım bölgesinde, dikkatli olunmalı." :
                parseFloat(f.rsi_14 || "50") < 30 ? "Aşırı satım bölgesinde, potansiyel toparlanma." :
                parseFloat(f.momentum_5d || "0") > 3 ? "Güçlü kısa vadeli momentum." :
                parseFloat(f.momentum_5d || "0") < -3 ? "Zayıf kısa vadeli momentum." :
                "Normal seviyelerde."
              }
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, format }: { label: string; value?: string; format: string }) {
  const num = parseFloat(value || "0");
  let display = value || "—";
  let color = "text-alpha-text";

  if (format === "pct") {
    display = `${num > 0 ? "+" : ""}${num.toFixed(2)}%`;
    color = num > 0 ? "text-alpha-accent" : num < 0 ? "text-alpha-danger" : "text-alpha-text";
  } else if (format === "1") {
    display = num.toFixed(1);
  } else if (format === "2") {
    display = num.toFixed(2);
  }

  return (
    <div className="bg-alpha-surface border border-alpha-border rounded-lg p-3">
      <p className="text-xs text-alpha-muted uppercase">{label}</p>
      <p className={`text-lg font-bold mt-1 font-mono ${color}`}>{display}</p>
    </div>
  );
}

function EdgeRow({ label, value, threshold }: { label: string; value?: string; threshold: number }) {
  const num = parseFloat(value || "0");
  const active = Math.abs(num) > threshold;

  return (
    <div className="flex items-center justify-between">
      <span className={active ? "text-alpha-accent" : "text-alpha-muted"}>
        {active ? "●" : "○"} {label}
      </span>
      <span className="font-mono">{num.toFixed(2)}</span>
    </div>
  );
}
