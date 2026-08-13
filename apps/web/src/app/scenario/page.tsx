"use client";

import { useState } from "react";

interface ScenarioResult {
  name: string;
  marketChange: number;
  probability: number;
  portfolioImpact: number;
  color: string;
}

export default function ScenarioLab() {
  const [ticker, setTicker] = useState("THYAO");
  const [weight, setWeight] = useState(8);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<ScenarioResult[] | null>(null);

  const runSimulation = () => {
    setRunning(true);
    setTimeout(() => {
      setResults([
        { name: "Strong Bull", marketChange: 10, probability: 15, portfolioImpact: 12.4, color: "text-emerald-400" },
        { name: "Bull", marketChange: 5, probability: 30, portfolioImpact: 6.8, color: "text-emerald-400" },
        { name: "Base", marketChange: 0, probability: 30, portfolioImpact: 0.4, color: "text-zinc-400" },
        { name: "Bear", marketChange: -5, probability: 18, portfolioImpact: -5.2, color: "text-red-400" },
        { name: "Crash", marketChange: -15, probability: 7, portfolioImpact: -14.8, color: "text-red-400" },
      ]);
      setRunning(false);
    }, 1500);
  };

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Scenario Lab</h1>
        <p className="text-[11px] text-zinc-600">Monte Carlo simulation • stress testing • what-if analysis</p>
      </div>

      {/* Input Panel */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
        <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Simulation Parameters</h2>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="text-[10px] text-zinc-600 block mb-1">Ticker</label>
            <input
              type="text"
              value={ticker}
              onChange={e => setTicker(e.target.value.toUpperCase())}
              className="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-zinc-600"
            />
          </div>
          <div>
            <label className="text-[10px] text-zinc-600 block mb-1">Portfolio Weight (%)</label>
            <input
              type="number"
              value={weight}
              onChange={e => setWeight(Number(e.target.value))}
              min={0}
              max={100}
              className="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-zinc-600"
            />
          </div>
          <div className="flex items-end">
            <button
              onClick={runSimulation}
              disabled={running}
              className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-800 text-white text-xs font-medium py-1.5 rounded transition-colors"
            >
              {running ? "Running..." : "Run 10,000 Scenarios"}
            </button>
          </div>
        </div>
      </div>

      {/* Results */}
      {results && (
        <>
          <div className="grid grid-cols-5 gap-3">
            {results.map(r => (
              <div key={r.name} className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
                <p className="text-[9px] uppercase tracking-wider text-zinc-600">{r.name}</p>
                <p className="text-[10px] text-zinc-500 mt-0.5">Market {r.marketChange > 0 ? "+" : ""}{r.marketChange}%</p>
                <p className={`text-lg font-mono font-semibold mt-1 ${r.color}`}>
                  {r.portfolioImpact > 0 ? "+" : ""}{r.portfolioImpact.toFixed(1)}%
                </p>
                <div className="w-full h-1 bg-zinc-800 rounded-full mt-2 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${r.portfolioImpact >= 0 ? "bg-emerald-500" : "bg-red-500"}`}
                    style={{ width: `${r.probability}%` }}
                  />
                </div>
                <p className="text-[9px] text-zinc-600 mt-1">{r.probability}% probability</p>
              </div>
            ))}
          </div>

          <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
            <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Summary</h2>
            <div className="grid grid-cols-4 gap-4 text-[11px]">
              <div>
                <p className="text-zinc-600">Expected Return</p>
                <p className="font-mono text-zinc-200">+1.8%</p>
              </div>
              <div>
                <p className="text-zinc-600">VaR 95%</p>
                <p className="font-mono text-red-400">-8.4%</p>
              </div>
              <div>
                <p className="text-zinc-600">CVaR 95%</p>
                <p className="font-mono text-red-400">-12.1%</p>
              </div>
              <div>
                <p className="text-zinc-600">Prob Positive</p>
                <p className="font-mono text-emerald-400">62%</p>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
