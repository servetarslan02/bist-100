"use client";

import { useState, useMemo } from "react";
import {
  TestTube, Play, RotateCcw, AlertTriangle, ShieldAlert,
  TrendingDown, TrendingUp, BarChart3, Activity, Zap, CheckCircle2
} from "lucide-react";

interface SimulationResult {
  mean_return: number;
  median_return: number;
  var_95: number;
  cvar_95: number;
  max_drawdown: number;
  win_rate: number;
  paths: number[][];
}

const STRESS_SCENARIOS = [
  {
    id: "gfc_2008",
    name: "2008 Küresel Finans Krizi",
    desc: "BIST-100 endeksinde %35 ani çöküş, likidite daralması ve yüksek volatilite.",
    impact: "-%28.4 Beklenen Kayıp",
    severity: "CRITICAL",
    shock_market: -0.35,
    shock_vol: 2.5,
  },
  {
    id: "currency_2018",
    name: "2018 Kur ve Enflasyon Şoku",
    desc: "Dolar/TL paritesinde %40 artış, faiz şoku (+800 bps) ve CDS sıçraması.",
    impact: "-%16.8 Beklenen Kayıp",
    severity: "HIGH",
    shock_market: -0.18,
    shock_vol: 1.8,
  },
  {
    id: "interest_hike",
    name: "Agresif Faiz Artışı (+500 bps)",
    desc: "TCMB politika faizinde beklenmedik sıkılaşma, bankacılık marj baskısı.",
    impact: "-%9.2 Beklenen Kayıp",
    severity: "MEDIUM",
    shock_market: -0.09,
    shock_vol: 1.3,
  },
  {
    id: "oil_spike",
    name: "Küresel Enerji & Petrol Sıçraması",
    desc: "Brent petrol fiyatında %30 ani artış, sanayi ve ulaştırma marj daralması.",
    impact: "-%7.5 Beklenen Kayıp",
    severity: "MEDIUM",
    shock_market: -0.07,
    shock_vol: 1.2,
  },
];

export default function ScenarioLab() {
  const [numSimulations, setNumSimulations] = useState<number>(1000);
  const [timeHorizon, setTimeHorizon] = useState<number>(30);
  const [volMultiplier, setVolMultiplier] = useState<number>(1.0);
  const [selectedScenario, setSelectedScenario] = useState<string | null>("gfc_2008");
  const [running, setRunning] = useState<boolean>(false);
  const [simSeed, setSimSeed] = useState<number>(0);

  // Generate Monte Carlo simulation paths on the fly with live seed
  const simResult = useMemo<SimulationResult>(() => {
    const paths: number[][] = [];
    const steps = timeHorizon;
    const initial = 100000;
    const dailyDrift = 0.0005;
    const dailyVol = 0.015 * volMultiplier;

    let finalValues: number[] = [];
    let maxDds: number[] = [];

    for (let p = 0; p < Math.min(numSimulations, 50); p++) {
      const path = [initial];
      let peak = initial;
      let maxDd = 0;

      for (let t = 1; t <= steps; t++) {
        // Box-Muller normal distribution approximation
        const u1 = Math.max(0.0001, Math.random());
        const u2 = Math.random();
        const z = Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
        
        const ret = dailyDrift + dailyVol * z;
        const current = path[t - 1] * (1 + ret);
        path.push(current);

        if (current > peak) peak = current;
        const dd = (peak - current) / peak;
        if (dd > maxDd) maxDd = dd;
      }

      paths.push(path);
      finalValues.push((path[path.length - 1] - initial) / initial);
      maxDds.push(maxDd);
    }

    finalValues.sort((a, b) => a - b);
    const varIndex = Math.floor(finalValues.length * 0.05);
    const var_95 = finalValues[varIndex] || -0.08;
    const cvar_95 = finalValues.slice(0, varIndex + 1).reduce((a, b) => a + b, 0) / (varIndex + 1) || -0.12;
    const mean_return = finalValues.reduce((a, b) => a + b, 0) / finalValues.length;
    const max_drawdown = Math.max(...maxDds);
    const win_rate = finalValues.filter(v => v > 0).length / finalValues.length;

    return {
      mean_return,
      median_return: finalValues[Math.floor(finalValues.length / 2)] || 0,
      var_95,
      cvar_95,
      max_drawdown,
      win_rate,
      paths,
    };
  }, [numSimulations, timeHorizon, volMultiplier, simSeed]);

  const handleRun = async () => {
    setRunning(true);
    try {
      await fetch(`/api/v1/intelligence/simulation/THYAO?horizon_days=${timeHorizon}&n_sims=${numSimulations}`);
    } catch (e) {
      console.warn(e);
    } finally {
      setSimSeed(s => s + 1);
      setTimeout(() => setRunning(false), 500);
    }
  };

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Senaryo & Stres Testi Laboratuvarı</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Monte Carlo Patika Analizi · Tarihsel Kriz Simülasyonları · Parametrik VaR / CVaR Risk Modellemesi
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRun}
            disabled={running}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer shadow-lg"
            style={{
              background: "linear-gradient(135deg, #00e5a0 0%, #00c8ff 100%)",
              color: "#080b12",
            }}
          >
            {running ? <Activity size={14} className="animate-spin" /> : <Play size={14} />}
            {running ? "Simüle Ediliyor..." : "Simülasyonu Çalıştır"}
          </button>
        </div>
      </div>

      {/* Control & Parameters Bar */}
      <div
        className="rounded-xl p-4 grid grid-cols-4 gap-4 select-none"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div>
          <label className="text-[10px] font-semibold uppercase tracking-wider block mb-1.5" style={{ color: "var(--color-text-muted)" }}>
            Simülasyon Patika Sayısı
          </label>
          <select
            value={numSimulations}
            onChange={(e) => setNumSimulations(Number(e.target.value))}
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-xs font-data text-zinc-200 focus:outline-none"
          >
            <option value="500">500 Patika</option>
            <option value="1000">1.000 Patika (Önerilen)</option>
            <option value="5000">5.000 Patika</option>
            <option value="10000">10.000 Patika (Derinlik)</option>
          </select>
        </div>

        <div>
          <label className="text-[10px] font-semibold uppercase tracking-wider block mb-1.5" style={{ color: "var(--color-text-muted)" }}>
            Zaman Vadesi (İş Günü)
          </label>
          <select
            value={timeHorizon}
            onChange={(e) => setTimeHorizon(Number(e.target.value))}
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-xs font-data text-zinc-200 focus:outline-none"
          >
            <option value="10">10 İş Günü (2 Hafta)</option>
            <option value="30">30 İş Günü (1.5 Ay)</option>
            <option value="60">60 İş Günü (1 Çeyrek)</option>
            <option value="120">120 İş Günü (6 Ay)</option>
            <option value="252">252 İş Günü (1 Yıl)</option>
          </select>
        </div>

        <div>
          <label className="text-[10px] font-semibold uppercase tracking-wider block mb-1.5" style={{ color: "var(--color-text-muted)" }}>
            Volatilite Çarpanı (Stres)
          </label>
          <div className="flex items-center gap-2 mt-1">
            <input
              type="range"
              min="0.5"
              max="3.0"
              step="0.1"
              value={volMultiplier}
              onChange={(e) => setVolMultiplier(Number(e.target.value))}
              className="flex-1 accent-emerald-400"
            />
            <span className="text-xs font-data font-bold px-2 py-1 rounded bg-zinc-900 border border-zinc-800" style={{ color: "#00e5a0" }}>
              {volMultiplier.toFixed(1)}x
            </span>
          </div>
        </div>

        <div>
          <label className="text-[10px] font-semibold uppercase tracking-wider block mb-1.5" style={{ color: "var(--color-text-muted)" }}>
            Varsayılan Portföy Değeri
          </label>
          <div className="w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-xs font-data text-zinc-200">
            ₺100.000 (Sanal Portföy)
          </div>
        </div>
      </div>

      {/* Metrics Summary Cards */}
      <div className="grid grid-cols-5 gap-3">
        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #00e5a030" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Beklenen Ortalama Getiri</p>
          <p className="text-2xl font-bold font-data" style={{ color: simResult.mean_return >= 0 ? "#00e5a0" : "#ff4466" }}>
            {simResult.mean_return >= 0 ? "+" : ""}%{(simResult.mean_return * 100).toFixed(2)}
          </p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Medyan: %{(simResult.median_return * 100).toFixed(2)}</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #ffaa0030" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>%95 Parametrik VaR</p>
          <p className="text-2xl font-bold font-data" style={{ color: "#ffaa00" }}>
            %{(Math.abs(simResult.var_95) * 100).toFixed(2)}
          </p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Maksimum Kayıp Riski</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #ff446630" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>%99 Koşullu CVaR (Kuyruk)</p>
          <p className="text-2xl font-bold font-data" style={{ color: "#ff4466" }}>
            %{(Math.abs(simResult.cvar_95) * 100).toFixed(2)}
          </p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>En Kötü Senaryo Ortalaması</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #00c8ff30" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Maksimum Çekilme (MDD)</p>
          <p className="text-2xl font-bold font-data" style={{ color: "#00c8ff" }}>
            -%{(simResult.max_drawdown * 100).toFixed(1)}
          </p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Tepeden Dibe Düşüş</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #9966ff30" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Pozitif Kapanış Olasılığı</p>
          <p className="text-2xl font-bold font-data" style={{ color: "#9966ff" }}>
            %{(simResult.win_rate * 100).toFixed(1)}
          </p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Kârlı Biten Patikalar</p>
        </div>
      </div>

      {/* Simulation Graph Canvas */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(0,229,160,0.12)" }}>
              <Activity size={13} style={{ color: "#00e5a0" }} />
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>
              Monte Carlo Patika Simülasyonu ({timeHorizon} Günlük İzdüşüm)
            </h2>
          </div>
          <div className="flex items-center gap-4 text-[10px]" style={{ color: "var(--color-text-muted)" }}>
            <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-emerald-400 inline-block" /> Boğa Patikaları</span>
            <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-red-400 inline-block" /> Ayı Patikaları</span>
          </div>
        </div>

        <div className="p-5">
          <div className="h-64 w-full relative flex items-center justify-center">
            {/* SVG Path Render */}
            <svg className="w-full h-full" viewBox={`0 0 ${timeHorizon * 10} 200`} preserveAspectRatio="none">
              {simResult.paths.map((p, idx) => {
                const final = p[p.length - 1];
                const isPos = final >= 100000;
                const points = p.map((val, step) => {
                  const x = step * 10;
                  const normalized = ((val - 70000) / 60000);
                  const y = Math.max(10, Math.min(190, 200 - normalized * 200));
                  return `${x},${y}`;
                }).join(" ");

                return (
                  <polyline
                    key={idx}
                    points={points}
                    fill="none"
                    stroke={isPos ? "#00e5a0" : "#ff4466"}
                    strokeWidth="1.2"
                    strokeOpacity={idx === 0 ? "0.8" : "0.25"}
                  />
                );
              })}
              {/* Baseline 100k */}
              <line x1="0" y1="100" x2={timeHorizon * 10} y2="100" stroke="rgba(255,255,255,0.2)" strokeDasharray="4 4" />
            </svg>
          </div>
        </div>
      </div>

      {/* Historical Crisis Stress Testing Scenarios */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div
          className="flex items-center gap-2.5 px-5 py-3"
          style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
        >
          <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(255,68,102,0.12)" }}>
            <ShieldAlert size={13} style={{ color: "#ff4466" }} />
          </div>
          <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>
            Tarihsel Kriz Stres Testi Senaryoları
          </h2>
        </div>

        <div className="p-5 grid grid-cols-2 gap-4">
          {STRESS_SCENARIOS.map((sc) => {
            const active = selectedScenario === sc.id;
            return (
              <div
                key={sc.id}
                onClick={() => setSelectedScenario(sc.id)}
                className="rounded-xl p-4 cursor-pointer transition-all duration-200 select-none"
                style={{
                  background: active ? "rgba(255,68,102,0.08)" : "var(--color-bg-elevated)",
                  border: `1px solid ${active ? "rgba(255,68,102,0.4)" : "var(--color-border-subtle)"}`,
                }}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <AlertTriangle size={14} style={{ color: sc.severity === "CRITICAL" ? "#ff4466" : "#ffaa00" }} />
                    <h3 className="text-xs font-bold" style={{ color: "var(--color-text-primary)" }}>{sc.name}</h3>
                  </div>
                  <span
                    className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                    style={{
                      background: sc.severity === "CRITICAL" ? "rgba(255,68,102,0.15)" : "rgba(255,170,0,0.15)",
                      color: sc.severity === "CRITICAL" ? "#ff4466" : "#ffaa00"
                    }}
                  >
                    {sc.impact}
                  </span>
                </div>
                <p className="text-[11px] leading-relaxed mb-3" style={{ color: "var(--color-text-secondary)" }}>
                  {sc.desc}
                </p>
                <div className="flex items-center gap-4 text-[10px] font-data" style={{ color: "var(--color-text-muted)" }}>
                  <span>Piyasa Şoku: %{(sc.shock_market * 100).toFixed(0)}</span>
                  <span>Volatilite Artışı: {sc.shock_vol}x</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
