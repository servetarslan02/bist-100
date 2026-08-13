"use client";

import { useEffect, useState } from "react";

interface Opportunity {
  ticker: string;
  name: string;
  score: number;
  direction: string;
  risk_level: string;
  horizon: string;
  expected_return_pct: number;
  spec_category: string;
}

export default function Opportunities() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("ALL");

  useEffect(() => {
    async function fetch() {
      try {
        const res = await fetch("/api/signals?limit=50");
        if (res.ok) setOpportunities(await res.json());
      } catch {}
      setLoading(false);
    }
    fetch();
    const interval = setInterval(fetch, 30000);
    return () => clearInterval(interval);
  }, []);

  const filtered = filter === "ALL" ? opportunities :
    opportunities.filter(o => o.spec_category === filter);

  const categories = ["ALL", "HIGH_CONVICTION", "CANDIDATE", "WATCH"];

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-2">Opportunities</h1>
      <p className="text-sm text-alpha-muted mb-6">SPEC, Momentum, Breakout, Value, Event Driven</p>

      <div className="flex gap-2 mb-4">
        {categories.map(c => (
          <button
            key={c}
            onClick={() => setFilter(c)}
            className={`px-3 py-1.5 text-xs rounded transition-colors ${
              filter === c
                ? "bg-alpha-accent text-alpha-bg"
                : "bg-alpha-surface border border-alpha-border text-alpha-muted hover:text-alpha-text"
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      <div className="bg-alpha-surface border border-alpha-border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-alpha-muted border-b border-alpha-border bg-alpha-bg/50">
              <th className="text-left py-2 px-3">TICKER</th>
              <th className="text-left py-2 px-3">NAME</th>
              <th className="text-right py-2 px-3">SCORE</th>
              <th className="text-center py-2 px-3">DIR</th>
              <th className="text-center py-2 px-3">RISK</th>
              <th className="text-center py-2 px-3">HORIZON</th>
              <th className="text-right py-2 px-3">EXP RET</th>
              <th className="text-center py-2 px-3">CATEGORY</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="text-center py-8 text-alpha-muted">Loading...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={8} className="text-center py-8 text-alpha-muted">No opportunities found</td></tr>
            ) : (
              filtered.map((o, i) => (
                <tr key={i} className="border-b border-alpha-border/30 hover:bg-alpha-border/20 cursor-pointer">
                  <td className="py-2 px-3 font-semibold text-alpha-accent">{o.ticker}</td>
                  <td className="py-2 px-3 text-alpha-muted truncate max-w-[150px]">{o.name}</td>
                  <td className="py-2 px-3 text-right font-mono font-bold">{o.score?.toFixed(0)}</td>
                  <td className="py-2 px-3 text-center">
                    <span className={o.direction === "LONG" ? "text-alpha-accent" : "text-alpha-danger"}>
                      {o.direction}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-center">
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      o.risk_level === "LOW" ? "bg-green-900/30 text-green-400" :
                      o.risk_level === "HIGH" ? "bg-red-900/30 text-red-400" :
                      "bg-yellow-900/30 text-yellow-400"
                    }`}>{o.risk_level}</span>
                  </td>
                  <td className="py-2 px-3 text-center text-alpha-muted">{o.horizon}</td>
                  <td className={`py-2 px-3 text-right font-mono ${
                    o.expected_return_pct > 0 ? "text-alpha-accent" : "text-alpha-danger"
                  }`}>{o.expected_return_pct > 0 ? "+" : ""}{o.expected_return_pct?.toFixed(1)}%</td>
                  <td className="py-2 px-3 text-center">
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      o.spec_category === "HIGH_CONVICTION" ? "bg-red-900/30 text-red-400" :
                      o.spec_category === "CANDIDATE" ? "bg-orange-900/30 text-orange-400" :
                      o.spec_category === "WATCH" ? "bg-yellow-900/30 text-yellow-400" :
                      "bg-alpha-bg text-alpha-muted"
                    }`}>{o.spec_category}</span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
