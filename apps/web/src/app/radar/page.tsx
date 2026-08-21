"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { usePolling } from "@/lib/api";
import { Search, ArrowUpRight, ArrowDownRight, Loader2, Wifi, WifiOff } from "lucide-react";

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

// BIST: 10:00 - 18:00 İstanbul (UTC+3)
function isBistOpen(): boolean {
  const now = new Date();
  const istanbul = new Date(now.toLocaleString("en-US", { timeZone: "Europe/Istanbul" }));
  const day = istanbul.getDay(); // 0=Sun, 6=Sat
  if (day === 0 || day === 6) return false;
  const h = istanbul.getHours();
  const m = istanbul.getMinutes();
  const minutes = h * 60 + m;
  return minutes >= 600 && minutes < 1080; // 10:00 - 18:00
}

export default function MarketRadar() {
  const [search, setSearch] = useState("");
  const [sortField, setSortField] = useState<keyof RadarRow>("score");
  const [sortAsc, setSortAsc] = useState(false);
  const [marketOpen, setMarketOpen] = useState(isBistOpen());

  // Cache'den anında geldiği için borsa açıksa 10s, kapalıysa 60s
  const pollInterval = marketOpen ? 10_000 : 60_000;

  const { data: rawData, loading, lastUpdated } = usePolling<RadarResponse>(
    "/market/radar?limit=200",
    pollInterval
  );

  // Her dakika borsa durumunu kontrol et
  useEffect(() => {
    const timer = setInterval(() => setMarketOpen(isBistOpen()), 60_000);
    return () => clearInterval(timer);
  }, []);

  const allRows: RadarRow[] = useMemo(() => rawData?.data ?? [], [rawData]);

  const filteredRows = useMemo(() => {
    return allRows
      .filter(r => {
        if (!search) return true;
        const q = search.toLowerCase();
        return r.symbol.toLowerCase().includes(q);
      })
      .sort((a, b) => {
        const valA = a[sortField] ?? 0;
        const valB = b[sortField] ?? 0;
        return sortAsc ? (Number(valA) - Number(valB)) : (Number(valB) - Number(valA));
      });
  }, [allRows, search, sortField, sortAsc]);

  const handleSort = (field: keyof RadarRow) => {
    if (sortField === field) setSortAsc(!sortAsc);
    else { setSortField(field); setSortAsc(false); }
  };

  const Th = ({ field, label, right }: { field: keyof RadarRow; label: string; right?: boolean }) => (
    <th
      onClick={() => handleSort(field)}
      className={`py-3 px-4 cursor-pointer hover:text-zinc-100 select-none whitespace-nowrap ${right ? "text-right" : ""}`}
    >
      {label}{sortField === field ? (sortAsc ? " ↑" : " ↓") : ""}
    </th>
  );

  return (
    <div className="p-5 space-y-4 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Piyasa Radarı</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              {loading && allRows.length === 0
                ? "Yükleniyor..."
                : `${filteredRows.length} / ${allRows.length} hisse`}
              {rawData?.errors && rawData.errors > 0 ? ` · ${rawData.errors} hisse verisi yok` : ""}
            </p>
            {/* Borsa durumu göstergesi */}
            <span className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${
              marketOpen
                ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                : "bg-zinc-800 text-zinc-500 border border-zinc-700"
            }`}>
              {marketOpen
                ? <><Wifi size={9} /> CANLI · {Math.round(pollInterval / 1000)}s</>
                : <><WifiOff size={9} /> Borsa Kapalı</>
              }
            </span>
            {lastUpdated && (
              <span className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>
                · {lastUpdated.toLocaleTimeString("tr-TR")}
              </span>
            )}
          </div>
        </div>

        {/* Arama */}
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

      {/* Loading */}
      {loading && allRows.length === 0 && (
        <div className="flex items-center justify-center py-20 gap-3 text-zinc-500">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Piyasa verileri yükleniyor...</span>
        </div>
      )}

      {/* Tablo */}
      {allRows.length > 0 && (
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="overflow-x-auto max-h-[calc(100vh-200px)] custom-scrollbar">
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
                  <Th field="volume" label="Hacim" right />
                  <Th field="rsi" label="RSI 14" right />
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
                    <tr key={row.symbol} className="hover:bg-white/[0.03] transition-colors cursor-pointer">
                      <td className="py-2.5 px-4 font-bold font-data text-zinc-100">
                        <div className="flex items-center gap-1.5">
                          <span>{row.symbol}</span>
                          {row.isBist100 && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
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
                          {isPos ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                          {isPos ? "+" : ""}%{row.change.toFixed(2)}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-right font-data text-zinc-400">₺{row.high.toFixed(2)}</td>
                      <td className="py-2.5 px-4 text-right font-data text-zinc-400">₺{row.low.toFixed(2)}</td>
                      <td className="py-2.5 px-4 text-right font-data text-zinc-500 text-[10px]">
                        {row.volume > 1_000_000
                          ? `${(row.volume / 1_000_000).toFixed(1)}M`
                          : row.volume > 1_000
                          ? `${(row.volume / 1_000).toFixed(0)}K`
                          : row.volume.toString()}
      </td>
                      <td className="py-2.5 px-4 text-right font-data font-semibold" style={{ color: rsiColor }}>
                        {rsi !== null && rsi !== undefined ? rsi.toFixed(1) : "—"}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-bold" style={{ color: scoreColor }}>
                        {row.score}
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
