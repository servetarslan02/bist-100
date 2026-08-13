"use client";

import { useState, useCallback, useEffect } from "react";
import { StatCard } from "@/components/ui/StatCard";

interface AssetData {
  ticker: string;
  price: number;
  candles: Array<{ time: number; open: number; high: number; low: number; close: number; volume: number }>;
  features: Record<string, number>;
  spec: {
    score: number;
    category: string;
    anomaly: number;
    evidence: number;
    regime: number;
  };
}

export default function AssetIntelligence() {
  const [ticker, setTicker] = useState("THYAO");
  const [inputValue, setInputValue] = useState("THYAO");
  const [data, setData] = useState<AssetData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchAsset = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/market/instrument/${t}/full`);
      if (res.ok) setData(await res.json());
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { fetchAsset(ticker); }, [ticker, fetchAsset]);

  const f = data?.features || {};
  const spec = data?.spec;
  const rsi = f.rsi_14 || 50;
  const macd = f.macd || 0;
  const mom5 = f.roc_5d || 0;
  const mom20 = f.momentum_20d || 0;
  const volZ = f.volume_zscore || 0;
  const bbPos = f.bb_position || 0.5;
  const atrPct = f.atr_14_pct || 0;

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-4">
        <h1 className="text-lg font-semibold text-zinc-100">Asset Intelligence</h1>
        <div className="flex items-center gap-1">
          <input
            type="text"
            value={inputValue}
            onChange={e => setInputValue(e.target.value.toUpperCase())}
            onKeyDown={e => e.key === "Enter" && setTicker(inputValue)}
            className="bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1 text-xs font-mono text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600 w-28"
            placeholder="Ticker..."
          />
          <button
            onClick={() => setTicker(inputValue)}
            className="bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded px-3 py-1 text-xs text-zinc-300 transition-colors"
          >
            →
          </button>
        </div>
        {data && (
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-sm font-semibold text-zinc-200">{data.ticker}</span>
            <span className="text-lg font-mono font-bold text-zinc-100">₺{data.price?.toFixed(2)}</span>
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-5 h-5 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
        </div>
      ) : !data ? (
        <div className="text-center py-20 text-zinc-600">Enter a ticker</div>
      ) : (
        <>
          {/* Price Chart */}
          <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <span className="text-lg font-bold text-zinc-100">{data.ticker}</span>
                <span className="text-xl font-mono font-bold text-zinc-100">₺{data.price?.toFixed(2)}</span>
                {data.candles.length > 1 && (
                  <span className={`text-sm font-mono ${
                    data.price > data.candles[data.candles.length - 2]?.close ? "text-emerald-400" : "text-red-400"
                  }`}>
                    {((data.price / data.candles[data.candles.length - 2]?.close - 1) * 100).toFixed(2)}%
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded ${
                  spec?.category === "HIGH_CONVICTION" ? "bg-red-950 text-red-400" :
                  spec?.category === "CANDIDATE" ? "bg-amber-950 text-amber-400" :
                  spec?.category === "WATCH" ? "bg-zinc-800 text-zinc-400" :
                  "bg-zinc-900 text-zinc-600"
                }`}>
                  SPEC {spec?.score?.toFixed(0) || "—"}
                </span>
              </div>
            </div>

            {/* SVG Chart */}
            <Chart candles={data.candles} />
          </div>

          {/* Metric Grid */}
          <div className="grid grid-cols-6 gap-3">
            <StatCard label="RSI 14" value={rsi} decimals={1} color={rsi > 70 ? "red" : rsi < 30 ? "green" : "neutral"} size="sm" />
            <StatCard label="MACD" value={macd} decimals={2} color={macd > 0 ? "green" : "red"} size="sm" />
            <StatCard label="MOM 5D" value={mom5} decimals={2} suffix="%" color="auto" size="sm" />
            <StatCard label="MOM 20D" value={mom20} decimals={2} suffix="%" color="auto" size="sm" />
            <StatCard label="VOL Z" value={volZ} decimals={2} color={volZ > 2 ? "red" : "neutral"} size="sm" />
            <StatCard label="ATR%" value={atrPct} decimals={2} suffix="%" size="sm" />
          </div>

          {/* Edge Decomposition + WHY */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
              <h3 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Edge Decomposition</h3>
              <div className="space-y-2">
                {[
                  { label: "Volume Anomaly", value: volZ, threshold: 2.0, max: 5 },
                  { label: "Price Momentum", value: mom5, threshold: 2.0, max: 10 },
                  { label: "BB Position", value: bbPos, threshold: 0.9, max: 1 },
                  { label: "RSI Extreme", value: Math.abs(rsi - 50), threshold: 20, max: 50 },
                  { label: "Trend Strength", value: f.adx || 0, threshold: 25, max: 50 },
                ].map(item => {
                  const active = Math.abs(item.value) > item.threshold;
                  const pct = Math.min(Math.abs(item.value) / item.max * 100, 100);
                  return (
                    <div key={item.label}>
                      <div className="flex items-center justify-between mb-0.5">
                        <span className={`text-[11px] ${active ? "text-emerald-400" : "text-zinc-500"}`}>
                          {active ? "●" : "○"} {item.label}
                        </span>
                        <span className="text-[10px] font-mono text-zinc-400">{item.value.toFixed(2)}</span>
                      </div>
                      <div className="w-full h-1 bg-zinc-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${active ? "bg-emerald-500" : "bg-zinc-700"}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
              <h3 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">WHY?</h3>
              <div className="text-[12px] text-zinc-400 leading-relaxed">
                {rsi > 70 ? (
                  <p><span className="text-red-400 font-medium">Aşırı alım bölgesinde.</span> RSI {rsi.toFixed(0)}. {mom5 > 3 ? "Güçlü momentum var ama geri çekilme riski artıyor." : ""}</p>
                ) : rsi < 30 ? (
                  <p><span className="text-emerald-400 font-medium">Aşırı satım bölgesinde.</span> RSI {rsi.toFixed(0)}. Potansiyel toparlanma alanı.</p>
                ) : mom5 > 3 ? (
                  <p><span className="text-emerald-400 font-medium">Güçlü momentum.</span> Son 5 günde %{mom5.toFixed(1)} yükseliş. {volZ > 1.5 ? "Hacim desteği var." : ""}</p>
                ) : mom5 < -3 ? (
                  <p><span className="text-red-400 font-medium">Zayıf momentum.</span> Son 5 günde %{Math.abs(mom5).toFixed(1)} düşüş.</p>
                ) : (
                  <p><span className="text-zinc-400">Normal seviyelerde.</span> Belirgin sinyal yok.</p>
                )}
              </div>

              <div className="mt-3 pt-2 border-t border-zinc-800/60">
                <h4 className="text-[9px] uppercase tracking-wider text-zinc-600 mb-1.5">Key Metrics</h4>
                <div className="grid grid-cols-2 gap-1 text-[10px]">
                  <div className="flex justify-between"><span className="text-zinc-600">BB Position</span><span className="font-mono text-zinc-400">{bbPos.toFixed(2)}</span></div>
                  <div className="flex justify-between"><span className="text-zinc-600">Vol Z-Score</span><span className="font-mono text-zinc-400">{volZ.toFixed(2)}</span></div>
                  <div className="flex justify-between"><span className="text-zinc-600">ATR%</span><span className="font-mono text-zinc-400">{atrPct.toFixed(2)}%</span></div>
                  <div className="flex justify-between"><span className="text-zinc-600">MACD</span><span className="font-mono text-zinc-400">{macd.toFixed(2)}</span></div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// =====================================================
// SVG Candlestick Chart
// =====================================================

function Chart({ candles }: { candles: Array<{ time: number; open: number; high: number; low: number; close: number }> }) {
  if (!candles || candles.length < 2) return <div className="h-[250px] flex items-center justify-center text-zinc-600">No chart data</div>;

  const width = 800;
  const height = 250;
  const padding = { top: 10, right: 10, bottom: 20, left: 60 };

  const prices = candles.flatMap(c => [c.high, c.low]);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const priceRange = maxPrice - minPrice || 1;

  const candleWidth = Math.max(2, (width - padding.left - padding.right) / candles.length - 1);

  const scaleY = (price: number) => {
    return padding.top + (1 - (price - minPrice) / priceRange) * (height - padding.top - padding.bottom);
  };

  const scaleX = (index: number) => {
    return padding.left + index * ((width - padding.left - padding.right) / candles.length) + candleWidth / 2;
  };

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="bg-zinc-950/50 rounded">
      {/* Grid lines */}
      {[0.25, 0.5, 0.75].map(pct => {
        const price = minPrice + priceRange * pct;
        const y = scaleY(price);
        return (
          <g key={pct}>
            <line x1={padding.left} y1={y} x2={width - padding.right} y2={y} stroke="rgba(255,255,255,0.03)" strokeWidth={1} />
            <text x={padding.left - 5} y={y + 3} textAnchor="end" fill="#52525b" fontSize={9} fontFamily="monospace">
              {price.toFixed(1)}
            </text>
          </g>
        );
      })}

      {/* Candles */}
      {candles.map((c, i) => {
        const x = scaleX(i);
        const isGreen = c.close >= c.open;
        const color = isGreen ? "#10b981" : "#ef4444";
        const bodyTop = scaleY(Math.max(c.open, c.close));
        const bodyBottom = scaleY(Math.min(c.open, c.close));
        const bodyHeight = Math.max(1, bodyBottom - bodyTop);

        return (
          <g key={i}>
            {/* Wick */}
            <line x1={x} y1={scaleY(c.high)} x2={x} y2={scaleY(c.low)} stroke={color} strokeWidth={1} />
            {/* Body */}
            <rect
              x={x - candleWidth / 2}
              y={bodyTop}
              width={candleWidth}
              height={bodyHeight}
              fill={isGreen ? color : color}
              stroke={color}
              strokeWidth={0.5}
            />
          </g>
        );
      })}
    </svg>
  );
}
