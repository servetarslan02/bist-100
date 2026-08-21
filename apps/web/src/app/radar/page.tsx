"use client";

import { useState, useMemo } from "react";
import { usePolling } from "@/lib/api";
import {
  Search, ArrowUpRight, ArrowDownRight, RefreshCw, Loader2
} from "lucide-react";

interface RadarRow {
  symbol: string;
  price: number;
  change: number;
  volume: number;
  high: number;
  low: number;
  rsi: number | null;
  score: number;
  isBist100: boolean;
}

interface RadarResponse {
  data: RadarRow[];
  count: number;
  errors: number;
  status: string;
}

export default function MarketRadar() {
  const { data: rawData, loading } = usePolling<RadarResponse>("/market/radar?limit=100&bist100_only=true", 120000);
  const [search, setSearch] = useState("");
  const [sortField, setSortField] = useState<keyof RadarRow>("score");
  const [sortAsc, setSortAsc] = useState(false);
  const [bist100Only, setBist100Only] = useState(true);

  const allRows: RadarRow[] = useMemo(() => {
    if (!rawData?.data) return [];
    return rawData.data;
  }, [rawData]);

  const filteredRows = useMemo(() => {
    return allRows
      .filter(r => {
        if (bist100Only && !r.isBist100) return false;
        if (search) {
          const q = search.toLowerCase();
          return r.symbol.toLowerCase().includes(q);
        }
        return true;
      })
      .sort((a, b) => {
        const valA = a[sortField] ?? 0;
        const valB = b[sortField] ?? 0;
        return sortAsc ? (Number(valA) - Number(valB)) : (Number(valB) - Number(valA));
      });
  }, [allRows, search, bist100Only, sortField, sortAsc]);

  const handleSort = (field: keyof RadarRow) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false);
    }
  };

  const Th = ({ field, label, right }: { field: keyof RadarRow; label: string; right?: boolean }) => (
    <th
      onClick={() => handleSort(field)}
      className={`py-3 px-4 cursor-pointer hover:text-zinc-100 select-none ${right ? "text-right" : ""}`}
    >
      {label} {sortField === field && (sortAsc ? "↑" : "↓")}
    </th>
  );

  return (
    <div className="p-5 space-y-4 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Piyasa Radarı</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            {loading ? "Yükleniyor..." : `${filteredRows.length} hisse · Gerçek zamanlı fiyat ve teknik veriler`}
            {rawData?.errors && rawData.errors > 0 ? ` · ${rawData.errors} hisse alınamadı` : ""}
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setBist100Only(!bist100Only)}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
              bist100Only
                ? "bg-emerald-500/20 border border-emerald-500/40 text-emerald-400"
                : "bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200"
            }`}
          >
            Sadece BIST-100
          </button>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800">
            <Search size={12} className="text-zinc-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Sembol ara..."
              className="bg-transparent text-xs text-zinc-200 focus:outline-none w-36"
            />
          </div>
        </div>
      </div>

      {/* Loading */}
      {loading && allRows.length === 0 && (
        <div className="flex items-center justify-center py-20 gap-3 text-zinc-500">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Gerçek piyasa verisi çekiliyor...</span>
        </div>
      )}

      {/* Table */}
      {allRows.length > 0 && (
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="overflow-x-auto max-h-[calc(100vh-230px)] custom-scrollbar">
            <table className="w-full text-left text-xs select-none">
              <thead
                className="sticky top-0 z-10 border-b border-zinc-800/80 uppercase text-[10px] tracking-wider text-zinc-400 font-semibold backdrop-blur-md"
                style={{ background: "rgba(13, 17, 26, 0.95)" }}
              >
                <tr>
                  <Th field="symbol" label="Sembol" />
                  <Th field="price" label="Fiyat" right />
                  <Th field="change" label="Günlük %" right />
                  <Th field="high" label="Yüksek" right />
                  <Th field="low" label="Düşük" right />
                  <Th field="rsi" label="14G RSI" right />
                  <Th field="score" label="Skor" right />
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/30">
                {filteredRows.map((row) => {
                  const isPos = row.change >= 0;
                  const rsi = row.rsi;
                  const rsiColor = rsi
                    ? rsi > 70 ? "#ff4466" : rsi < 35 ? "#00e5a0" : "#a1a1aa"
                    : "#52525b";
                  const scoreColor = row.score >= 70 ? "#00e5a0" : row.score >= 55 ? "#00c8ff" : "#ffaa00";

                  return (
                    <tr
                      key={row.symbol}
                      className="hover:bg-white/[0.03] transition-colors cursor-pointer"
                    >
                      <td className="py-2.5 px-4 font-bold font-data text-zinc-100">
                        <div className="flex items-center gap-2">
                          <span>{row.symbol}</span>
                          {row.isBist100 && (
                            <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                              B100
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-bold text-zinc-200">
                        ₺{row.price.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-bold">
                        <span className={`inline-flex items-center gap-0.5 ${isPos ? "text-emerald-400" : "text-red-400"}`}>
                          {isPos ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                          {isPos ? "+" : ""}%{row.change.toFixed(2)}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-right font-data text-zinc-400">
                        ₺{row.high.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data text-zinc-400">
                        ₺{row.low.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-semibold" style={{ color: rsiColor }}>
                        {rsi !== null && rsi !== undefined ? rsi.toFixed(1) : "—"}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-bold" style={{ color: scoreColor }}>
                        {row.score} / 100
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
