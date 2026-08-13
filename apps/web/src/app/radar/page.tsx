"use client";

import { useEffect, useState } from "react";

interface Instrument {
  symbol: string;
  name: string;
  sector: string;
}

export default function MarketRadar() {
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [features, setFeatures] = useState<Record<string, Record<string, string>>>({});
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");

  useEffect(() => {
    fetchInstruments();
  }, []);

  async function fetchInstruments() {
    try {
      const res = await fetch("/api/market/instruments?limit=200");
      if (res.ok) {
        const data = await res.json();
        setInstruments(data);

        // Fetch features for each
        for (const inst of data.slice(0, 50)) {
          fetchFeatures(inst.symbol);
        }
      }
    } catch (e) {
      console.error("Failed to fetch instruments:", e);
    } finally {
      setLoading(false);
    }
  }

  async function fetchFeatures(ticker: string) {
    try {
      const res = await fetch(`/api/market/instrument/${ticker}`);
      if (res.ok) {
        const data = await res.json();
        if (data.features) {
          setFeatures(prev => ({ ...prev, [ticker]: data.features }));
        }
      }
    } catch {}
  }

  const filtered = instruments.filter(i => {
    if (search && !i.symbol.toLowerCase().includes(search.toLowerCase()) &&
        !i.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (sectorFilter && i.sector !== sectorFilter) return false;
    return true;
  });

  const sectors = [...new Set(instruments.map(i => i.sector))].sort();

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Market Radar</h1>
          <p className="text-sm text-alpha-muted">800+ BIST instruments — live scanning</p>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="text"
            placeholder="Search ticker..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-alpha-bg border border-alpha-border rounded px-3 py-1.5 text-sm focus:outline-none focus:border-alpha-accent"
          />
          <select
            value={sectorFilter}
            onChange={e => setSectorFilter(e.target.value)}
            className="bg-alpha-bg border border-alpha-border rounded px-3 py-1.5 text-sm focus:outline-none focus:border-alpha-accent"
          >
            <option value="">All Sectors</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      <div className="bg-alpha-surface border border-alpha-border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-alpha-muted border-b border-alpha-border bg-alpha-bg/50">
              <th className="text-left py-2 px-3">TICKER</th>
              <th className="text-left py-2 px-3">NAME</th>
              <th className="text-left py-2 px-3">SECTOR</th>
              <th className="text-right py-2 px-3">RSI</th>
              <th className="text-right py-2 px-3">MOM 5D</th>
              <th className="text-right py-2 px-3">VOL Z</th>
              <th className="text-right py-2 px-3">ANOMALY</th>
              <th className="text-right py-2 px-3">SPEC</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} className="text-center py-8 text-alpha-muted">Loading...</td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-8 text-alpha-muted">No instruments found</td>
              </tr>
            ) : (
              filtered.map(inst => {
                const f = features[inst.symbol] || {};
                return (
                  <tr key={inst.symbol} className="border-b border-alpha-border/30 hover:bg-alpha-border/20 cursor-pointer">
                    <td className="py-2 px-3 font-semibold text-alpha-accent">{inst.symbol}</td>
                    <td className="py-2 px-3 text-alpha-muted truncate max-w-[200px]">{inst.name}</td>
                    <td className="py-2 px-3 text-alpha-muted">{inst.sector}</td>
                    <td className="py-2 px-3 text-right font-mono">{formatNum(f.rsi_14)}</td>
                    <td className={`py-2 px-3 text-right font-mono ${getColor(f.momentum_5d)}`}>
                      {formatPct(f.momentum_5d)}
                    </td>
                    <td className="py-2 px-3 text-right font-mono">{formatNum(f.volume_zscore)}</td>
                    <td className="py-2 px-3 text-right font-mono">{formatNum(f.anomaly_score)}</td>
                    <td className="py-2 px-3 text-right font-mono">{formatNum(f.spec_score)}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatNum(val?: string): string {
  if (!val) return "—";
  const num = parseFloat(val);
  return isNaN(num) ? "—" : num.toFixed(2);
}

function formatPct(val?: string): string {
  if (!val) return "—";
  const num = parseFloat(val);
  return isNaN(num) ? "—" : `${num > 0 ? "+" : ""}${num.toFixed(2)}%`;
}

function getColor(val?: string): string {
  if (!val) return "";
  const num = parseFloat(val);
  if (num > 0) return "text-alpha-accent";
  if (num < 0) return "text-alpha-danger";
  return "";
}
