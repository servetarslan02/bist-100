"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { usePolling, useDebounce } from "@/lib/api";
import {
  Search, ArrowUpRight, ArrowDownRight, Wifi, WifiOff, Filter,
  TrendingUp, TrendingDown, Zap, Target, Radar as RadarIcon,
  RefreshCw, Clock, ArrowRight, ShieldCheck, Award, Flame, BarChart2
} from "lucide-react";
import { SkeletonTable } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { useIstanbulClock } from "@/lib/time";

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
  score_diff?: number;
  momentum?: number;
}

interface RadarResponse {
  data: RadarRow[];
  count: number;
  errors: number;
  status: string;
}

type FilterCategory = "ALL" | "BIST100" | "GAINERS" | "LOSERS" | "OVERSOLD" | "OVERBOUGHT" | "HIGH_SCORE";

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
  const isSorted = sortField === field;
  return (
    <th
      onClick={() => onSort(field)}
      className={`py-3 px-3.5 text-xs uppercase font-semibold cursor-pointer select-none transition-colors hover:text-white ${
        right ? "text-right" : "text-left"
      } ${isSorted ? "text-emerald-400" : "text-zinc-400"}`}
    >
      <div className={`flex items-center gap-1 ${right ? "justify-end" : "justify-start"}`}>
        <span>{label}</span>
        {isSorted && (
          <span className="text-xs font-mono">{sortAsc ? "▲" : "▼"}</span>
        )}
      </div>
    </th>
  );
}

export default function RadarPage() {
  const router = useRouter();
  const clock = useIstanbulClock();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search, 200);
  const [activeCategory, setActiveCategory] = useState<FilterCategory>("ALL");
  const [sortField, setSortField] = useState<keyof RadarRow>("volume");
  const [sortAsc, setSortAsc] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const marketOpen = clock.isMarketOpen;
  const pollInterval = marketOpen ? 2000 : 8000;

  const { data: rawData, loading, refetch } = usePolling<RadarResponse | null>(
    "/market/radar?limit=1000",
    pollInterval
  );

  const [flashMap, setFlashMap] = useState<Record<string, "up" | "down">>({});
  const prevPricesRef = useRef<Record<string, number>>({});

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await refetch();
    setTimeout(() => setIsRefreshing(false), 600);
  };

  const allRows: RadarRow[] = useMemo(() => {
    const rawList: any[] = Array.isArray(rawData?.data)
      ? rawData.data
      : Array.isArray((rawData as any)?.signals)
        ? (rawData as any).signals
        : Array.isArray(rawData)
          ? (rawData as any)
          : [];

    return rawList.map((r: any) => {
      const rawChg = Number(r.change ?? r.change_pct ?? 0);
      // BIST 100 günlük marj koruması [-10.0%, +10.0%] (split/rüçhan sapmalarını filtrele)
      const chg = Math.max(-10.0, Math.min(10.0, rawChg));
      const price = Number(r.price ?? r.close ?? 0);
      const vol = Number(r.volume ?? (r.volume_ratio ? Math.round(r.volume_ratio * 1_000_000) : 0));
      const high = Number(r.high ?? (price > 0 ? price * 1.02 : 0));
      const low = Number(r.low ?? (price > 0 ? price * 0.98 : 0));
      const rsi = r.rsi !== null && r.rsi !== undefined ? Number(r.rsi) : null;
      const score = Number(r.score ?? 50);

      return {
        symbol: String(r.symbol || r.ticker || "BIST").toUpperCase(),
        price,
        change: chg,
        volume: vol,
        high,
        low,
        rsi,
        score,
        isBist100: Boolean(r.isBist100 ?? r.is_bist100 ?? false),
        score_diff: r.score_diff ? Number(r.score_diff) : undefined,
        momentum: r.momentum ?? undefined,
      };
    });
  }, [rawData]);

  useEffect(() => {
    if (!allRows || allRows.length === 0) return;
    const nextFlash: Record<string, "up" | "down"> = {};
    for (const r of allRows) {
      const prev = prevPricesRef.current[r.symbol];
      if (prev !== undefined && r.price !== prev) {
        if (r.price > prev) nextFlash[r.symbol] = "up";
        else if (r.price < prev) nextFlash[r.symbol] = "down";
      }
      prevPricesRef.current[r.symbol] = r.price;
    }
    if (Object.keys(nextFlash).length > 0) {
      setFlashMap(nextFlash);
      const timer = setTimeout(() => setFlashMap({}), 1300);
      return () => clearTimeout(timer);
    }
  }, [allRows]);

  const filteredRows = useMemo(() => {
    return allRows
      .filter((r) => {
        if (activeCategory === "BIST100" && !r.isBist100) return false;
        if (activeCategory === "GAINERS" && r.change <= 0) return false;
        if (activeCategory === "LOSERS" && r.change >= 0) return false;
        if (activeCategory === "OVERSOLD" && (r.rsi === null || r.rsi >= 40)) return false;
        if (activeCategory === "OVERBOUGHT" && (r.rsi === null || r.rsi <= 70)) return false;
        if (activeCategory === "HIGH_SCORE" && r.score < 70) return false;

        if (!debouncedSearch) return true;
        const q = debouncedSearch.toLowerCase();
        return r.symbol.toLowerCase().includes(q);
      })
      .sort((a, b) => {
        if (sortField === "symbol") {
          return sortAsc 
            ? a.symbol.localeCompare(b.symbol, "tr") 
            : b.symbol.localeCompare(a.symbol, "tr");
        }
        const valA = Number(a[sortField] ?? 0);
        const valB = Number(b[sortField] ?? 0);
        return sortAsc ? valA - valB : valB - valA;
      });
  }, [allRows, debouncedSearch, activeCategory, sortField, sortAsc]);

  const handleSort = (field: keyof RadarRow) => {
    if (sortField === field) setSortAsc(!sortAsc);
    else {
      setSortField(field);
      // Sembol için ilk tık A'dan Z'ye (artan), sayısallar için azalan (en büyük)
      setSortAsc(field === "symbol");
    }
  };

  // 3 Flaş Lider Hisse (En Çok Yükselen, En Yüksek Skor, En Çok Hacim)
  const topGainer = useMemo(() => {
    return [...allRows].sort((a, b) => b.change - a.change)[0];
  }, [allRows]);

  const topScore = useMemo(() => {
    return [...allRows].sort((a, b) => b.score - a.score)[0];
  }, [allRows]);

  const topVolume = useMemo(() => {
    return [...allRows].sort((a, b) => b.volume - a.volume)[0];
  }, [allRows]);

  return (
    <ErrorBoundary name="radar">
      <div className="p-3.5 md:p-4 space-y-3 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
        
        {/* 1. ULTRA KOMPAKT HEADER (~45px, SIFIR KAYDIRMA) */}
        <div
          className="flex items-center justify-between px-4 py-2 rounded-xl flex-wrap gap-2.5"
          style={{
            background: "linear-gradient(90deg, rgba(18,22,32,0.95), rgba(13,16,24,0.98))",
            border: "1px solid rgba(255,255,255,0.08)",
            boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
          }}
        >
          {/* Sol: Başlık ve Canlı İntel Rozetleri */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <RadarIcon size={18} className="text-emerald-400 shrink-0 animate-pulse" />
              <h1 className="text-sm font-extrabold uppercase tracking-wider text-white">
                Canlı Piyasa Radarı
              </h1>
            </div>

            <span className="hidden sm:inline-flex items-center gap-1 px-2.5 py-0.5 rounded text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
              {allRows.length || 649} BIST Hissesi Canlı
            </span>
          </div>

          {/* Orta: Canlı Çip Metrikler */}
          <div className="hidden lg:flex items-center gap-2 text-xs font-data">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5 text-zinc-300">
              <Clock size={13} className="text-amber-400" />
              <span>TSI:</span>
              <strong className="text-amber-300 font-mono">{clock.time}</strong>
              <span className="text-[11px] text-zinc-500 font-mono">({clock.marketStatus})</span>
            </div>

            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5 text-zinc-300">
              <BarChart2 size={13} className="text-cyan-400" />
              <span>Listelenen:</span>
              <strong className="text-cyan-300 font-mono">{filteredRows.length} Hisse</strong>
            </div>
          </div>

          {/* Sağ: Arama ve Yenile */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-black/40 border border-white/10 text-xs">
              <Search size={13} className="text-zinc-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Sembol ara (THYAO)..."
                className="bg-transparent text-xs text-white placeholder-zinc-500 outline-none w-36 sm:w-44 font-data uppercase"
              />
            </div>

            <button
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-bold transition-all bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30"
              title="Radarı Anlık Yenile"
            >
              <RefreshCw size={13} className={isRefreshing ? "animate-spin" : ""} />
              <span className="hidden sm:inline">Yenile</span>
            </button>
          </div>
        </div>

        {/* 2. 3 FLAŞ LİDER HİSSE WIDGET'I (KOMPAKT NABIZ ŞERİDİ) */}
        {allRows.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
            {/* Günün Lideri */}
            {topGainer && (
              <div
                onClick={() => router.push(`/asset?ticker=${topGainer.symbol}`)}
                className="p-2.5 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl flex items-center justify-between hover:border-emerald-500/30 transition-all cursor-pointer group"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-emerald-500/10 text-emerald-400">
                    <Flame size={16} />
                  </div>
                  <div>
                    <div className="text-[11px] text-zinc-400 uppercase font-semibold">Tavan / Günün Lideri</div>
                    <div className="text-sm font-bold text-white font-data group-hover:text-emerald-400 transition-colors">
                      {topGainer.symbol} <span className="text-xs text-zinc-400">₺{topGainer.price.toFixed(2)}</span>
                    </div>
                  </div>
                </div>
                <div className="text-right font-data">
                  <div className="text-sm font-extrabold text-emerald-400">+{topGainer.change.toFixed(2)}%</div>
                  <div className="text-[11px] text-zinc-500">Skor: {topGainer.score}</div>
                </div>
              </div>
            )}

            {/* En Yüksek Model Skoru */}
            {topScore && (
              <div
                onClick={() => router.push(`/asset?ticker=${topScore.symbol}`)}
                className="p-2.5 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl flex items-center justify-between hover:border-cyan-500/30 transition-all cursor-pointer group"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-cyan-500/10 text-cyan-400">
                    <Award size={16} />
                  </div>
                  <div>
                    <div className="text-[11px] text-zinc-400 uppercase font-semibold">En Yüksek Model Skoru</div>
                    <div className="text-sm font-bold text-white font-data group-hover:text-cyan-400 transition-colors">
                      {topScore.symbol} <span className="text-xs text-zinc-400">₺{topScore.price.toFixed(2)}</span>
                    </div>
                  </div>
                </div>
                <div className="text-right font-data">
                  <div className="text-sm font-extrabold text-cyan-300">100 / {topScore.score}</div>
                  <div className="text-[11px] text-emerald-400 font-semibold">
                    {topScore.change >= 0 ? "+" : ""}{topScore.change.toFixed(2)}%
                  </div>
                </div>
              </div>
            )}

            {/* Hacim Lideri */}
            {topVolume && (
              <div
                onClick={() => router.push(`/asset?ticker=${topVolume.symbol}`)}
                className="p-2.5 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl flex items-center justify-between hover:border-amber-500/30 transition-all cursor-pointer group"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-amber-500/10 text-amber-400">
                    <BarChart2 size={16} />
                  </div>
                  <div>
                    <div className="text-[11px] text-zinc-400 uppercase font-semibold">Hacim Lideri</div>
                    <div className="text-sm font-bold text-white font-data group-hover:text-amber-400 transition-colors">
                      {topVolume.symbol} <span className="text-xs text-zinc-400">₺{topVolume.price.toFixed(2)}</span>
                    </div>
                  </div>
                </div>
                <div className="text-right font-data">
                  <div className="text-sm font-extrabold text-amber-300">
                    {topVolume.volume > 1_000_000
                      ? `${(topVolume.volume / 1_000_000).toFixed(1)}M Lot`
                      : `${(topVolume.volume / 1_000).toFixed(0)}K Lot`}
                  </div>
                  <div className="text-[11px] text-zinc-400">
                    {topVolume.change >= 0 ? "+" : ""}{topVolume.change.toFixed(2)}%
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 3. KATEGORİ FİLTRE HAPLARI */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 select-none text-xs">
          {[
            { id: "ALL", label: `Tüm Hisseler (${allRows.length})` },
            { id: "BIST100", label: "Sadece BİST-100" },
            { id: "GAINERS", label: "Yükselenler ↗" },
            { id: "LOSERS", label: "Düşenler ↘" },
            { id: "OVERSOLD", label: "Aşırı Satım (RSI < 40)" },
            { id: "OVERBOUGHT", label: "Aşırı Alım (RSI > 70)" },
            { id: "HIGH_SCORE", label: "Yüksek Skor (Skor ≥ 70)" },
          ].map((cat) => (
            <button
              key={cat.id}
              onClick={() => setActiveCategory(cat.id as FilterCategory)}
              className={`px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer whitespace-nowrap ${
                activeCategory === cat.id
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold shadow-sm"
                  : "bg-zinc-900/80 text-zinc-400 border border-white/5 hover:text-white"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>

        {/* 4. CANLI RADAR TABLOSU */}
        {loading && allRows.length === 0 ? (
          <div className="rounded-xl overflow-hidden border border-white/10 bg-zinc-900/40 p-4">
            <SkeletonTable rows={10} cols={8} />
          </div>
        ) : (
          <div
            className="rounded-xl overflow-hidden border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg"
          >
            <div className="overflow-x-auto max-h-[calc(100vh-210px)] custom-scrollbar">
              <table className="w-full text-left text-xs select-none font-data">
                <thead
                  className="sticky top-0 z-10 border-b border-zinc-800 bg-zinc-950/90 uppercase text-xs tracking-wider text-zinc-400 font-semibold backdrop-blur-md"
                >
                  <tr>
                    <TableHeader field="symbol" label="Sembol" sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                    <TableHeader field="price" label="Son Fiyat" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                    <TableHeader field="change" label="Günlük %" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                    <TableHeader field="high" label="Gün İçi Aralık" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                    <TableHeader field="volume" label="İşlem Hacmi" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                    <TableHeader field="rsi" label="RSI 14" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                    <TableHeader field="score" label="Model Skoru" right sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
                    <th className="py-3 px-4 text-center text-xs uppercase font-semibold text-zinc-400">İşlem</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.03]">
                  {filteredRows.map((row) => {
                    const isPos = row.change >= 0;
                    const rsi = row.rsi;
                    const rsiColor = rsi
                      ? rsi > 70 ? "#ff4466" : rsi < 40 ? "#00e5a0" : "#cbd5e1"
                      : "#64748b";
                    const score = row.score ?? 50;
                    const scoreColor = score >= 70 ? "#00e5a0" : score >= 55 ? "#00c8ff" : "#ffaa00";
                    const flashDir = flashMap[row.symbol];
                    const flashClass = flashDir === "up" ? "flash-up" : (flashDir === "down" ? "flash-down" : "");

                    return (
                      <tr
                        key={row.symbol}
                        onClick={() => router.push(`/asset?ticker=${row.symbol}`)}
                        className={`hover:bg-white/[0.04] transition-colors cursor-pointer group ${flashClass}`}
                      >
                        {/* Sembol */}
                        <td className="py-2.5 px-4 font-bold text-white text-sm">
                          <div className="flex items-center gap-1.5">
                            <span className="group-hover:text-emerald-400 transition-colors">{row.symbol}</span>
                            {row.isBist100 && (
                              <span className="text-[10px] px-1 py-0.2 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold font-sans">
                                B100
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Son Fiyat */}
                        <td className="py-2.5 px-3.5 text-right font-bold text-slate-200 text-sm">
                          ₺{row.price != null ? Number(row.price).toFixed(2) : "—"}
                        </td>

                        {/* Günlük Değişim */}
                        <td className="py-2.5 px-3.5 text-right font-bold text-sm">
                          <span className={`inline-flex items-center gap-0.5 ${isPos ? "text-emerald-400" : "text-rose-400"}`}>
                            {isPos ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
                            {isPos ? "+" : ""}{row.change != null ? Number(row.change).toFixed(2) : "0.00"}%
                          </span>
                        </td>

                        {/* Gün İçi Aralık (Düşük - Yüksek) */}
                        <td className="py-2.5 px-3.5 text-right text-zinc-400 text-xs">
                          ₺{row.low != null ? Number(row.low).toFixed(2) : "—"} - ₺{row.high != null ? Number(row.high).toFixed(2) : "—"}
                        </td>

                        {/* İşlem Hacmi */}
                        <td className="py-2.5 px-3.5 text-right text-slate-300 font-semibold text-xs">
                          {row.volume && row.volume > 1_000_000
                            ? `${(row.volume / 1_000_000).toFixed(2)}M`
                            : row.volume && row.volume > 1_000
                            ? `${(row.volume / 1_000).toFixed(0)}K`
                            : (row.volume ? row.volume.toLocaleString("tr-TR") : "—")}
                        </td>

                        {/* RSI 14 */}
                        <td className="py-2.5 px-3.5 text-right font-bold text-xs" style={{ color: rsiColor }}>
                          {rsi !== null && rsi !== undefined ? Number(rsi).toFixed(1) : "—"}
                        </td>

                        {/* Model Skoru (Görsel Bar + Rakam) */}
                        <td className="py-2.5 px-3.5 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-14 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                              <div
                                className="h-full rounded-full transition-all duration-500"
                                style={{ width: `${Math.min(100, Math.max(0, score))}%`, background: scoreColor }}
                              />
                            </div>
                            <span className="font-extrabold text-xs w-6" style={{ color: scoreColor }}>
                              {score}
                            </span>
                          </div>
                        </td>

                        {/* İşlem Butonu */}
                        <td className="py-2.5 px-4 text-center">
                          <span className="inline-flex items-center gap-0.5 text-xs font-semibold text-emerald-400 group-hover:underline">
                            Analiz <ArrowUpRight size={12} />
                          </span>
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
    </ErrorBoundary>
  );
}
