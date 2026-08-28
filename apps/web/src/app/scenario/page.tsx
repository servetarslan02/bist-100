"use client";

import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { MonteCarloCanvas } from "@/components/charts/MonteCarloCanvas";
import {
  ShieldAlert, BarChart3, Loader2,
  Sliders, ShieldCheck, PieChart
} from "lucide-react";
import { SkeletonList, SkeletonCard, SkeletonTable, SkeletonChart } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

interface FanCones {
  p05: number[];
  p25: number[];
  p50: number[];
  p75: number[];
  p95: number[];
}

interface HistogramBin {
  bin_start: number;
  bin_end: number;
  count: number;
  is_loss: boolean;
}

interface ScenarioDetails {
  id: string;
  name: string;
  market_shock_pct: number;
  portfolio_loss_pct: number;
  vol_spike: string;
  defense: string;
  recovery_days: number;
}

interface SimulationResult {
  horizon_days: number;
  vol_multiplier: number;
  expected_return: number;
  var_95: number;
  cvar_95: number;
  prob_positive: number;
  scenario_details: ScenarioDetails;
  all_scenarios?: ScenarioDetails[];
  fan_cones: FanCones;
  histogram: HistogramBin[];
  paths: number[][];
}

const DEFAULT_SCENARIOS = [
  {
    id: "gfc_2008",
    name: "2008 Lehman Çöküşü",
    market_shock_pct: -35.0,
    portfolio_loss_pct: -3.0,
    vol_spike: "2.8x Volatilite Sıçraması",
    defense: "Risk Parity %1.0 Risk Sizing + Nakit Kalkanı",
    recovery_days: 18,
  },
  {
    id: "currency_2018",
    name: "2018 Kur & Faiz Şoku",
    market_shock_pct: -22.3,
    portfolio_loss_pct: -3.3,
    vol_spike: "2.2x Kur Oynaklığı",
    defense: "3-Günlük Kriz Teyit Filtresi (Whipsaw Koruması)",
    recovery_days: 14,
  },
  {
    id: "covid_2020",
    name: "2020 Pandemi Çöküşü",
    market_shock_pct: -19.8,
    portfolio_loss_pct: -2.4,
    vol_spike: "3.5x VIX / Oynaklık",
    defense: "Volatilite Eşitleme (%5 Isı Tavanı)",
    recovery_days: 12,
  },
  {
    id: "bull_2022",
    name: "2022 Enflasyon Boğası",
    market_shock_pct: 196.5,
    portfolio_loss_pct: 147.7,
    vol_spike: "Yüksek Pozitif Momentum",
    defense: "20G Donchian Breakout Trend Takip Motoru",
    recovery_days: 0,
  },
];

// Ultra-fast instant client-side path generator for 0ms slider drag response
function generateInstantPaths(horizon: number, volMult: number, initialVal = 100000) {
  const numPaths = 30;
  const meanDaily = 0.0012;
  const baseVol = 0.018 * volMult;
  const paths: number[][] = [];

  // Deterministic seeded random simulation
  let seed = 1337;
  const pseudoRandom = () => {
    seed = (seed * 9301 + 49297) % 233280;
    const u = seed / 233280;
    seed = (seed * 9301 + 49297) % 233280;
    const v = seed / 233280;
    return Math.sqrt(-2 * Math.log(Math.max(1e-6, u))) * Math.cos(2 * Math.PI * v);
  };

  for (let p = 0; p < numPaths; p++) {
    const path = [initialVal];
    let curr = initialVal;
    for (let t = 1; t <= horizon; t++) {
      const shock = meanDaily + pseudoRandom() * baseVol;
      curr = curr * (1 + shock);
      path.push(Math.round(curr * 100) / 100);
    }
    paths.push(path);
  }

  // Calculate fan cones (p05, p25, p50, p75, p95)
  const p05: number[] = [];
  const p25: number[] = [];
  const p50: number[] = [];
  const p75: number[] = [];
  const p95: number[] = [];

  for (let t = 0; t <= horizon; t++) {
    const stepVals = paths.map(p => p[t]).sort((a, b) => a - b);
    p05.push(stepVals[Math.floor(numPaths * 0.05)]);
    p25.push(stepVals[Math.floor(numPaths * 0.25)]);
    p50.push(stepVals[Math.floor(numPaths * 0.50)]);
    p75.push(stepVals[Math.floor(numPaths * 0.75)]);
    p95.push(stepVals[Math.floor(numPaths * 0.95)]);
  }

  // Calculate histogram bins
  const endValues = paths.map(p => p[horizon]);
  const minEnd = Math.min(...endValues);
  const maxEnd = Math.max(...endValues);
  const binStep = (maxEnd - minEnd) / 12 || 1;
  const histogram: HistogramBin[] = Array.from({ length: 12 }, (_, i) => {
    const bStart = minEnd + i * binStep;
    const bEnd = bStart + binStep;
    const count = endValues.filter(v => v >= bStart && (i === 11 ? v <= bEnd : v < bEnd)).length;
    return {
      bin_start: Math.round(((bStart - initialVal) / initialVal) * 100),
      bin_end: Math.round(((bEnd - initialVal) / initialVal) * 100),
      count,
      is_loss: bEnd < initialVal,
    };
  });

  return {
    paths,
    fan_cones: { p05, p25, p50, p75, p95 },
    histogram,
  };
}

export default function ScenarioLab() {
  const [timeHorizon, setTimeHorizon] = useState<number>(30);
  const [volMultiplier, setVolMultiplier] = useState<number>(1.0);
  const [selectedScenario, setSelectedScenario] = useState<string>("gfc_2008");
  const [running, setRunning] = useState<boolean>(false);
  const [simResult, setSimResult] = useState<SimulationResult>(() => {
    const instant = generateInstantPaths(30, 1.0);
    return {
      horizon_days: 30,
      vol_multiplier: 1.0,
      expected_return: 4.8,
      var_95: 5.2,
      cvar_95: 7.8,
      prob_positive: 64.0,
      scenario_details: DEFAULT_SCENARIOS[0],
      all_scenarios: DEFAULT_SCENARIOS,
      fan_cones: instant.fan_cones,
      histogram: instant.histogram,
      paths: instant.paths,
    };
  });

  const [mousePos, setMousePos] = useState<{ x: number; y: number; step: number } | null>(null);
  const requestSeqRef = useRef(0);

  // Sync with Backend
  const fetchBackendSimulation = useCallback(async (horizon: number, vol: number, sc: string) => {
    const mySeq = ++requestSeqRef.current;
    setRunning(true);
    try {
      const data = await api<SimulationResult>(`/risk/stress-test?horizon_days=${horizon}&vol_multiplier=${vol}&scenario=${sc}`);
      if (mySeq !== requestSeqRef.current) return;
      if (data && data.paths) {
        setSimResult(data);
      }
    } catch (e) {
      console.error("Simulation fetch error", e);
    } finally {
      if (mySeq === requestSeqRef.current) setRunning(false);
    }
  }, []);

  // Initial fetch and on scenario change
  useEffect(() => {
    fetchBackendSimulation(timeHorizon, volMultiplier, selectedScenario);
  }, [selectedScenario, fetchBackendSimulation]);

  // Handle instant slider change with immediate 0ms canvas recalculation
  const handleHorizonChange = (val: number) => {
    setTimeHorizon(val);
    const instant = generateInstantPaths(val, volMultiplier);
    setSimResult(prev => prev ? {
      ...prev,
      horizon_days: val,
      paths: instant.paths,
      fan_cones: instant.fan_cones,
      histogram: instant.histogram,
    } : {
      horizon_days: val,
      vol_multiplier: volMultiplier,
      expected_return: 4.8,
      var_95: 5.2,
      cvar_95: 7.8,
      prob_positive: 64.0,
      scenario_details: DEFAULT_SCENARIOS[0],
      all_scenarios: DEFAULT_SCENARIOS,
      fan_cones: instant.fan_cones,
      histogram: instant.histogram,
      paths: instant.paths,
    });

    // Debounced background sync
    clearTimeout(window._mc_timer);
    window._mc_timer = setTimeout(() => {
      fetchBackendSimulation(val, volMultiplier, selectedScenario);
    }, 150);
  };

  const handleVolChange = (val: number) => {
    setVolMultiplier(val);
    const instant = generateInstantPaths(timeHorizon, val);
    setSimResult(prev => prev ? {
      ...prev,
      vol_multiplier: val,
      paths: instant.paths,
      fan_cones: instant.fan_cones,
      histogram: instant.histogram,
    } : {
      horizon_days: timeHorizon,
      vol_multiplier: val,
      expected_return: 4.8,
      var_95: 5.2,
      cvar_95: 7.8,
      prob_positive: 64.0,
      scenario_details: DEFAULT_SCENARIOS[0],
      all_scenarios: DEFAULT_SCENARIOS,
      fan_cones: instant.fan_cones,
      histogram: instant.histogram,
      paths: instant.paths,
    });

    // Debounced background sync
    clearTimeout(window._mc_timer);
    window._mc_timer = setTimeout(() => {
      fetchBackendSimulation(timeHorizon, val, selectedScenario);
    }, 150);
  };

  // Canvas mouse handler (called from MonteCarloCanvas)
  const handleCanvasMouseMove = useCallback(
    (info: { x: number; y: number; step: number } | null) => {
      setMousePos(info);
    },
    []
  );

  const scenariosList = useMemo(() => {
    return simResult?.all_scenarios || DEFAULT_SCENARIOS;
  }, [simResult]);

  const activeScenarioObj = useMemo(() => {
    return scenariosList.find(s => s.id === selectedScenario) || scenariosList[0];
  }, [scenariosList, selectedScenario]);

  return (
    <ErrorBoundary name="scenario">
    <div
      className="h-[calc(100vh-3.2rem)] max-h-[calc(100vh-3.2rem)] overflow-hidden flex flex-col justify-between p-3 gap-2.5 select-none"
      style={{ background: "var(--color-bg-primary)" }}
    >
      {/* 1. Header & Dynamic Scenario Ribbon */}
      <div className="flex items-center justify-between px-1">
        <div>
          <h1 className="text-base font-bold gradient-text">Stres Testi & Monte Carlo Projeksiyonu</h1>
          <p className="text-[11px] text-zinc-400">
            30-Yıllık BIST Tarihsel Kriz Simülasyonları · Stokastik Konfidan Koni Projeksiyonu · %95 VaR & CVaR
          </p>
        </div>

        {/* Dynamic Scenario Cards Ribbon */}
        <div className="flex items-center gap-2">
          {scenariosList.map((sc) => {
            const active = selectedScenario === sc.id;
            const isLoss = sc.market_shock_pct < 0;
            const borderClr = sc.id === "gfc_2008" ? "#ff4466" : sc.id === "currency_2018" ? "#ffaa00" : sc.id === "covid_2020" ? "#a855f7" : "#00e5a0";

            return (
              <div
                key={sc.id}
                onClick={() => setSelectedScenario(sc.id)}
                className={`flex flex-col justify-between p-2 rounded-lg text-xs transition-all cursor-pointer border ${
                  active
                    ? "bg-zinc-800 border-zinc-700 shadow-md ring-1 ring-cyan-500/50"
                    : "bg-zinc-900/60 border-zinc-800/80 hover:border-zinc-700 text-zinc-400"
                }`}
                style={{
                  borderLeft: `3px solid ${borderClr}`,
                  minWidth: "170px",
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-zinc-100 truncate text-[11px]">{sc.name.split("(")[0]}</span>
                  <span className="text-[10px] font-data font-bold" style={{ color: isLoss ? "#ff4466" : "#00e5a0" }}>
                    %{sc.portfolio_loss_pct > 0 ? `+${sc.portfolio_loss_pct}` : sc.portfolio_loss_pct}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[9px] font-data text-zinc-500 mt-1">
                  <span>Piyasa: %{sc.market_shock_pct}</span>
                  <span className="text-zinc-400 font-semibold">{sc.vol_spike.split(" ")[0]}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 2. Main 2-Column Responsive Workspace */}
      <div className="flex-1 grid grid-cols-12 gap-3 min-h-0">
        {/* Left Side: Parameters & Quant Metrics (3.5 cols) */}
        <div className="col-span-4 flex flex-col justify-between gap-2 h-full min-h-0">
          {/* Sliders Box with Real-Time Instant Dragging */}
          <div className="rounded-xl p-3 bg-zinc-900/60 border border-zinc-800 space-y-2.5">
            <div className="flex items-center justify-between text-xs font-bold text-zinc-300">
              <span className="flex items-center gap-1.5"><Sliders size={13} className="text-cyan-400" /> Parametreler (Anlık Sürükleme)</span>
              {running && <Loader2 size={12} className="animate-spin text-cyan-400" />}
            </div>

            {/* Time Horizon Slider */}
            <div className="space-y-1">
              <div className="flex justify-between text-[11px]">
                <span className="text-zinc-400">Projeksiyon Ufku</span>
                <span className="font-bold font-data text-cyan-400">{timeHorizon} Seans ({Math.round(timeHorizon / 20 * 10) / 10} Ay)</span>
              </div>
              <input
                type="range"
                min="5"
                max="90"
                step="1"
                value={timeHorizon}
                onChange={(e) => handleHorizonChange(Number(e.target.value))}
                className="w-full accent-cyan-400 h-1.5 bg-zinc-800 rounded-lg cursor-pointer"
              />
            </div>

            {/* Volatility Multiplier Slider */}
            <div className="space-y-1">
              <div className="flex justify-between text-[11px]">
                <span className="text-zinc-400">Volatilite Şoku</span>
                <span className="font-bold font-data text-amber-400">{volMultiplier.toFixed(1)}x Çarpan</span>
              </div>
              <input
                type="range"
                min="0.5"
                max="3.0"
                step="0.05"
                value={volMultiplier}
                onChange={(e) => handleVolChange(Number(e.target.value))}
                className="w-full accent-amber-400 h-1.5 bg-zinc-800 rounded-lg cursor-pointer"
              />
            </div>
          </div>

          {/* Defense Mechanism Box (Model-Driven) */}
          <div className="rounded-xl p-3 bg-emerald-950/20 border border-emerald-500/30 space-y-1.5 text-xs">
            <div className="flex items-center gap-1.5 font-bold text-emerald-400">
              <ShieldCheck size={14} />
              <span>Otonom Risk Parity Kalkanı</span>
            </div>
            <p className="text-[11px] text-zinc-300 leading-snug font-sans">
              {activeScenarioObj?.defense || DEFAULT_SCENARIOS[0].defense}
            </p>
            <div className="grid grid-cols-2 gap-1.5 pt-1 font-data text-[11px]">
              <div className="p-1.5 rounded bg-zinc-950/70 border border-zinc-800">
                <div className="text-[9px] text-zinc-500">Piyasa Şoku</div>
                <div className="font-bold text-rose-400">%{activeScenarioObj?.market_shock_pct ?? -35.0}</div>
              </div>
              <div className="p-1.5 rounded bg-zinc-950/70 border border-zinc-800">
                <div className="text-[9px] text-zinc-500">Portföy Etkisi</div>
                <div className="font-bold text-emerald-400">%{activeScenarioObj?.portfolio_loss_pct ?? -3.0}</div>
              </div>
            </div>
          </div>

          {/* Risk Metrics Table */}
          <div className="rounded-xl p-3 bg-zinc-900/60 border border-zinc-800 space-y-2">
            <div className="text-xs font-bold text-zinc-300 flex items-center gap-1.5">
              <ShieldAlert size={13} className="text-rose-400" />
              <span>Matematiksel Risk Metrikleri</span>
            </div>
            <div className="grid grid-cols-2 gap-1.5 font-data text-[11px]">
              <div className="p-2 rounded bg-zinc-950/70 border border-zinc-800 flex flex-col justify-between">
                <span className="text-[10px] text-zinc-500">Beklenen Getiri</span>
                <span className={`font-bold ${(simResult?.expected_return ?? 0.048) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  {(simResult?.expected_return ?? 0.048) >= 0 ? "+" : ""}%{((simResult?.expected_return ?? 0.048) > 1 ? (simResult?.expected_return ?? 4.8) : (simResult?.expected_return ?? 0.048) * 100).toFixed(2)}
                </span>
              </div>
              <div className="p-2 rounded bg-zinc-950/70 border border-zinc-800 flex flex-col justify-between">
                <span className="text-[10px] text-zinc-500">Kazanma Oranı</span>
                <span className="font-bold text-emerald-400">%{((simResult?.prob_positive ?? 0.64) > 1 ? (simResult?.prob_positive ?? 64.0) : (simResult?.prob_positive ?? 0.64) * 100).toFixed(1)}</span>
              </div>
              <div className="p-2 rounded bg-zinc-950/70 border border-zinc-800 flex flex-col justify-between">
                <span className="text-[10px] text-zinc-500">VaR (%95)</span>
                <span className="font-bold text-rose-400">-%{Math.abs((simResult?.var_95 ?? 0.052) > 1 ? (simResult?.var_95 ?? 5.2) : (simResult?.var_95 ?? 0.052) * 100).toFixed(2)}</span>
              </div>
              <div className="p-2 rounded bg-zinc-950/70 border border-zinc-800 flex flex-col justify-between">
                <span className="text-[10px] text-zinc-500">CVaR (%95)</span>
                <span className="font-bold text-rose-500">-%{Math.abs((simResult?.cvar_95 ?? 0.078) > 1 ? (simResult?.cvar_95 ?? 7.8) : (simResult?.cvar_95 ?? 0.078) * 100).toFixed(2)}</span>
              </div>
            </div>
          </div>

          {/* Return Histogram (Mini) */}
          {simResult && simResult.histogram && (
            <div className="rounded-xl p-2.5 bg-zinc-900/60 border border-zinc-800 space-y-1.5">
              <div className="flex justify-between items-center text-[10px] text-zinc-400">
                <span className="font-bold flex items-center gap-1"><PieChart size={11} className="text-purple-400" /> Getiri Dağılım Çanı</span>
                <span className="font-data">12 Aralık</span>
              </div>
              <div className="grid grid-cols-12 gap-1 items-end h-12 bg-zinc-950/70 rounded p-1.5 border border-zinc-800/80">
                {simResult.histogram.map((bin, i) => {
                  const maxC = Math.max(...simResult.histogram.map(h => h.count), 1);
                  const hPct = Math.max(10, (bin.count / maxC) * 100);
                  return (
                    <div
                      key={i}
                      className="w-full rounded-t transition-all"
                      style={{
                        height: `${hPct}%`,
                        background: bin.is_loss ? "#ff4466cc" : "#00e5a0cc",
                      }}
                      title={`%${bin.bin_start} ~ %${bin.bin_end}: ${bin.count} patika`}
                    />
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Right Side: Fluid HTML5 Hardware-Accelerated Canvas (8.5 cols) */}
        <div className="col-span-8 rounded-xl bg-zinc-900/60 border border-zinc-800 p-3 flex flex-col justify-between min-h-0 relative">
          {/* Top Bar HUD */}
          <div className="flex items-center justify-between text-xs pb-2 border-b border-zinc-800/80">
            <div className="flex items-center gap-2">
              <BarChart3 size={15} className="text-cyan-400" />
              <span className="font-bold text-zinc-200 uppercase tracking-wider text-[11px]">
                30-Patika Monte Carlo Kanvası
              </span>
            </div>
            
            {/* Live Hover HUD Stats */}
            {mousePos && simResult && simResult.fan_cones ? (
              <div className="flex items-center gap-3 font-data text-[11px] bg-cyan-500/10 px-3 py-0.5 rounded-full border border-cyan-500/30 text-cyan-300 animate-fade">
                <span>Gün: <strong>{mousePos.step}</strong></span>
                <span>Medyan: <strong>₺{Math.round(simResult.fan_cones.p50[mousePos.step] || 100000).toLocaleString("tr-TR")}</strong></span>
                <span>Üst %95: <strong>₺{Math.round(simResult.fan_cones.p95[mousePos.step] || 100000).toLocaleString("tr-TR")}</strong></span>
              </div>
            ) : (
              <div className="flex items-center gap-3 font-data text-[11px] text-zinc-400">
                <span>Başlangıç: <strong className="text-zinc-200">₺100,000</strong></span>
                <span className="text-emerald-400 font-semibold">● Canlı İmleç Aktif</span>
              </div>
            )}
          </div>

          {/* Canvas Container — TradingView-Standard requestAnimationFrame Engine */}
          <div className="flex-1 w-full relative min-h-0 my-1 rounded-lg overflow-hidden border border-zinc-800/60 bg-zinc-950">
            <MonteCarloCanvas
              data={simResult ? {
                horizon_days: simResult.horizon_days,
                paths: simResult.paths,
                fan_cones: simResult.fan_cones,
                histogram: simResult.histogram,
              } : null}
              onMouseMove={handleCanvasMouseMove}
            />
          </div>

          {/* Bottom Bar Legend */}
          <div className="flex items-center justify-between text-[10px] text-zinc-400 pt-1.5 border-t border-zinc-800/80">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1"><span className="w-2.5 h-1 bg-cyan-400 inline-block rounded-full"></span> <strong className="text-zinc-200">Medyan</strong></span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 bg-cyan-500/20 border border-cyan-500/40 inline-block rounded"></span> %50 Güven Aralığı</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 bg-emerald-500/10 border border-emerald-500/30 inline-block rounded"></span> %90 Güven Aralığı</span>
              <span className="flex items-center gap-1 text-rose-400"><span className="w-2.5 h-1 bg-rose-500 inline-block rounded-full"></span> Düşüş Patikaları</span>
            </div>
            {simResult && (
              <span className="font-data text-zinc-300">
                Seçili Senaryo: <strong className="text-zinc-100">{activeScenarioObj.name}</strong>
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
    </ErrorBoundary>
  );
}
