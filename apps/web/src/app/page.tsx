"use client";

import { useEffect, useState } from "react";

interface MarketState {
  regime: string;
  breadth_pct: number;
  advancing: number;
  declining: number;
  avg_rsi: number;
  anomaly_count: number;
  risk_appetite: number;
}

interface Signal {
  ticker: string;
  name: string;
  score: number;
  direction: string;
  risk_level: string;
  horizon: string;
}

export default function Overview() {
  const [marketState, setMarketState] = useState<MarketState | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  async function fetchData() {
    try {
      const [stateRes, signalsRes] = await Promise.all([
        fetch("/api/market/state"),
        fetch("/api/signals?limit=10"),
      ]);

      if (stateRes.ok) setMarketState(await stateRes.json());
      if (signalsRes.ok) setSignals(await signalsRes.json());
    } catch (e) {
      console.error("Failed to fetch data:", e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">ALPHA BIST</h1>
          <p className="text-sm text-alpha-muted">Market Intelligence & Quant Engine</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-alpha-accent live-indicator" />
            <span className="text-sm">LIVE</span>
          </div>
          <span className="text-sm text-alpha-muted">
            {new Date().toLocaleTimeString("tr-TR")}
          </span>
        </div>
      </div>

      {/* Market State Cards */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        <StatCard
          label="REGIME"
          value={marketState?.regime || "—"}
          color={getRegimeColor(marketState?.regime)}
        />
        <StatCard
          label="BREADTH"
          value={`${marketState?.breadth_pct?.toFixed(1) || "—"}%`}
          color={marketState && marketState.breadth_pct > 50 ? "text-alpha-accent" : "text-alpha-danger"}
        />
        <StatCard
          label="ADV / DEC"
          value={`${marketState?.advancing || 0} / ${marketState?.declining || 0}`}
          color="text-alpha-text"
        />
        <StatCard
          label="AVG RSI"
          value={marketState?.avg_rsi?.toFixed(1) || "—"}
          color={getRSIColor(marketState?.avg_rsi)}
        />
        <StatCard
          label="ANOMALIES"
          value={String(marketState?.anomaly_count || 0)}
          color={marketState && marketState.anomaly_count > 5 ? "text-alpha-warning" : "text-alpha-text"}
        />
      </div>

      {/* Opportunity Radar */}
      <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4 mb-6">
        <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <span className="text-alpha-accent">●</span> OPPORTUNITY ENGINE
        </h2>

        {loading ? (
          <div className="text-alpha-muted text-sm py-8 text-center">Loading...</div>
        ) : signals.length === 0 ? (
          <div className="text-alpha-muted text-sm py-8 text-center">No active signals</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-alpha-muted border-b border-alpha-border">
                <th className="text-left py-2 px-2">TICKER</th>
                <th className="text-left py-2 px-2">NAME</th>
                <th className="text-right py-2 px-2">SCORE</th>
                <th className="text-center py-2 px-2">DIR</th>
                <th className="text-center py-2 px-2">RISK</th>
                <th className="text-center py-2 px-2">HORIZON</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s, i) => (
                <tr key={i} className="border-b border-alpha-border/50 hover:bg-alpha-border/30">
                  <td className="py-2 px-2 font-semibold text-alpha-accent">{s.ticker}</td>
                  <td className="py-2 px-2 text-alpha-muted">{s.name}</td>
                  <td className="py-2 px-2 text-right font-mono">{s.score?.toFixed(0)}</td>
                  <td className="py-2 px-2 text-center">
                    <span className={s.direction === "LONG" ? "text-alpha-accent" : "text-alpha-danger"}>
                      {s.direction}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-center">
                    <RiskBadge level={s.risk_level} />
                  </td>
                  <td className="py-2 px-2 text-center text-alpha-muted">{s.horizon}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <h3 className="text-xs text-alpha-muted uppercase mb-2">Risk Appetite</h3>
          <div className="text-2xl font-bold">
            {marketState ? (marketState.risk_appetite * 100).toFixed(0) : "—"}%
          </div>
          <div className="w-full bg-alpha-border rounded-full h-2 mt-2">
            <div
              className="bg-alpha-accent h-2 rounded-full transition-all"
              style={{ width: `${(marketState?.risk_appetite || 0) * 100}%` }}
            />
          </div>
        </div>

        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <h3 className="text-xs text-alpha-muted uppercase mb-2">System Status</h3>
          <div className="space-y-1 text-sm">
            <StatusRow label="Data Feed" status="ok" />
            <StatusRow label="ML Engine" status="ok" />
            <StatusRow label="AI Service" status="ok" />
            <StatusRow label="Risk Gate" status="ok" />
          </div>
        </div>

        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <h3 className="text-xs text-alpha-muted uppercase mb-2">Live Intelligence</h3>
          <div className="text-sm text-alpha-muted">
            <p>Monitoring 800+ BIST instruments</p>
            <p className="mt-1">Last update: {new Date().toLocaleTimeString("tr-TR")}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-alpha-surface border border-alpha-border rounded-lg p-3">
      <p className="text-xs text-alpha-muted uppercase">{label}</p>
      <p className={`text-lg font-bold mt-1 ${color}`}>{value}</p>
    </div>
  );
}

function RiskBadge({ level }: { level: string }) {
  const colors: Record<string, string> = {
    LOW: "bg-green-900/30 text-green-400",
    MEDIUM: "bg-yellow-900/30 text-yellow-400",
    HIGH: "bg-red-900/30 text-red-400",
    CRITICAL: "bg-red-900/50 text-red-300",
  };

  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors[level] || colors.MEDIUM}`}>
      {level}
    </span>
  );
}

function StatusRow({ label, status }: { label: string; status: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-alpha-muted">{label}</span>
      <span className={status === "ok" ? "text-alpha-accent" : "text-alpha-danger"}>
        {status === "ok" ? "●" : "○"}
      </span>
    </div>
  );
}

function getRegimeColor(regime?: string): string {
  if (!regime) return "text-alpha-muted";
  if (regime.includes("UP") || regime.includes("EXPANSION")) return "text-alpha-accent";
  if (regime.includes("DOWN") || regime.includes("PANIC")) return "text-alpha-danger";
  if (regime.includes("HIGH")) return "text-alpha-warning";
  return "text-alpha-text";
}

function getRSIColor(rsi?: number): string {
  if (!rsi) return "text-alpha-muted";
  if (rsi > 70) return "text-alpha-danger";
  if (rsi < 30) return "text-alpha-accent";
  return "text-alpha-text";
}
