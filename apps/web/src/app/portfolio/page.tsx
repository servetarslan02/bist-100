"use client";

import { usePolling, type PortfolioData } from "@/lib/api";
import { StatCard } from "@/components/ui/StatCard";

export default function PortfolioPage() {
  const { data, loading } = usePolling<PortfolioData>("/portfolio", 15000);
  const p = data?.portfolio;

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Portfolio</h1>
          <p className="text-[11px] text-zinc-600">Paper trading • {data?.positions?.length || 0} positions</p>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-5 gap-3">
        <StatCard label="CAPITAL" value={p?.current_capital || 0} decimals={0} prefix="₺" size="sm" />
        <StatCard label="INVESTED" value={p?.invested_value || 0} decimals={0} prefix="₺" size="sm" />
        <StatCard label="CASH" value={p?.cash_balance || 0} decimals={0} prefix="₺" size="sm" />
        <StatCard label="P&L" value={p?.total_pnl || 0} decimals={0} prefix="₺" color="auto" size="sm" />
        <StatCard label="RETURN" value={p?.total_return_pct || 0} decimals={2} suffix="%" color="auto" size="sm" />
      </div>

      {/* Positions */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg overflow-hidden">
        <div className="px-4 py-2.5 border-b border-zinc-800/60">
          <h2 className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">Positions</h2>
        </div>

        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800/40 bg-zinc-950/50">
              <th className="text-left py-1.5 px-3 font-medium">TICKER</th>
              <th className="text-left py-1.5 px-3 font-medium">NAME</th>
              <th className="text-right py-1.5 px-3 font-medium">QTY</th>
              <th className="text-right py-1.5 px-3 font-medium">AVG COST</th>
              <th className="text-right py-1.5 px-3 font-medium">CURRENT</th>
              <th className="text-right py-1.5 px-3 font-medium">VALUE</th>
              <th className="text-right py-1.5 px-3 font-medium">P&L</th>
              <th className="text-right py-1.5 px-3 font-medium">P&L%</th>
              <th className="text-right py-1.5 px-3 font-medium">WEIGHT</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="text-center py-12 text-zinc-600">Loading...</td></tr>
            ) : !data || data.positions.length === 0 ? (
              <tr><td colSpan={9} className="text-center py-12 text-zinc-600">No positions</td></tr>
            ) : (
              data.positions.map((pos, i) => (
                <tr key={i} className="border-b border-zinc-800/20 row-hover cursor-pointer">
                  <td className="py-1.5 px-3 font-semibold text-zinc-200">{pos.ticker}</td>
                  <td className="py-1.5 px-3 text-zinc-500 truncate max-w-[120px]">{pos.name}</td>
                  <td className="py-1.5 px-3 text-right font-mono text-zinc-300">{pos.quantity}</td>
                  <td className="py-1.5 px-3 text-right font-mono text-zinc-400">₺{pos.avg_cost?.toFixed(2)}</td>
                  <td className="py-1.5 px-3 text-right font-mono text-zinc-300">₺{pos.current_price?.toFixed(2)}</td>
                  <td className="py-1.5 px-3 text-right font-mono text-zinc-300">₺{pos.market_value?.toLocaleString()}</td>
                  <td className={`py-1.5 px-3 text-right font-mono ${pos.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    ₺{pos.unrealized_pnl?.toLocaleString()}
                  </td>
                  <td className={`py-1.5 px-3 text-right font-mono ${pos.unrealized_pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {pos.unrealized_pnl_pct?.toFixed(2)}%
                  </td>
                  <td className="py-1.5 px-3 text-right font-mono text-zinc-400">{pos.weight_pct?.toFixed(1)}%</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
