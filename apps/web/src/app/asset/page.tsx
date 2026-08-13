"use client";

import { useState, useCallback } from "react";
import { usePolling, type AssetData } from "@/lib/api";
import { StatCard } from "@/components/ui/StatCard";
import dynamic from "next/dynamic";

const LiveChart = dynamic(
  () => import("@/components/charts/LiveChart").then(m => m.LiveChart),
  { ssr: false }
);

export default function AssetIntelligence() {
  const [ticker, setTicker] = useState("THYAO");
  const [inputValue, setInputValue] = useState("THYAO");
  const { data, loading, refetch } = usePolling<AssetData>(
    `/market/instrument/${ticker}`,
    30000
  );

  const handleSearch = useCallback(() => {
    setTicker(inputValue.toUpperCase());
  }, [inputValue]);

  const f = data?.features || {};
  const rsi = parseFloat(f.rsi_14 || "50");
  const macd = parseFloat(f.macd || "0");
  const mom5 = parseFloat(f.momentum_5d || "0");
  const mom20 = parseFloat(f.momentum_20d || "0");
  const volZ = parseFloat(f.volume_zscore || "0");
  const bbPos = parseFloat(f.bb_position || "0.5");
  const atrPct = parseFloat(f.atr_14_pct || "0");

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
            onKeyDown={e => e.key === "Enter" && handleSearch()}
            className="bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1 text-xs font-mono text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600 w-28"
            placeholder="Ticker..."
          />
          <button
            onClick={handleSearch}
            className="bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded px-3 py-1 text-xs text-zinc-300 transition-colors"
          >
            →
          </button>
        </div>
        {data && (
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-sm font-semibold text-zinc-200">{data.instrument.symbol}</span>
            <span className="text-[11px] text-zinc-500">{data.instrument.name}</span>
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">
              {data.instrument.sector}
            </span>
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-5 h-5 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
        </div>
      ) : !data ? (
        <div className="text-center py-20 text-zinc-600">Enter a ticker to analyze</div>
      ) : (
        <>
          {/* Price Chart Placeholder */}
          <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <span className="text-xl font-semibold text-zinc-100">{data.instrument.symbol}</span>
                <span className="text-sm text-zinc-500 ml-2">{data.instrument.name}</span>
              </div>
              <div className="text-right">
                <div className="text-sm text-zinc-500">Last Price</div>
                <div className="text-lg font-mono text-zinc-200">₺{parseFloat(f.price || "0").toFixed(2)}</div>
              </div>
            </div>
            <LiveChart ticker={ticker} height={250} />
          </div>

          {/* Metric Grid */}
          <div className="grid grid-cols-6 gap-3">
            <StatCard label="RSI 14" value={rsi} decimals={1} color={rsi > 70 ? "red" : rsi < 30 ? "green" : "neutral"} size="sm" />
            <StatCard label="MACD" value={macd} decimals={2} color={macd > 0 ? "green" : "red"} size="sm" />
            <StatCard label="MOM 5D" value={mom5} decimals={2} suffix="%" color="auto" size="sm" />
            <StatCard label="MOM 20D" value={mom20} decimals={2} suffix="%" color="auto" size="sm" />
            <StatCard label="VOL Z-SCORE" value={volZ} decimals={2} color={volZ > 2 ? "red" : "neutral"} size="sm" />
            <StatCard label="ATR%" value={atrPct} decimals={2} suffix="%" size="sm" />
          </div>

          {/* Edge Decomposition */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
              <h3 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Edge Decomposition</h3>
              <div className="space-y-2">
                {[
                  { label: "Volume Anomaly", value: volZ, threshold: 2.0, max: 5 },
                  { label: "Price Momentum", value: mom5, threshold: 2.0, max: 10 },
                  { label: "BB Position", value: bbPos, threshold: 0.9, max: 1 },
                  { label: "RSI Extreme", value: Math.abs(rsi - 50), threshold: 20, max: 50 },
                  { label: "Trend Strength", value: parseFloat(f.adx || "0"), threshold: 25, max: 50 },
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
                  <p>
                    <span className="text-red-400 font-medium">Aşırı alım bölgesinde.</span> RSI {rsi.toFixed(0)} seviyesinde.
                    {mom5 > 3 && " Güçlü momentum var ama geri çekilme riski artıyor."}
                    {volZ > 2 && " Hacim anomalisi tespit edildi — dikkatli olunmalı."}
                  </p>
                ) : rsi < 30 ? (
                  <p>
                    <span className="text-emerald-400 font-medium">Aşırı satım bölgesinde.</span> RSI {rsi.toFixed(0)} seviyesinde.
                    {mom5 < -3 && " Düşüş momentumu güçlü."}
                    {" Potansiyel toparlanma alanı."}
                  </p>
                ) : mom5 > 3 ? (
                  <p>
                    <span className="text-emerald-400 font-medium">Güçlü kısa vadeli momentum.</span> Son 5 günde %{mom5.toFixed(1)} yükseliş.
                    {volZ > 1.5 && " Hacim desteği var."}
                    {bbPos > 0.8 && " Bollinger üst bandına yakın — aşırı alım riski."}
                  </p>
                ) : mom5 < -3 ? (
                  <p>
                    <span className="text-red-400 font-medium">Zayıf momentum.</span> Son 5 günde %{Math.abs(mom5).toFixed(1)} düşüş.
                    {rsi < 40 && " RSI düşük seviyede — satmak için geç olabilir."}
                  </p>
                ) : (
                  <p>
                    <span className="text-zinc-400">Normal seviyelerde.</span> Belirgin bir sinyal yok.
                    RSI {rsi.toFixed(0)}, momentum nötr.
                  </p>
                )}
              </div>

              <div className="mt-3 pt-2 border-t border-zinc-800/60">
                <h4 className="text-[9px] uppercase tracking-wider text-zinc-600 mb-1.5">Key Metrics</h4>
                <div className="grid grid-cols-2 gap-1 text-[10px]">
                  <div className="flex justify-between">
                    <span className="text-zinc-600">BB Position</span>
                    <span className="font-mono text-zinc-400">{bbPos.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-600">Vol Z-Score</span>
                    <span className="font-mono text-zinc-400">{volZ.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-600">ATR%</span>
                    <span className="font-mono text-zinc-400">{atrPct.toFixed(2)}%</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-600">MACD</span>
                    <span className="font-mono text-zinc-400">{macd.toFixed(2)}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
