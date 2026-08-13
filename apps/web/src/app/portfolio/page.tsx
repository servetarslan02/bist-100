"use client";

import { useEffect, useState } from "react";

interface Position {
  ticker: string;
  name: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  weight_pct: number;
}

interface PortfolioData {
  portfolio: {
    id: number;
    name: string;
    initial_capital: number;
    current_capital: number;
    cash_balance: number;
    invested_value: number;
    total_pnl: number;
    total_return_pct: number;
  };
  positions: Position[];
}

export default function PortfolioPage() {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPortfolio();
    const interval = setInterval(fetchPortfolio, 30000);
    return () => clearInterval(interval);
  }, []);

  async function fetchPortfolio() {
    try {
      const res = await fetch("/api/portfolio");
      if (res.ok) {
        setData(await res.json());
      }
    } catch (e) {
      console.error("Failed to fetch portfolio:", e);
    } finally {
      setLoading(false);
    }
  }

  const p = data?.portfolio;

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Portfolio</h1>

      {/* Summary Cards */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        <Card label="CAPITAL" value={formatCurrency(p?.current_capital)} />
        <Card label="INVESTED" value={formatCurrency(p?.invested_value)} />
        <Card label="CASH" value={formatCurrency(p?.cash_balance)} />
        <Card
          label="P&L"
          value={formatCurrency(p?.total_pnl)}
          color={p && p.total_pnl >= 0 ? "text-alpha-accent" : "text-alpha-danger"}
        />
        <Card
          label="RETURN"
          value={`${p?.total_return_pct?.toFixed(2) || "0.00"}%`}
          color={p && p.total_return_pct >= 0 ? "text-alpha-accent" : "text-alpha-danger"}
        />
      </div>

      {/* Positions Table */}
      <div className="bg-alpha-surface border border-alpha-border rounded-lg overflow-hidden">
        <div className="p-4 border-b border-alpha-border">
          <h2 className="text-sm font-semibold">Positions</h2>
        </div>

        <table className="w-full text-sm">
          <thead>
            <tr className="text-alpha-muted border-b border-alpha-border bg-alpha-bg/50">
              <th className="text-left py-2 px-3">TICKER</th>
              <th className="text-left py-2 px-3">NAME</th>
              <th className="text-right py-2 px-3">QTY</th>
              <th className="text-right py-2 px-3">AVG COST</th>
              <th className="text-right py-2 px-3">CURRENT</th>
              <th className="text-right py-2 px-3">VALUE</th>
              <th className="text-right py-2 px-3">P&L</th>
              <th className="text-right py-2 px-3">P&L %</th>
              <th className="text-right py-2 px-3">WEIGHT</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="text-center py-8 text-alpha-muted">Loading...</td></tr>
            ) : !data || data.positions.length === 0 ? (
              <tr><td colSpan={9} className="text-center py-8 text-alpha-muted">No positions</td></tr>
            ) : (
              data.positions.map((pos, i) => (
                <tr key={i} className="border-b border-alpha-border/30 hover:bg-alpha-border/20">
                  <td className="py-2 px-3 font-semibold text-alpha-accent">{pos.ticker}</td>
                  <td className="py-2 px-3 text-alpha-muted truncate max-w-[150px]">{pos.name}</td>
                  <td className="py-2 px-3 text-right font-mono">{pos.quantity}</td>
                  <td className="py-2 px-3 text-right font-mono">{pos.avg_cost?.toFixed(2)}</td>
                  <td className="py-2 px-3 text-right font-mono">{pos.current_price?.toFixed(2)}</td>
                  <td className="py-2 px-3 text-right font-mono">{formatCurrency(pos.market_value)}</td>
                  <td className={`py-2 px-3 text-right font-mono ${pos.unrealized_pnl >= 0 ? "text-alpha-accent" : "text-alpha-danger"}`}>
                    {formatCurrency(pos.unrealized_pnl)}
                  </td>
                  <td className={`py-2 px-3 text-right font-mono ${pos.unrealized_pnl_pct >= 0 ? "text-alpha-accent" : "text-alpha-danger"}`}>
                    {pos.unrealized_pnl_pct?.toFixed(2)}%
                  </td>
                  <td className="py-2 px-3 text-right font-mono">{pos.weight_pct?.toFixed(1)}%</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Card({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-alpha-surface border border-alpha-border rounded-lg p-3">
      <p className="text-xs text-alpha-muted uppercase">{label}</p>
      <p className={`text-lg font-bold mt-1 ${color || "text-alpha-text"}`}>{value}</p>
    </div>
  );
}

function formatCurrency(val?: number): string {
  if (val === undefined || val === null) return "—";
  return new Intl.NumberFormat("tr-TR", {
    style: "currency",
    currency: "TRY",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(val);
}
