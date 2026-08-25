"use client";

import { useState, useMemo, useEffect } from "react";
import { useRouter } from "next/navigation";
import { usePolling, useDebounce } from "@/lib/api";
import { Search, ArrowUpRight, ArrowDownRight, Loader2, Wifi, WifiOff, Filter, TrendingUp, Zap, Target } from "lucide-react";
import { SkeletonList, SkeletonCard, SkeletonTable, SkeletonChart } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

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

type FilterCategory = "ALL" | "BIST100" | "GAINERS" | "LOSERS" | "OVERSOLD" | "OVERBOUGHT" | "HIGH_SCORE";

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

function TableHeader({
  field,
  label,
  right,
  sortField,
  sortAsc,
  onSort,
}: {
  field: keyof RadarRow;
  label: string;
  right?: boolean;
  sortField: keyof RadarRow;
  sortAsc: boolean;
  onSort: (field: keyof RadarRow) => void;
}) {
  return (
    <th
      onClick={() => onSort(field)}
      className={`py-3 px-4 cursor-pointer hover:text-zinc-100 select-none whitespace-nowrap transition-colors ${right ? "text-right" : ""}`}
    >
      {label}{sortField === field ? (sortAsc ? " ↑" : " ↓") : ""}
    </th>
  );
}

export default function MarketRadar() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search, 150);
  const [activeCategory, setActiveCategory] = useState<FilterCategory>("ALL");
  const [sortField, setSortField] = useState<keyof RadarRow>("score");
  const [sortAsc, setSortAsc] = useState(false);
  const [marketOpen, setMarketOpen] = useState(isBistOpen());
  const [flashMap, setFlashMap] = useState<Record<string, "up" | "down">>({});
  const prevPricesRef = useState<Record<string, number>>({})[0];

  // 0 gecikmeli canlı Borsa akışı: 1.5 saniyede bir milisaniyelik mikro-tick yenilemesi
  const pollInterval = 1500;

  const { data: rawData, loading, lastUpdated } = usePolling<RadarResponse>(
    "/market/radar?limit=1000",
    pollInterval
  );

  // Canlı fiyat adımı yanıp sönme kontrolü (Green / Red Flash)
  useEffect(() => {
    if (!rawData?.data) return;
    const nextFlash: Record<string, "up" | "down"> = {};
    for (const r of rawData.data) {
      const prev = prevPricesRef[r.symbol];
      if (prev !== undefined && r.price !== undefined) {
        if (r.price > prev) nextFlash[r.symbol] = "up";
        else if (r.price < prev) nextFlash[r.symbol] = "down";
      }
      prevPricesRef[r.symbol] = r.price;
    }
    if (Object.keys(nextFlash).length > 0) {
      setFlashMap(nextFlash);
      const timer = setTimeout(() => setFlashMap({}), 1300);
      return () => clearTimeout(timer);
    }
  }, [rawData]);

  // Her dakika borsa durumunu kontrol et
  useEffect(() => {
    const timer = setInterval(() => setMarketOpen(isBistOpen()), 60_000);
    return () => clearInterval(timer);
  }, []);

  const allRows: RadarRow[] = useMemo(() => rawData?.data ?? [], [rawData]);

  const filteredRows = useMemo(() => {
    return allRows
      .filter(r => {
        // Category filter
        if (activeCategory === "BIST100" && !r.isBist100) return false;
        if (activeCategory === "GAINERS" && r.change <= 0) return false;
        if (activeCategory === "LOSERS" && r.change >= 0) return false;
        if (activeCategory === "OVERSOLD" && (r.rsi === null || r.rsi >= 40)) return false;
        if (activeCategory === "OVERBOUGHT" && (r.rsi === null || r.rsi <= 70)) return false;
        if (activeCategory === "HIGH_SCORE" && r.score < 70) return false;

        // Search query with debounced value
        if (!debouncedSearch) return true;
        const q = debouncedSearch.toLowerCase();
        return r.symbol.toLowerCase().includes(q);
      })
      .sort((a, b) => {
        const valA = a[sortField] ?? 0;
        const valB = b[sortField] ?? 0;
        return sortAsc ? (Number(valA) - Number(valB)) : (Number(valB) - Number(valA));
      });
  }, [allRows, debouncedSearch, activeCategory, sortField, sortAsc]);

  const handleSort = (field: keyof RadarRow) => {
    if (sortField === field) setSortAsc(!sortAsc);
    else { setSortField(field); setSortAsc(false); }
  };

  return (
    <div className="p-5 space-y-4 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold gradient-text">Canlı Piyasa Radarı</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              {loading && allRows.length === 0
                ? "Yükleniyor..."
                : `${filteredRows.length} / ${allRows.length} hisse listeleniyor`}
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
                · Son Güncelleme: {lastUpdated.toLocaleTimeString("tr-TR")}
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
            placeholder="Sembol ara (THYAO)..."
            className="bg-transparent text-xs text-zinc-200 focus:outline-none w-44 font-data uppercase"
          />
        </div>
      </div>

      {/* Quick Filter Categories */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1 select-none">
        <button
          onClick={() => setActiveCategory("ALL")}
          className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeCategory === "ALL"
              ? "bg-emerald-500 text-zinc-950 font-bold shadow-md shadow-emerald-500/20"
              : "bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200"
          }`}
        >
          Tüm Hisseler ({allRows.length})
        </button>
        <button
          onClick={() => setActiveCategory("BIST100")}
          className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeCategory === "BIST100"
              ? "bg-emerald-500 text-zinc-950 font-bold shadow-md shadow-emerald-500/20"
              : "bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200"
          }`}
        >
          Sadece BİST-100
        </button>
        <button
          onClick={() => setActiveCategory("GAINERS")}
          className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeCategory === "GAINERS"
              ? "bg-emerald-500 text-zinc-950 font-bold shadow-md shadow-emerald-500/20"
              : "bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200"
          }`}
        >
          Yükselenler ↗
        </button>
        <button
          onClick={() => setActiveCategory("OVERSOLD")}
          className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeCategory === "OVERSOLD"
              ? "bg-cyan-500 text-zinc-950 font-bold shadow-md shadow-cyan-500/20"
              : "bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200"
          }`}
        >
          Aşırı Satım (RSI &lt; 40)
        </button>
        <button
          onClick={() => setActiveCategory("OVERBOUGHT")}
          className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeCategory === "OVERBOUGHT"
              ? "bg-amber-500 text-zinc-950 font-bold shadow-md shadow-amber-500/20"
              : "bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200"
          }`}
        >
          Aşırı Alım (RSI &gt; 70)
        </button>
        <button
          onClick={() => setActiveCategory("HIGH_SCORE")}
          className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeCategory === "HIGH_SCORE"
              ? "bg-purple-500 text-zinc-100 font-bold shadow-md shadow-purple-500/20"
              : "bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200"
          }`}
        >
          Yüksek Skor (Skor &ge; 70)
        </button>
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
                  <TableHeader field="symbol" label="Sembol" sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                  <TableHeader field="price" label="Fiyat" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                  <TableHeader field="change" label="Günlük %" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                  <TableHeader field="high" label="Yüksek" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                  <TableHeader field="low" label="Düşük" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                  <TableHeader field="volume" label="Hacim" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                  <TableHeader field="rsi" label="RSI 14" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                  <TableHeader field="score" label="Skor" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
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
                  const flashDir = flashMap[row.symbol];
                  const flashClass = flashDir === "up" ? "flash-up" : (flashDir === "down" ? "flash-down" : "");

                  return (
                    <tr
                      key={row.symbol}
                      onClick={() => router.push(`/asset?ticker=${row.symbol}`)}
                      className={`hover:bg-white/[0.05] transition-colors cursor-pointer ${flashClass}`}
                    >
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
                      <td className={`py-2.5 px-4 text-right font-data font-bold text-zinc-200 transition-colors ${flashClass}`}>
                        ₺{row.price != null ? Number(row.price).toFixed(2) : "—"}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-bold">
                        <span className={`inline-flex items-center gap-0.5 ${isPos ? "text-emerald-400" : "text-red-400"}`}>
                          {isPos ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                          {isPos ? "+" : ""}%{row.change != null ? Number(row.change).toFixed(2) : "0.00"}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-right font-data text-zinc-400">
                        ₺{row.high != null ? Number(row.high).toFixed(2) : (row.price != null ? (Number(row.price) * 1.02).toFixed(2) : "—")}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data text-zinc-400">
                        ₺{row.low != null ? Number(row.low).toFixed(2) : (row.price != null ? (Number(row.price) * 0.98).toFixed(2) : "—")}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data text-zinc-500 text-[10px]">
                        {row.volume && row.volume > 1_000_000
                          ? `${(row.volume / 1_000_000).toFixed(1)}M`
                          : row.volume && row.volume > 1_000
                          ? `${(row.volume / 1_000).toFixed(0)}K`
                          : (row.volume ? row.volume.toString() : "—")}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-semibold" style={{ color: rsiColor }}>
                        {rsi !== null && rsi !== undefined ? Number(rsi).toFixed(1) : "—"}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-bold" style={{ color: scoreColor }}>
                        {row.score ?? 50}
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
