"use client";

import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { MonteCarloCanvas } from "@/components/charts/MonteCarloCanvas";
import {
  ShieldAlert, BarChart3, Loader2,
  Sliders, ShieldCheck, PieChart, Activity, Zap, TrendingUp, AlertTriangle
} from "lucide-react";
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

const DEFAULT_SCENARIOS: ScenarioDetails[] = [
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

// Instant client-side path generator for 0ms slider drag response
function generateInstantPaths(horizon: number, volMult: number, initialVal = 100000) {
  const numPaths = 30;
  const meanDaily = 0.0012;
  const baseVol = 0.018 * volMult;
  const paths: number[][] = [];

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
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Sync with Backend
  const fetchBackendSimulation = useCallback(async (horizon: number, vol: number, sc: string) => {
    const mySeq = ++requestSeqRef.current;
    setRunning(true);
    try {
      const data = await api<SimulationResult>(`/risk/stress-test?horizon_days=${horizon}&vol_multiplier=${vol}&scenario=${sc}`);
      if (mySeq !== requestSeqRef.current) return;
      if (data && data.paths && data.paths.length > 0) {
        setSimResult(data);
      }
    } catch (e) {
      console.error("Simulation fetch error", e);
    } finally {
      if (mySeq === requestSeqRef.current) setRunning(false);
    }
  }, []);

  useEffect(() => {
    fetchBackendSimulation(timeHorizon, volMultiplier, selectedScenario);
  }, [selectedScenario, fetchBackendSimulation]);

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

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      fetchBackendSimulation(val, volMultiplier, selectedScenario);
    }, 180);
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

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      fetchBackendSimulation(timeHorizon, val, selectedScenario);
    }, 180);
  };

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

  const formattedExpectedRet = useMemo(() => {
    const v = simResult?.expected_return ?? 4.8;
    const num = Math.abs(v) > 1 ? v : v * 100;
    return `${num >= 0 ? "+" : ""}%${num.toFixed(2)}`;
  }, [simResult]);

  const formattedWinRate = useMemo(() => {
    const v = simResult?.prob_positive ?? 64.0;
    const num = v > 1 ? v : v * 100;
    return `%${num.toFixed(1)}`;
  }, [simResult]);

  const formattedVar95 = useMemo(() => {
    const v = simResult?.var_95 ?? 5.2;
    const num = Math.abs(v) > 1 ? Math.abs(v) : Math.abs(v) * 100;
    return `-%${num.toFixed(2)}`;
  }, [simResult]);

  const formattedCVar95 = useMemo(() => {
    const v = simResult?.cvar_95 ?? 7.8;
    const num = Math.abs(v) > 1 ? Math.abs(v) : Math.abs(v) * 100;
    return `-%${num.toFixed(2)}`;
  }, [simResult]);

  return (
    <ErrorBoundary name="scenario">
      <div className="relative min-h-screen pb-12 overflow-hidden select-none" style={{ background: "var(--color-bg-primary)" }}>
        {/* Ambient Radial Glow */}
        <div 
          className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[900px] h-[300px] opacity-15 blur-[120px] rounded-full"
          style={{ background: "radial-gradient(ellipse, #ff4466 0%, #00c8ff 40%, transparent 70%)" }}
        />

        <div className="relative max-w-7xl mx-auto p-3.5 md:p-5 lg:p-6 space-y-3.5">
          
          {/* 1. ULTRA KOMPAKT HEADER & KONTROL ŞERİDİ (~45px) */}
          <div className="rounded-xl px-4 py-2.5 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-3">
            
            {/* Sol: Başlık ve Canlı Çipler */}
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="flex items-center gap-2">
                <ShieldAlert size={18} className="text-rose-400 shrink-0 animate-pulse" />
                <h1 className="text-base font-extrabold text-white tracking-tight">
                  Stres Testi & Monte Carlo Projeksiyonu
                </h1>
              </div>

              <div className="h-3.5 w-px bg-white/[0.1] hidden sm:block" />

              <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-data">
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-rose-500/10 text-rose-300 border border-rose-500/20 font-semibold">
                  <Activity size={11} />
                  <span>4 Kriz Senaryosu</span>
                </span>

                <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 font-semibold">
                  1.000 Monte Carlo Patikası
                </span>

                <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-semibold hidden md:inline-block">
                  Risk Parity Kalkanı Aktif
                </span>
              </div>
            </div>

            {/* Sağ: Hızlı Senaryo Seçim Hapları */}
            <div className="flex items-center gap-1.5 overflow-x-auto py-0.5 max-w-full">
              {scenariosList.map((sc) => {
                const active = selectedScenario === sc.id;
                const isLoss = sc.market_shock_pct < 0;
                const borderClr = sc.id === "gfc_2008" ? "#ff4466" : sc.id === "currency_2018" ? "#ffaa00" : sc.id === "covid_2020" ? "#a855f7" : "#00e5a0";

                return (
                  <button
                    key={sc.id}
                    onClick={() => setSelectedScenario(sc.id)}
                    className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all border shrink-0 ${
                      active
                        ? "bg-zinc-800 text-white shadow-md border-white/20 ring-1 ring-cyan-500/50"
                        : "bg-zinc-900/60 border-white/[0.06] text-zinc-400 hover:text-zinc-200 hover:border-white/10"
                    }`}
                    style={{ borderLeft: `3px solid ${borderClr}` }}
                  >
                    <span className="text-[11px] font-bold">{sc.name.split(" ")[0]}</span>
                    <span className="text-[10px] font-data font-bold" style={{ color: isLoss ? "#ff4466" : "#00e5a0" }}>
                      %{sc.portfolio_loss_pct > 0 ? `+${sc.portfolio_loss_pct}` : sc.portfolio_loss_pct}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 2. ANA 2-KOLON ÇALIŞMA ALANI */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3.5">
            
            {/* Sol Panel: Parametreler & Quant Risk Metrikleri (4 Kolon) */}
            <div className="lg:col-span-4 space-y-3">
              
              {/* Sürgüler Kutusu */}
              <div className="rounded-xl p-3.5 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg space-y-3">
                <div className="flex items-center justify-between text-xs font-bold text-zinc-200">
                  <span className="flex items-center gap-1.5">
                    <Sliders size={14} className="text-cyan-400" />
                    <span>Parametreler (Anlık Sürükleme)</span>
                  </span>
                  {running && <Loader2 size={13} className="animate-spin text-cyan-400" />}
                </div>

                {/* Projeksiyon Ufku */}
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs font-data">
                    <span className="text-zinc-400">Projeksiyon Ufku</span>
                    <span className="font-bold text-cyan-400">
                      {timeHorizon} Seans ({Math.round(timeHorizon / 20 * 10) / 10} Ay)
                    </span>
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

                {/* Volatilite Çarpanı */}
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs font-data">
                    <span className="text-zinc-400">Volatilite Şoku</span>
                    <span className="font-bold text-amber-400">{volMultiplier.toFixed(1)}x Çarpan</span>
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

              {/* Otonom Risk Parity Kalkanı */}
              <div className="rounded-xl p-3.5 border border-emerald-500/30 bg-emerald-950/15 backdrop-blur-xl shadow-lg space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 font-bold text-xs text-emerald-400">
                    <ShieldCheck size={15} />
                    <span>Otonom Risk Parity Kalkanı</span>
                  </div>
                  <span className="text-[10px] font-data font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    {activeScenarioObj.recovery_days > 0 ? `${activeScenarioObj.recovery_days}G Toparlanma` : "Anında Savunma"}
                  </span>
                </div>

                <p className="text-[11px] text-zinc-300 leading-relaxed font-sans bg-zinc-950/40 p-2.5 rounded-lg border border-white/[0.04]">
                  {activeScenarioObj?.defense || DEFAULT_SCENARIOS[0].defense}
                </p>

                <div className="grid grid-cols-2 gap-2 font-data text-xs pt-0.5">
                  <div className="p-2 rounded-lg bg-zinc-950/60 border border-white/[0.04]">
                    <div className="text-[9px] text-zinc-400 uppercase font-semibold">Piyasa Şoku</div>
                    <div className="font-bold text-rose-400 mt-0.5">%{activeScenarioObj?.market_shock_pct ?? -35.0}</div>
                  </div>
                  <div className="p-2 rounded-lg bg-zinc-950/60 border border-white/[0.04]">
                    <div className="text-[9px] text-zinc-400 uppercase font-semibold">Portföy Etkisi</div>
                    <div className="font-bold text-emerald-400 mt-0.5">%{activeScenarioObj?.portfolio_loss_pct ?? -3.0}</div>
                  </div>
                </div>
              </div>

              {/* Matematiksel Risk Metrikleri */}
              <div className="rounded-xl p-3.5 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg space-y-2.5">
                <div className="text-xs font-bold text-zinc-200 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <ShieldAlert size={14} className="text-rose-400" />
                    <span>Matematiksel Risk Metrikleri</span>
                  </span>
                  <span className="text-[10px] text-zinc-500 font-data">Ufuk: {timeHorizon}G</span>
                </div>

                <div className="grid grid-cols-2 gap-2 font-data text-xs">
                  <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-white/[0.04] flex flex-col justify-between">
                    <span className="text-[10px] text-zinc-400 font-semibold">Beklenen Getiri</span>
                    <span className={`font-bold text-sm mt-1 ${(simResult?.expected_return ?? 4.8) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {formattedExpectedRet}
                    </span>
                  </div>

                  <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-white/[0.04] flex flex-col justify-between">
                    <span className="text-[10px] text-zinc-400 font-semibold">Kazanma Oranı</span>
                    <span className="font-bold text-sm text-cyan-400 mt-1">
                      {formattedWinRate}
                    </span>
                  </div>

                  <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-white/[0.04] flex flex-col justify-between">
                    <span className="text-[10px] text-zinc-400 font-semibold">VaR (%95)</span>
                    <span className="font-bold text-sm text-rose-400 mt-1">
                      {formattedVar95}
                    </span>
                  </div>

                  <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-white/[0.04] flex flex-col justify-between">
                    <span className="text-[10px] text-zinc-400 font-semibold">CVaR / Expected Shortfall</span>
                    <span className="font-bold text-sm text-rose-500 mt-1">
                      {formattedCVar95}
                    </span>
                  </div>
                </div>
              </div>

              {/* Getiri Dağılım Çanı (Histogram) */}
              {simResult && simResult.histogram && (
                <div className="rounded-xl p-3 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg space-y-2">
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-bold text-zinc-200 flex items-center gap-1.5">
                      <PieChart size={13} className="text-purple-400" />
                      <span>Getiri Dağılım Çanı (12 Bin)</span>
                    </span>
                    <span className="text-[10px] font-data text-zinc-500">Stokastik Dağılım</span>
                  </div>

                  <div className="grid grid-cols-12 gap-1 items-end h-14 bg-zinc-950/60 rounded-lg p-2 border border-white/[0.04]">
                    {simResult.histogram.map((bin, i) => {
                      const maxC = Math.max(...simResult.histogram.map(h => h.count), 1);
                      const hPct = Math.max(12, (bin.count / maxC) * 100);
                      return (
                        <div
                          key={i}
                          className="w-full rounded-t transition-all hover:brightness-125"
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

            {/* Sağ Panel: HTML5 Donanım Hızlandırmalı Canvas (8 Kolon) */}
            <div className="lg:col-span-8 rounded-xl p-4 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg flex flex-col justify-between gap-3 min-h-[500px]">
              
              {/* Üst Bar HUD */}
              <div className="flex items-center justify-between pb-2 border-b border-white/[0.06]">
                <div className="flex items-center gap-2">
                  <BarChart3 size={16} className="text-cyan-400" />
                  <span className="font-bold text-white text-xs uppercase tracking-wider">
                    Monte Carlo Simülasyonu (Konfidan Koni Projeksiyonu)
                  </span>
                </div>

                {/* Canlı İmleç Takibi */}
                {mousePos && simResult && simResult.fan_cones ? (
                  <div className="flex items-center gap-2.5 font-data text-xs bg-cyan-500/10 px-3 py-1 rounded-full border border-cyan-500/30 text-cyan-300 animate-fade">
                    <span>Gün: <strong>{mousePos.step}</strong></span>
                    <span>Medyan: <strong>₺{Math.round(simResult.fan_cones.p50[mousePos.step] || 100000).toLocaleString("tr-TR")}</strong></span>
                    <span>Üst %95: <strong>₺{Math.round(simResult.fan_cones.p95[mousePos.step] || 100000).toLocaleString("tr-TR")}</strong></span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2.5 font-data text-xs text-zinc-400">
                    <span>Başlangıç: <strong className="text-white">₺100.000</strong></span>
                    <span className="text-emerald-400 font-semibold">● Canlı İmleç Aktif</span>
                  </div>
                )}
              </div>

              {/* Kanvas Alanı */}
              <div className="flex-1 w-full relative min-h-[400px] rounded-lg overflow-hidden border border-white/[0.06] bg-zinc-950/80">
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

              {/* Alt Bilgi & Gösterge (Legend) */}
              <div className="flex flex-wrap items-center justify-between text-[11px] text-zinc-400 pt-2 border-t border-white/[0.06] gap-2">
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-1 bg-cyan-400 inline-block rounded-full" />
                    <strong className="text-zinc-200">Medyan (p50)</strong>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 bg-cyan-500/20 border border-cyan-500/40 inline-block rounded" />
                    <span>%50 Güven Aralığı</span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 bg-emerald-500/10 border border-emerald-500/30 inline-block rounded" />
                    <span>%90 Güven Aralığı</span>
                  </span>
                  <span className="flex items-center gap-1.5 text-rose-400">
                    <span className="w-3 h-1 bg-rose-500 inline-block rounded-full" />
                    <span>Düşüş Patikaları</span>
                  </span>
                </div>

                <div className="font-data text-zinc-300 text-xs">
                  Seçili Kriz: <strong className="text-white">{activeScenarioObj.name}</strong>
                </div>
              </div>

            </div>

          </div>

        </div>
      </div>
    </ErrorBoundary>
  );
}
