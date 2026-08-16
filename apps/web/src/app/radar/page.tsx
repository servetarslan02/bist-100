"use client";

import { useState, useMemo } from "react";
import { usePolling, type Instrument } from "@/lib/api";

interface EnrichedInstrument extends Instrument {
  price?: number;
  rsi?: number;
  mom5?: number;
  mom20?: number;
  vol_z?: number;
  anomaly?: number;
  spec?: number;
}

export default function MarketRadar() {
  const { data: instruments, loading } = usePolling<Instrument[]>("/market/instruments?limit=500", 60000);
  const [search, setSearch] = useState("");
  const [sector, setSector] = useState("");
  const [sortCol, setSortCol] = useState<string>("spec");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sectors = useMemo(() => {
    if (!instruments) return [];
    return [...new Set(instruments.map(i => i.sector))].sort();
  }, [instruments]);

  const filtered = useMemo(() => {
    if (!instruments) return [];
    return instruments.filter(i => {
      if (search && !i.symbol.toLowerCase().includes(search.toLowerCase()) &&
          !i.name.toLowerCase().includes(search.toLowerCase())) return false;
      if (sector && i.sector !== sector) return false;
      return true;
    });
  }, [instruments, search, sector]);

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  };

  const SortHeader = ({ col, label, align = "left" }: { col: string; label: string; align?: string }) => (
    <th
      className={`py-1.5 px-2 font-medium cursor-pointer hover:text-zinc-300 select-none ${align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left"}`}
      onClick={() => handleSort(col)}
    >
      <span className="flex items-center gap-1" style={{ justifyContent: align === "right" ? "flex-end" : align === "center" ? "center" : "flex-start" }}>
        {label}
        {sortCol === col && (
          <span className="text-zinc-600">{sortDir === "asc" ? "↑" : "↓"}</span>
        )}
      </span>
    </th>
  );

  return (
    <div className="p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Market Radar</h1>
          <p className="text-[11px] text-zinc-600">{filtered.length} instruments • live scanning</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search..."
            className="bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1 text-xs text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600 w-40"
          />
          <select
            value={sector}
            onChange={e => setSector(e.target.value)}
            className="bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1 text-xs text-zinc-300 focus:outline-none focus:border-zinc-600"
          >
            <option value="">All Sectors</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-zinc-500 border-b border-zinc-800/60 bg-zinc-950/50">
                <SortHeader col="symbol" label="TICKER" />
                <SortHeader col="name" label="NAME" />
                <SortHeader col="sector" label="SECTOR" />
                <SortHeader col="price" label="PRICE" align="right" />
                <SortHeader col="change" label="CHG%" align="right" />
                <SortHeader col="rsi" label="RSI" align="right" />
                <SortHeader col="mom5" label="MOM5" align="right" />
                <SortHeader col="mom20" label="MOM20" align="right" />
                <SortHeader col="vol_z" label="VOL Z" align="right" />
                <SortHeader col="anomaly" label="ANOM" align="right" />
                <SortHeader col="spec" label="SPEC" align="right" />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={11} className="text-center py-12 text-zinc-600">
                    <div className="flex items-center justify-center gap-2">
                      <div className="w-4 h-4 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
                      Loading market data...
                    </div>
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={11} className="text-center py-12 text-zinc-600">No instruments found</td>
                </tr>
              ) : (
                filtered.map((inst, i) => (
                  <tr
                    key={inst.symbol}
                    className="border-b border-zinc-800/20 row-hover cursor-pointer"
                  >
                    <td className="py-1.5 px-2 font-semibold text-zinc-200">{inst.symbol}</td>
                    <td className="py-1.5 px-2 text-zinc-500 truncate max-w-[160px]">{inst.name}</td>
                    <td className="py-1.5 px-2">
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">
                        {inst.sector}
                      </span>
                    </td>
                    <td className="py-1.5 px-2 text-right font-mono text-zinc-300">—</td>
                    <td className="py-1.5 px-2 text-right font-mono text-zinc-500">—</td>
                    <td className="py-1.5 px-2 text-right font-mono text-zinc-400">—</td>
                    <td className="py-1.5 px-2 text-right font-mono text-zinc-500">—</td>
                    <td className="py-1.5 px-2 text-right font-mono text-zinc-500">—</td>
                    <td className="py-1.5 px-2 text-right font-mono text-zinc-500">—</td>
                    <td className="py-1.5 px-2 text-right font-mono text-zinc-500">—</td>
                    <td className="py-1.5 px-2 text-right font-mono text-zinc-400">—</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-[10px] text-zinc-600">
        <span>Data: yfinance (15min delayed)</span>
        <span>Refresh: 60s</span>
      </div>
    </div>
  );
}
