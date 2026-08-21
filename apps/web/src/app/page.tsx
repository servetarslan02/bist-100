"use client";

import { usePolling, type MarketState, type Signal, type WorldState, type SystemStatus } from "@/lib/api";
import {
  TrendingUp, TrendingDown, Minus,
  Activity, Globe, BarChart2, AlertTriangle,
  ArrowUpRight, ArrowDownRight, Shield,
  Wifi, WifiOff, ChevronUp, ChevronDown,
  Target as TargetIcon
} from "lucide-react";

// ─── Mini SVG Sparkline ──────────────────────────────────────────────────────
function MiniSparkline({ value = 0, color = "#00e5a0" }: { value?: number; color?: string }) {
  const w = 48, h = 20;
  const points = Array.from({ length: 8 }, (_, i) => {
    const x = (i / 7) * w;
    const noise = (Math.sin(i * 2.3 + value) + 1) / 2;
    const y = h - noise * (h * 0.7) - h * 0.15;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg width={w} height={h} className="opacity-60">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ─── Stat Card ───────────────────────────────────────────────────────────────
function StatCard({
  label, value, suffix = "", decimals = 1,
  trend, icon: Icon, accent = "#00e5a0"
}: {
  label: string; value?: number; suffix?: string; decimals?: number;
  trend?: "up" | "down" | "neutral"; icon?: React.ElementType; accent?: string;
}) {
  const displayVal = value !== undefined ? value.toFixed(decimals) : "—";
  const trendColor = trend === "up" ? "#00e5a0" : trend === "down" ? "#ff4466" : "#8892a4";
  const TrendIcon = trend === "up" ? ChevronUp : trend === "down" ? ChevronDown : Minus;

  return (
    <div
      className="card-hover rounded-xl p-4 flex flex-col gap-3"
      style={{
        background: "var(--color-bg-card)",
        border: "1px solid var(--color-border-subtle)",
        borderTop: `1px solid ${accent}30`,
      }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>
          {label}
        </span>
        {Icon && (
          <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: `${accent}15` }}>
            <Icon size={12} style={{ color: accent }} />
          </div>
        )}
      </div>
      <div className="flex items-end justify-between">
        <span className="text-2xl font-bold font-data" style={{ color: "var(--color-text-primary)" }}>
          {displayVal}
          <span className="text-sm ml-0.5" style={{ color: "var(--color-text-secondary)" }}>{suffix}</span>
        </span>
        <div className="flex flex-col items-end gap-1">
          <MiniSparkline value={value || 0} color={accent} />
          {trend && (
            <div className="flex items-center gap-0.5">
              <TrendIcon size={10} style={{ color: trendColor }} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Signal Direction Badge ───────────────────────────────────────────────────
function DirBadge({ dir }: { dir: string }) {
  const up = dir === "LONG";
  return (
    <div
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold"
      style={{
        background: up ? "rgba(0,229,160,0.12)" : "rgba(255,68,102,0.12)",
        color: up ? "#00e5a0" : "#ff4466",
      }}
    >
      {up ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
      {dir}
    </div>
  );
}

// ─── Risk Badge ───────────────────────────────────────────────────────────────
function RiskBadge({ level }: { level: string }) {
  const cfg: Record<string, { bg: string; color: string }> = {
    LOW: { bg: "rgba(0,229,160,0.1)", color: "#00e5a0" },
    MEDIUM: { bg: "rgba(255,170,0,0.1)", color: "#ffaa00" },
    HIGH: { bg: "rgba(255,68,102,0.1)", color: "#ff4466" },
  };
  const c = cfg[level] ?? cfg.MEDIUM;
  return (
    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ background: c.bg, color: c.color }}>
      {level}
    </span>
  );
}

// ─── Score Bar ────────────────────────────────────────────────────────────────
function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? "#00e5a0" : score >= 60 ? "#ffaa00" : "#ff4466";
  return (
    <div className="flex items-center gap-2">
      <div className="w-12 h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className="text-[11px] font-data font-semibold" style={{ color }}>{score?.toFixed(0)}</span>
    </div>
  );
}

// ─── World Metric Row ─────────────────────────────────────────────────────────
function WorldMetric({ label, value, invert }: { label: string; value: number; invert: boolean }) {
  const pct = value * 100;
  const isGood = invert ? value < 0.4 : value > 0.6;
  const isBad = invert ? value > 0.7 : value < 0.3;
  const color = isGood ? "#00e5a0" : isBad ? "#ff4466" : "#ffaa00";
  return (
    <div className="flex items-center gap-3">
      <span className="text-[11px] w-24 flex-shrink-0" style={{ color: "var(--color-text-secondary)" }}>{label}</span>
      <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}80, ${color})` }}
        />
      </div>
      <span className="text-[10px] font-data w-8 text-right" style={{ color }}>{pct.toFixed(0)}%</span>
    </div>
  );
}

// ─── Service Health Row ────────────────────────────────────────────────────────
function ServiceRow({ name, health }: { name: string; health: string }) {
  const ok = health === "healthy";
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2">
        {ok ? <Wifi size={11} style={{ color: "#00e5a0" }} /> : <WifiOff size={11} style={{ color: "#ff4466" }} />}
        <span className="text-[11px] capitalize" style={{ color: "var(--color-text-secondary)" }}>
          {name.replace(/_/g, " ")}
        </span>
      </div>
      <span
        className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
        style={{
          background: ok ? "rgba(0,229,160,0.1)" : "rgba(255,68,102,0.1)",
          color: ok ? "#00e5a0" : "#ff4466",
        }}
      >
        {health}
      </span>
    </div>
  );
}

// ─── Section Header ────────────────────────────────────────────────────────────
function SectionHeader({ icon: Icon, title, sub, accent = "#00e5a0" }: {
  icon: React.ElementType; title: string; sub?: string; accent?: string;
}) {
  return (
    <div
      className="flex items-center justify-between px-5 py-3"
      style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
    >
      <div className="flex items-center gap-2.5">
        <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: `${accent}15` }}>
          <Icon size={13} style={{ color: accent }} />
        </div>
        <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>
          {title}
        </h2>
      </div>
      {sub && <span className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>{sub}</span>}
    </div>
  );
}

// ─── Regime Pill ─────────────────────────────────────────────────────────────
function RegimePill({ regime }: { regime?: string }) {
  if (!regime) return <span style={{ color: "var(--color-text-muted)" }}>—</span>;
  const up = regime.includes("UP") || regime.includes("EXPANSION") || regime.includes("BULL");
  const down = regime.includes("DOWN") || regime.includes("PANIC") || regime.includes("BEAR");
  const color = up ? "#00e5a0" : down ? "#ff4466" : "#ffaa00";
  const Icon = up ? TrendingUp : down ? TrendingDown : Minus;
  return (
    <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full"
      style={{ background: `${color}15`, border: `1px solid ${color}30` }}>
      <Icon size={11} style={{ color }} />
      <span className="text-[11px] font-bold" style={{ color }}>{regime}</span>
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────
export default function Overview() {
  const { data: market } = usePolling<MarketState>("/market/state", 15000);
  const { data: signals } = usePolling<Signal[]>("/signals?limit=10", 30000);
  const { data: world } = usePolling<WorldState>("/world/state", 30000);
  const { data: status } = usePolling<SystemStatus>("/status", 10000);

  const systemOk = status?.status === "ok";

  return (
    <div className="p-5 space-y-4 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>

      {/* ── Top Header ───────────────────────────────────────────── */}
      <div className="flex items-center justify-between py-1">
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-xl font-bold tracking-tight gradient-text">ALPHA BIST</h1>
            <p className="text-[10px] uppercase tracking-widest" style={{ color: "var(--color-text-muted)" }}>
              Market Intelligence Platform
            </p>
          </div>
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full"
            style={{ background: "rgba(0,229,160,0.08)", border: "1px solid rgba(0,229,160,0.15)" }}>
            <div className="w-1.5 h-1.5 rounded-full live-dot" style={{ background: "#00e5a0" }} />
            <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "#00e5a0" }}>Live</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-data" style={{ color: "var(--color-text-muted)" }}>
            {new Date().toLocaleTimeString("tr-TR")}
          </span>
          <div
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold"
            style={{
              background: systemOk ? "rgba(0,229,160,0.08)" : "rgba(255,68,102,0.08)",
              border: `1px solid ${systemOk ? "rgba(0,229,160,0.2)" : "rgba(255,68,102,0.2)"}`,
              color: systemOk ? "#00e5a0" : "#ff4466"
            }}
          >
            {systemOk ? <Shield size={11} /> : <AlertTriangle size={11} />}
            {systemOk ? "All Systems" : "Degraded"}
          </div>
        </div>
      </div>

      {/* ── Market State Bar ────────────────────────────────────────── */}
      <div
        className="rounded-xl p-4"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div className="grid grid-cols-6 gap-4">
          {/* Regime */}
          <div className="space-y-2">
            <p className="text-[9px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Regime</p>
            <RegimePill regime={market?.regime} />
          </div>
          {/* Breadth */}
          <div className="space-y-2">
            <p className="text-[9px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Breadth</p>
            <p className="text-xl font-bold font-data" style={{ color: "var(--color-text-primary)" }}>
              {market?.breadth_pct?.toFixed(1) ?? "—"}<span className="text-sm" style={{ color: "var(--color-text-secondary)" }}>%</span>
            </p>
          </div>
          {/* Adv/Dec */}
          <div className="space-y-2">
            <p className="text-[9px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Adv / Dec</p>
            <p className="text-lg font-bold font-data">
              <span style={{ color: "#00e5a0" }}>{market?.advancing ?? 0}</span>
              <span className="mx-1" style={{ color: "var(--color-text-faint)" }}>/</span>
              <span style={{ color: "#ff4466" }}>{market?.declining ?? 0}</span>
            </p>
          </div>
          {/* RSI */}
          <div className="space-y-2">
            <p className="text-[9px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Avg RSI</p>
            <p className="text-xl font-bold font-data"
              style={{
                color: (market?.avg_rsi ?? 50) > 70 ? "#ff4466" :
                  (market?.avg_rsi ?? 50) < 30 ? "#00e5a0" : "var(--color-text-primary)"
              }}>
              {market?.avg_rsi?.toFixed(1) ?? "—"}
            </p>
          </div>
          {/* Anomalies */}
          <div className="space-y-2">
            <p className="text-[9px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Anomalies</p>
            <p className="text-xl font-bold font-data"
              style={{ color: (market?.anomaly_count ?? 0) > 10 ? "#ffaa00" : "var(--color-text-primary)" }}>
              {market?.anomaly_count ?? 0}
            </p>
          </div>
          {/* Risk Appetite */}
          <div className="space-y-2">
            <p className="text-[9px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Risk Appetite</p>
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-data font-semibold" style={{ color: "#00e5a0" }}>
                  {((market?.risk_appetite ?? 0) * 100).toFixed(0)}%
                </span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{
                    width: `${(market?.risk_appetite ?? 0) * 100}%`,
                    background: "linear-gradient(90deg, #00e5a060, #00e5a0)"
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Stat Cards ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-5 gap-3">
        <StatCard
          label="Global Risk"
          value={(world?.global_risk_appetite ?? 0) * 100}
          suffix="%" decimals={0}
          icon={Globe}
          accent="#00c8ff"
          trend={world && world.global_risk_appetite > 0.6 ? "up" : "down"}
        />
        <StatCard
          label="VIX"
          value={world?.vix_level}
          decimals={1}
          icon={BarChart2}
          accent={world && world.vix_level > 25 ? "#ff4466" : "#00e5a0"}
          trend={world && world.vix_level > 25 ? "up" : "down"}
        />
        <StatCard
          label="USD Strength"
          value={(world?.usd_strength ?? 0) * 100}
          suffix="%" decimals={0}
          icon={TrendingUp}
          accent="#9966ff"
        />
        <StatCard
          label="Turkey Macro Risk"
          value={(world?.turkey_macro_risk ?? 0) * 100}
          suffix="%" decimals={0}
          icon={AlertTriangle}
          accent={world && world.turkey_macro_risk > 0.6 ? "#ff4466" : "#ffaa00"}
          trend={world && world.turkey_macro_risk > 0.6 ? "up" : "neutral"}
        />
        <StatCard
          label="Oil Pressure"
          value={(world?.oil_pressure ?? 0) * 100}
          suffix="%" decimals={0}
          icon={Activity}
          accent="#ffaa00"
        />
      </div>

      {/* ── Opportunity Engine ──────────────────────────────────────── */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <SectionHeader
          icon={TargetIcon}
          title="Opportunity Engine"
          sub={`${signals?.length ?? 0} active signals`}
          accent="#00e5a0"
        />

        {!signals || signals.length === 0 ? (
          <div className="py-12 text-center" style={{ color: "var(--color-text-muted)" }}>
            <TargetIcon size={24} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">No active signals</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider font-semibold"
                  style={{
                    color: "var(--color-text-muted)",
                    borderBottom: "1px solid var(--color-border-subtle)"
                  }}>
                  <th className="text-left py-2.5 px-5">Ticker</th>
                  <th className="text-left py-2.5 px-3">Name</th>
                  <th className="text-right py-2.5 px-3">Score</th>
                  <th className="text-center py-2.5 px-3">Dir</th>
                  <th className="text-center py-2.5 px-3">Risk</th>
                  <th className="text-center py-2.5 px-3">Horizon</th>
                  <th className="text-right py-2.5 px-5">Return</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s, i) => (
                  <tr
                    key={i}
                    className="row-hover cursor-pointer text-[12px]"
                    style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}
                  >
                    <td className="py-3 px-5">
                      <span className="font-bold font-data" style={{ color: "var(--color-text-primary)" }}>
                        {s.ticker}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      <span className="truncate max-w-[140px] block" style={{ color: "var(--color-text-secondary)" }}>
                        {s.name}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right">
                      <ScoreBar score={s.score ?? 0} />
                    </td>
                    <td className="py-3 px-3 text-center">
                      <DirBadge dir={s.direction} />
                    </td>
                    <td className="py-3 px-3 text-center">
                      <RiskBadge level={s.risk_level ?? "MEDIUM"} />
                    </td>
                    <td className="py-3 px-3 text-center">
                      <span className="text-[11px] font-data" style={{ color: "var(--color-text-secondary)" }}>
                        {s.horizon}
                      </span>
                    </td>
                    <td className="py-3 px-5 text-right">
                      <span
                        className="font-data font-semibold text-[13px]"
                        style={{ color: (s.expected_return_pct ?? 0) > 0 ? "#00e5a0" : "#ff4466" }}
                      >
                        {(s.expected_return_pct ?? 0) > 0 ? "+" : ""}{s.expected_return_pct?.toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Bottom Panels ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4">
        {/* System Health */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <SectionHeader icon={Activity} title="System Health" accent="#00c8ff" />
          <div className="px-5 py-3 divide-y" style={{ borderColor: "rgba(255,255,255,0.03)" }}>
            {status?.services && Object.entries(status.services).length > 0
              ? Object.entries(status.services).map(([name, health]) => (
                <ServiceRow key={name} name={name} health={health as string} />
              ))
              : (
                <p className="py-6 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
                  Loading...
                </p>
              )
            }
          </div>
        </div>

        {/* World State */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <SectionHeader icon={Globe} title="World State" accent="#9966ff" />
          <div className="px-5 py-4 space-y-4">
            {world ? [
              { label: "Geopolitical Risk", value: world.geopolitical_risk, invert: true },
              { label: "EM Risk Appetite", value: world.em_risk_appetite, invert: false },
              { label: "Inflation Pressure", value: world.inflation_pressure, invert: true },
              { label: "US Rate Pressure", value: world.us_rate_pressure, invert: true },
            ].map(f => (
              <WorldMetric key={f.label} label={f.label} value={f.value} invert={f.invert} />
            )) : (
              <p className="py-6 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
                Loading world state...
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
