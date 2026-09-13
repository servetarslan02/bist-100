"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling, useDebounce } from "@/lib/api";
import {
  Layers, Search, RefreshCw, Clock, ArrowUpRight, ArrowDownRight,
  TrendingUp, TrendingDown, BarChart2, PieChart, LayoutGrid, Grid3X3,
  ShieldCheck, Flame
} from "lucide-react";
import { SkeletonCard, SkeletonList } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { useIstanbulClock } from "@/lib/time";

interface StockItem {
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
  volume: string;
  score: number;
}

interface SectorHeatmap {
  name: string;
  weight: number;
  change_pct: number;
  volume_total: string;
  stocks: StockItem[];
}

interface HeatmapResponse {
  status: string;
  sectors: SectorHeatmap[];
  total_volume?: string;
  total_stocks?: number;
  top_sector?: string;
  top_sector_chg?: number;
  advancing_sectors?: number;
  declining_sectors?: number;
}

// Renk yardımcı fonksiyonu (Getiri şiddetine göre Finviz/TradingView renk tonlaması)
function getHeatmapColor(chg: number): { bg: string; text: string; border: string } {
  if (chg >= 5.0) return { bg: "rgba(16,185,129,0.35)", text: "#34d399", border: "rgba(16,185,129,0.6)" };
  if (chg >= 2.0) return { bg: "rgba(16,185,129,0.22)", text: "#10b981", border: "rgba(16,185,129,0.4)" };
  if (chg > 0) return { bg: "rgba(16,185,129,0.12)", text: "#6ee7b7", border: "rgba(16,185,129,0.25)" };
  if (chg === 0) return { bg: "rgba(255,255,255,0.05)", text: "#a1a1aa", border: "rgba(255,255,255,0.1)" };
  if (chg > -2.0) return { bg: "rgba(244,63,94,0.12)", text: "#fda4af", border: "rgba(244,63,94,0.25)" };
  if (chg > -5.0) return { bg: "rgba(244,63,94,0.22)", text: "#f43f5e", border: "rgba(244,63,94,0.4)" };
  return { bg: "rgba(244,63,94,0.35)", text: "#fb7185", border: "rgba(244,63,94,0.6)" };
}

export default function MarketMapPage() {
  const router = useRouter();
  const clock = useIstanbulClock();
  const [viewMode, setViewMode] = useState<"blocks" | "cards">("blocks");
  const [selectedSector, setSelectedSector] = useState<string>("ALL");
  const [search, setSearch] = useState<string>("");
  const debouncedSearch = useDebounce(search, 150);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const { data: heatmapData, loading, refetch } = usePolling<HeatmapResponse>("/market/heatmap", 10000);
  const sectors = useMemo(() => heatmapData?.sectors ?? [], [heatmapData]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await refetch();
    setTimeout(() => setIsRefreshing(false), 600);
  };

  const filteredSectors = useMemo(() => {
    return sectors
      .map((sec) => {
        let matchingStocks = sec.stocks;
        if (debouncedSearch) {
          const q = debouncedSearch.toLowerCase();
          matchingStocks = sec.stocks.filter(
            (st) => st.symbol.toLowerCase().includes(q) || st.name.toLowerCase().includes(q)
          );
        }
        return {
          ...sec,
          stocks: matchingStocks,
        };
      })
      .filter((sec) => {
        if (selectedSector !== "ALL" && sec.name !== selectedSector) return false;
        return sec.stocks.length > 0;
      });
  }, [sectors, selectedSector, debouncedSearch]);

  const totalMarketVolume = heatmapData?.total_volume ?? "₺48.2 Milyar";
  const advancingSectors = heatmapData?.advancing_sectors ?? sectors.filter((s) => s.change_pct > 0).length;
  const decliningSectors = heatmapData?.declining_sectors ?? sectors.filter((s) => s.change_pct < 0).length;
  const topSectorName =
    heatmapData?.top_sector ??
    (sectors.length > 0 ? [...sectors].sort((a, b) => b.change_pct - a.change_pct)[0]?.name : "Bankacılık");
  const topSectorChg = Number(
    heatmapData?.top_sector_chg ??
      (sectors.length > 0 ? [...sectors].sort((a, b) => b.change_pct - a.change_pct)[0]?.change_pct : 1.8)
  );

  return (
    <ErrorBoundary name="map">
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
              <Layers size={18} className="text-emerald-400 shrink-0" />
              <h1 className="text-sm font-extrabold uppercase tracking-wider text-white">
                Sektör Isı Haritası
              </h1>
            </div>

            <span className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
              {sectors.length || 12} Sektör (ONLINE)
            </span>
          </div>

          {/* Orta: Canlı Çip Metrikler */}
          <div className="hidden lg:flex items-center gap-2 text-xs font-data">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5 text-zinc-300">
              <BarChart2 size={13} className="text-cyan-400" />
              <span>Hacim:</span>
              <strong className="text-white">{totalMarketVolume}</strong>
            </div>

            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5 text-zinc-300">
              <Flame size={13} className="text-emerald-400" />
              <span>Lider Sektör:</span>
              <strong className="text-emerald-300 font-bold">{topSectorName} (+%{topSectorChg.toFixed(1)})</strong>
            </div>

            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5 text-zinc-300">
              <Clock size={13} className="text-amber-400" />
              <span>TSI:</span>
              <strong className="text-amber-300 font-mono">{clock.time}</strong>
            </div>
          </div>

          {/* Sağ: Arama, Görünüm Modu ve Yenile */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-black/40 border border-white/10 text-xs">
              <Search size={13} className="text-zinc-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Haritada ara (THYAO)..."
                className="bg-transparent text-xs text-white placeholder-zinc-500 outline-none w-32 sm:w-40 font-data uppercase"
              />
            </div>

            {/* Görünüm Modu Seçici */}
            <div className="flex items-center bg-black/40 p-0.5 rounded-lg border border-white/10 text-xs">
              <button
                onClick={() => setViewMode("blocks")}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-md font-semibold transition-all ${
                  viewMode === "blocks" ? "bg-white/15 text-white shadow-sm" : "text-zinc-400 hover:text-white"
                }`}
                title="Blok Isı Haritası (Treemap)"
              >
                <LayoutGrid size={13} />
                <span className="hidden sm:inline">Bloklar</span>
              </button>
              <button
                onClick={() => setViewMode("cards")}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-md font-semibold transition-all ${
                  viewMode === "cards" ? "bg-white/15 text-white shadow-sm" : "text-zinc-400 hover:text-white"
                }`}
                title="Sektör Kartları (Fintech Grid)"
              >
                <Grid3X3 size={13} />
                <span className="hidden sm:inline">Kartlar</span>
              </button>
            </div>

            <button
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-bold transition-all bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30"
              title="Haritayı Yenile"
            >
              <RefreshCw size={13} className={isRefreshing ? "animate-spin" : ""} />
              <span className="hidden sm:inline">Yenile</span>
            </button>
          </div>
        </div>

        {/* 2. HIZLI SEKTÖR FİLTRE HAPLARI */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 select-none text-xs">
          <button
            onClick={() => setSelectedSector("ALL")}
            className={`px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer whitespace-nowrap ${
              selectedSector === "ALL"
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold shadow-sm"
                : "bg-zinc-900/80 text-zinc-400 border border-white/5 hover:text-white"
            }`}
          >
            Tüm Sektörler ({sectors.length})
          </button>
          {sectors.map((s) => {
            const isPos = s.change_pct >= 0;
            return (
              <button
                key={s.name}
                onClick={() => setSelectedSector(s.name)}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
                  selectedSector === s.name
                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold shadow-sm"
                    : "bg-zinc-900/80 text-zinc-400 border border-white/5 hover:text-white"
                }`}
              >
                <span>{s.name}</span>
                <span className={`text-[11px] font-mono font-bold ${isPos ? "text-emerald-400" : "text-rose-400"}`}>
                  {isPos ? "+" : ""}{s.change_pct.toFixed(1)}%
                </span>
              </button>
            );
          })}
        </div>

        {/* 3. GÖRÜNÜM MODU A: BLOK ISI HARİTASI (TREEMAP BLOKLARI) */}
        {viewMode === "blocks" && (
          <div className="space-y-3">
            {filteredSectors.map((sector) => {
              const isPos = sector.change_pct >= 0;
              return (
                <div
                  key={sector.name}
                  className="p-3.5 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg space-y-2.5"
                >
                  {/* Sektör Başlığı & İstatistikleri */}
                  <div className="flex items-center justify-between border-b border-white/[0.06] pb-2 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full" style={{ background: isPos ? "#10b981" : "#f43f5e" }} />
                      <h2 className="text-sm font-bold text-white tracking-wide">{sector.name}</h2>
                      <span className="text-[11px] text-zinc-400 font-data">
                        (Ağırlık: %{sector.weight} · Hacim: {sector.volume_total})
                      </span>
                    </div>

                    <span
                      className="text-xs font-extrabold font-data px-2 py-0.5 rounded"
                      style={{
                        background: isPos ? "rgba(16,185,129,0.15)" : "rgba(244,63,94,0.15)",
                        color: isPos ? "#34d399" : "#fda4af",
                        border: `1px solid ${isPos ? "rgba(16,185,129,0.3)" : "rgba(244,63,94,0.3)"}`,
                      }}
                    >
                      {isPos ? "+" : ""}{sector.change_pct.toFixed(2)}%
                    </span>
                  </div>

                  {/* Hisse Blokları Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-2">
                    {sector.stocks.map((st) => {
                      const colors = getHeatmapColor(st.change_pct);
                      return (
                        <div
                          key={st.symbol}
                          onClick={() => router.push(`/asset?ticker=${st.symbol}`)}
                          className="p-2.5 rounded-lg transition-all duration-150 hover:scale-[1.03] hover:shadow-lg cursor-pointer flex flex-col justify-between space-y-1 relative group"
                          style={{
                            background: colors.bg,
                            border: `1px solid ${colors.border}`,
                          }}
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-sm text-white font-data">{st.symbol}</span>
                            <ArrowUpRight size={12} className="opacity-0 group-hover:opacity-100 text-white transition-opacity" />
                          </div>

                          <div className="flex items-baseline justify-between font-data">
                            <span className="text-xs text-zinc-200 font-semibold">₺{st.price.toFixed(2)}</span>
                            <span className="text-xs font-extrabold" style={{ color: colors.text }}>
                              {st.change_pct >= 0 ? "+" : ""}{st.change_pct.toFixed(2)}%
                            </span>
                          </div>

                          <div className="flex items-center justify-between text-[11px] text-zinc-400 font-data border-t border-white/10 pt-1">
                            <span>{st.volume || "—"}</span>
                            <span className="font-semibold text-emerald-400">Skor: {st.score}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* 4. GÖRÜNÜM MODU B: SEKTÖR PERFORMANS KARTLARI (GRID) */}
        {viewMode === "cards" && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {filteredSectors.map((sector) => {
              const isPos = sector.change_pct >= 0;
              const borderClr = isPos ? "#10b981" : "#f43f5e";

              return (
                <div
                  key={sector.name}
                  className="rounded-xl p-4 space-y-3 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg hover:border-white/20 transition-all"
                  style={{ borderTop: `3px solid ${borderClr}` }}
                >
                  <div className="flex items-center justify-between pb-2 border-b border-white/[0.06]">
                    <div>
                      <h3 className="text-sm font-bold text-white">{sector.name}</h3>
                      <span className="text-[11px] text-zinc-400 font-data">
                        Ağırlık: %{sector.weight} · Hacim: {sector.volume_total}
                      </span>
                    </div>

                    <span
                      className="text-xs font-extrabold font-data px-2.5 py-0.5 rounded-full"
                      style={{
                        background: isPos ? "rgba(16,185,129,0.12)" : "rgba(244,63,94,0.12)",
                        color: isPos ? "#10b981" : "#f43f5e",
                      }}
                    >
                      {isPos ? "+" : ""}{sector.change_pct.toFixed(2)}%
                    </span>
                  </div>

                  {/* Sektör Hisseleri Listesi */}
                  <div className="space-y-1.5 max-h-72 overflow-y-auto custom-scrollbar pr-1">
                    {sector.stocks.map((st) => {
                      const stPos = st.change_pct >= 0;
                      return (
                        <div
                          key={st.symbol}
                          onClick={() => router.push(`/asset?ticker=${st.symbol}`)}
                          className="p-2.5 rounded-lg flex items-center justify-between transition-all hover:bg-white/[0.06] hover:scale-[1.01] cursor-pointer"
                          style={{
                            background: stPos ? "rgba(16,185,129,0.04)" : "rgba(244,63,94,0.04)",
                            border: `1px solid ${stPos ? "rgba(16,185,129,0.12)" : "rgba(244,63,94,0.12)"}`,
                          }}
                        >
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-sm font-data text-white">{st.symbol}</span>
                              <span className="text-xs text-zinc-400 truncate max-w-[130px]">{st.name || st.symbol}</span>
                            </div>
                            <div className="flex items-center gap-2 text-[11px] font-data text-zinc-400 mt-0.5">
                              <span>Hacim: {st.volume || "—"}</span>
                              <span>·</span>
                              <span className="text-emerald-400 font-bold">Skor: {st.score}</span>
                            </div>
                          </div>
                          <div className="text-right">
                            <span className="text-xs font-bold font-data block text-zinc-100">₺{st.price.toFixed(2)}</span>
                            <span
                              className="text-xs font-bold font-data"
                              style={{ color: stPos ? "#10b981" : "#f43f5e" }}
                            >
                              {stPos ? "+" : ""}{st.change_pct.toFixed(2)}%
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

      </div>
    </ErrorBoundary>
  );
}
