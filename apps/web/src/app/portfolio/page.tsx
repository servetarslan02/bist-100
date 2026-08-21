"use client";

import { usePolling, type PortfolioData } from "@/lib/api";
import { Briefcase, TrendingUp, TrendingDown, DollarSign, Wallet, PieChart, ArrowUpRight, ArrowDownRight } from "lucide-react";

function MetricCard({ label, value, prefix = "", suffix = "", color }: {
  label: string; value?: number; prefix?: string; suffix?: string; color?: string;
}) {
  const isPos = (value ?? 0) >= 0;
  const accent = color === "auto" ? (isPos ? "#00e5a0" : "#ff4466") : color ?? "#00c8ff";
  return (
    <div
      className="rounded-xl p-4 space-y-2"
      style={{
        background: "var(--color-bg-card)",
        border: "1px solid var(--color-border-subtle)",
        borderTop: `1px solid ${accent}30`,
      }}
    >
      <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>
        {label}
      </p>
      <p className="text-2xl font-bold font-data" style={{ color: value === undefined ? "var(--color-text-muted)" : accent }}>
        {prefix}{value !== undefined ? value.toLocaleString("tr-TR", { maximumFractionDigits: 0 }) : "—"}{suffix}
      </p>
    </div>
  );
}

export default function PortfolioPage() {
  const { data, loading } = usePolling<PortfolioData>("/portfolio", 15000);
  const p = data?.portfolio;
  const positions = data?.positions ?? [];
  const totalPnlPos = (p?.total_pnl ?? 0) >= 0;

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Portfolio</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Paper trading · {positions.length} positions
          </p>
        </div>
        <div
          className="flex items-center gap-2 px-4 py-2 rounded-xl"
          style={{
            background: totalPnlPos ? "rgba(0,229,160,0.08)" : "rgba(255,68,102,0.08)",
            border: `1px solid ${totalPnlPos ? "rgba(0,229,160,0.2)" : "rgba(255,68,102,0.2)"}`,
          }}
        >
          {totalPnlPos ? <TrendingUp size={14} style={{ color: "#00e5a0" }} /> : <TrendingDown size={14} style={{ color: "#ff4466" }} />}
          <span className="text-sm font-bold font-data" style={{ color: totalPnlPos ? "#00e5a0" : "#ff4466" }}>
            {totalPnlPos ? "+" : ""}₺{(p?.total_pnl ?? 0).toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
          </span>
          <span className="text-xs font-data" style={{ color: "var(--color-text-secondary)" }}>
            ({totalPnlPos ? "+" : ""}{(p?.total_return_pct ?? 0).toFixed(2)}%)
          </span>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-5 gap-3">
        <MetricCard label="Capital" value={p?.current_capital} prefix="₺" accent="#00c8ff" />
        <MetricCard label="Invested" value={p?.invested_value} prefix="₺" accent="#9966ff" />
        <MetricCard label="Cash" value={p?.cash_balance} prefix="₺" accent="#ffaa00" />
        <MetricCard label="P&L" value={p?.total_pnl} prefix="₺" color="auto" />
        <MetricCard label="Return" value={p?.total_return_pct} suffix="%" color="auto" />
      </div>

      {/* Positions Table */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(0,200,255,0.12)" }}>
              <Briefcase size={13} style={{ color: "#00c8ff" }} />
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>
              Positions
            </h2>
          </div>
          <span className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>{positions.length} holdings</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr
                className="text-[10px] uppercase tracking-wider"
                style={{
                  color: "var(--color-text-muted)",
                  borderBottom: "1px solid var(--color-border-subtle)",
                  background: "rgba(255,255,255,0.01)"
                }}
              >
                <th className="text-left py-3 px-5">Ticker</th>
                <th className="text-left py-3 px-3">Name</th>
                <th className="text-right py-3 px-3">Qty</th>
                <th className="text-right py-3 px-3">Avg Cost</th>
                <th className="text-right py-3 px-3">Current</th>
                <th className="text-right py-3 px-3">Value</th>
                <th className="text-right py-3 px-3">P&L</th>
                <th className="text-right py-3 px-3">P&L%</th>
                <th className="text-right py-3 px-5">Weight</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="text-center py-16" style={{ color: "var(--color-text-muted)" }}>Loading...</td></tr>
              ) : positions.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-16">
                    <Wallet size={28} className="mx-auto mb-3" style={{ color: "var(--color-text-faint)" }} />
                    <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>No positions yet</p>
                  </td>
                </tr>
              ) : (
                positions.map((pos, i) => {
                  const pnlPos = (pos.unrealized_pnl ?? 0) >= 0;
                  return (
                    <tr
                      key={i}
                      className="row-hover cursor-pointer text-[12px]"
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}
                    >
                      <td className="py-3 px-5">
                        <span className="font-bold font-data" style={{ color: "var(--color-text-primary)" }}>{pos.ticker}</span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="truncate max-w-[120px] block text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
                          {pos.name}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-right font-data" style={{ color: "var(--color-text-primary)" }}>
                        {pos.quantity}
                      </td>
                      <td className="py-3 px-3 text-right font-data" style={{ color: "var(--color-text-secondary)" }}>
                        ₺{pos.avg_cost?.toFixed(2)}
                      </td>
                      <td className="py-3 px-3 text-right font-data" style={{ color: "var(--color-text-primary)" }}>
                        ₺{pos.current_price?.toFixed(2)}
                      </td>
                      <td className="py-3 px-3 text-right font-data" style={{ color: "var(--color-text-primary)" }}>
                        ₺{pos.market_value?.toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {pnlPos ? <ArrowUpRight size={11} style={{ color: "#00e5a0" }} /> : <ArrowDownRight size={11} style={{ color: "#ff4466" }} />}
                          <span className="font-data font-semibold" style={{ color: pnlPos ? "#00e5a0" : "#ff4466" }}>
                            ₺{pos.unrealized_pnl?.toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-3 text-right">
                        <span className="font-data font-semibold" style={{ color: pnlPos ? "#00e5a0" : "#ff4466" }}>
                          {pnlPos ? "+" : ""}{pos.unrealized_pnl_pct?.toFixed(2)}%
                        </span>
                      </td>
                      <td className="py-3 px-5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-12 h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
                            <div className="h-full rounded-full" style={{ width: `${pos.weight_pct ?? 0}%`, background: "#00c8ff" }} />
                          </div>
                          <span className="font-data text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
                            {pos.weight_pct?.toFixed(1)}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
