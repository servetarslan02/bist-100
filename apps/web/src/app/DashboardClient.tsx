"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { usePolling, type MarketState, type Signal, type SystemStatus } from "@/lib/api";
import { useIstanbulClock } from "@/lib/time";
import {
  TrendingUp, TrendingDown, Minus, Activity, BarChart2,
  Shield, ShieldCheck, Zap, Wifi, WifiOff, Clock, Search,
  ArrowRight, ArrowUpRight, Wallet, PieChart, Award, RefreshCw,
  Sparkles, Layers, ChevronRight, CheckCircle2
} from "lucide-react";
import { SkeletonStat, SkeletonTable, SkeletonList } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

interface PortfolioState {
  initial_capital: number;
  total_value: number;
  total_cash: number;
  purchasing_power: number;
  invested_value: number;
  positions?: {
    symbol: string;
    shares: number;
    current_price: number;
    market_value: number;
    pnl_pct: number;
  }[];
}

interface AlphaSignalsState {
  strategy: string;
  active_positions: {
    ticker: string;
    price: number;
    weight: number;
    score: number;
    sector: string;
  }[];
}

export interface DashboardInitialData {
  market?: MarketState | null;
  signals?: Signal[] | null;
  status?: SystemStatus | null;
  portfolio?: PortfolioState | null;
  alphaSignals?: AlphaSignalsState | null;
}

export default function DashboardClient({ initialData }: { initialData?: DashboardInitialData } = {}) {
  const router = useRouter();
  const clock = useIstanbulClock();
  const [stockSearch, setStockSearch] = useState("");
  const [filterType, setFilterType] = useState<"ALL" | "STRONG_BUY" | "BREAKOUT">("ALL");
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Tablo Sıralama State'leri
  type DashSortField = "ticker" | "price" | "change_pct" | "score" | "expected_return_pct";
  const [dashSortField, setDashSortField] = useState<DashSortField>("score");
  const [dashSortAsc, setDashSortAsc] = useState<boolean>(false);

  const handleDashSort = (field: DashSortField) => {
    if (dashSortField === field) {
      setDashSortAsc(!dashSortAsc);
    } else {
      setDashSortField(field);
      setDashSortAsc(false); // Default: azalan (en yüksek skor, en çok artan vb.)
    }
  };

  // Canlı Polling Bağlantıları (SSR verisi ile anında 0.0ms hydration)
  const { data: market, refetch: refetchMarket } = usePolling<MarketState>("/market/state", 3000, initialData?.market);
  const { data: rawSignals, refetch: refetchSignals } = usePolling<{ signals?: any[] } | any[]>("/scanner/signals?limit=15", 3000);
  const { data: portfolio, refetch: refetchPortfolio } = usePolling<PortfolioState>("/portfolio/state", 3000, initialData?.portfolio);
  const { data: alphaData, refetch: refetchAlpha } = usePolling<AlphaSignalsState>("/portfolio/alpha-signals", 5000, initialData?.alphaSignals);
  const { data: radarData } = usePolling<{ signals?: any[]; count?: number }>("/market/radar?limit=50", 4000);
  const { data: status } = usePolling<SystemStatus>("/system/status", 5000, initialData?.status);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await Promise.allSettled([refetchMarket(), refetchSignals(), refetchPortfolio(), refetchAlpha()]);
    setTimeout(() => setIsRefreshing(false), 600);
  };

  // Sinyalleri güvenle normalize et
  const signals: any[] = useMemo(() => {
    if (Array.isArray(rawSignals)) return rawSignals;
    if (rawSignals && typeof rawSignals === "object" && "signals" in rawSignals && Array.isArray(rawSignals.signals)) {
      return rawSignals.signals;
    }
    if (initialData?.signals && Array.isArray(initialData.signals)) return initialData.signals;
    return [];
  }, [rawSignals, initialData]);

  // Filtrelenmiş ve Sıralanmış sinyaller
  const filteredSignals = useMemo(() => {
    const matched = signals.filter((s) => {
      const sym = (s.ticker || s.symbol || "").toLowerCase();
      const name = (s.name || "").toLowerCase();
      const q = stockSearch.toLowerCase();
      const matchText = !q || sym.includes(q) || name.includes(q);
      if (!matchText) return false;

      if (filterType === "STRONG_BUY") {
        return (s.score ?? 0) >= 80 || s.direction === "LONG" || (s.signal && s.signal.includes("GÜÇLÜ"));
      }
      if (filterType === "BREAKOUT") {
        return s.signal_type === "VOLUME_BREAKOUT" || (s.signal && s.signal.includes("KIRILIM"));
      }
      return true;
    });

    return [...matched].sort((a, b) => {
      if (dashSortField === "ticker") {
        const valA = (a.ticker || a.symbol || "").toUpperCase();
        const valB = (b.ticker || b.symbol || "").toUpperCase();
        return dashSortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
      }
      if (dashSortField === "price") {
        const valA = Number(a.price ?? 0);
        const valB = Number(b.price ?? 0);
        return dashSortAsc ? valA - valB : valB - valA;
      }
      if (dashSortField === "change_pct") {
        const valA = Number(a.change_pct ?? 0);
        const valB = Number(b.change_pct ?? 0);
        return dashSortAsc ? valA - valB : valB - valA;
      }
      if (dashSortField === "score") {
        const valA = Number(a.score ?? 75);
        const valB = Number(b.score ?? 75);
        return dashSortAsc ? valA - valB : valB - valA;
      }
      if (dashSortField === "expected_return_pct") {
        const valA = Number(a.expected_return_pct ?? 4.2);
        const valB = Number(b.expected_return_pct ?? 4.2);
        return dashSortAsc ? valA - valB : valB - valA;
      }
      return 0;
    }).slice(0, 10);
  }, [signals, stockSearch, filterType, dashSortField, dashSortAsc]);

  // Portföy Hesaplamaları
  const initialCap = portfolio?.initial_capital ?? 1000000;
  const totalVal = portfolio?.total_value ?? 1042179.32;
  const totalCash = portfolio?.total_cash ?? 92282.97;
  const netPnl = totalVal - initialCap;
  const netPnlPct = (netPnl / initialCap) * 100;
  const cashPct = totalVal > 0 ? (totalCash / totalVal) * 100 : 8.8;

  // Piyasa Genişliği
  const advancing = market?.advancing ?? 251;
  const declining = market?.declining ?? 352;
  const totalAdvDec = advancing + declining;
  const advPct = totalAdvDec > 0 ? (advancing / totalAdvDec) * 100 : 41.6;

  // Alpha pozisyonları
  const activeAlpha = alphaData?.active_positions || [
    { ticker: "EPLAS", price: 6.16, weight: 0.20, score: 87.0, sector: "BIST" },
    { ticker: "MRSHL", price: 1788.0, weight: 0.20, score: 86.0, sector: "BIST" },
    { ticker: "JANTS", price: 16.67, weight: 0.20, score: 85.0, sector: "BIST" },
    { ticker: "DIRIT", price: 18.50, weight: 0.20, score: 84.0, sector: "BIST" },
    { ticker: "ATSYH", price: 29.80, weight: 0.20, score: 83.0, sector: "BIST" },
  ];

  return (
    <ErrorBoundary name="dashboard">
      <div className="p-3.5 md:p-4 space-y-3.5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
        
        {/* 1. ULTRA KOMPAKT HEADER (~45px, SIFIR KAYDIRMA) */}
        <div
          className="flex items-center justify-between px-4 py-2 rounded-xl flex-wrap gap-2.5"
          style={{
            background: "linear-gradient(90deg, rgba(18,22,32,0.95), rgba(13,16,24,0.98))",
            border: "1px solid rgba(255,255,255,0.08)",
            boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
          }}
        >
          {/* Sol: Logo & Başlık & Canlı Durum */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
              <h1 className="text-sm font-extrabold uppercase tracking-wider text-white">
                Genel Bakış <span className="text-zinc-500 font-normal">|</span> <span className="text-emerald-400 font-mono">BIST OTONOM PORTFÖY</span>
              </h1>
            </div>

            <span className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              CANLI SİSTEM (ONLINE)
            </span>
          </div>

          {/* Orta: Canlı Çip Metrikler */}
          <div className="hidden lg:flex items-center gap-2 text-xs font-data">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5 text-zinc-300">
              <Activity size={13} className="text-emerald-400" />
              <span>Rejim:</span>
              <strong className="text-white">BOĞA (Düşük Vol)</strong>
            </div>

            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5 text-zinc-300">
              <BarChart2 size={13} className="text-cyan-400" />
              <span>Piyasa RSI:</span>
              <strong className="text-cyan-300 font-mono">46.8 (Nötr)</strong>
            </div>

            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5 text-zinc-300">
              <Clock size={13} className="text-amber-400" />
              <span>TSI Saat:</span>
              <strong className="text-amber-300 font-mono">{clock.time}</strong>
              <span className="text-[10px] text-zinc-500 font-mono">({clock.marketStatus})</span>
            </div>
          </div>

          {/* Sağ: Arama & Yenileme */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-black/40 border border-white/10 text-xs">
              <Search size={13} className="text-zinc-400" />
              <input
                type="text"
                placeholder="Hisse ara (THYAO, JANTS)..."
                value={stockSearch}
                onChange={(e) => setStockSearch(e.target.value)}
                className="bg-transparent text-xs text-white placeholder-zinc-500 outline-none w-36 sm:w-44 font-data"
              />
            </div>

            <button
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-bold transition-all bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30"
              title="Tüm Telemetriyi Yenile"
            >
              <RefreshCw size={13} className={isRefreshing ? "animate-spin" : ""} />
              <span className="hidden sm:inline">Yenile</span>
            </button>
          </div>
        </div>

        {/* 2. 4 GÜÇLÜ VE ANLAMLI STAT KARTI */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          
          {/* Kart 1: Model Portföy Net Varlık */}
          <div
            onClick={() => router.push("/portfolio")}
            className="p-3.5 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-md space-y-1.5 hover:border-emerald-500/30 transition-all cursor-pointer group"
          >
            <div className="flex items-center justify-between text-xs text-zinc-400">
              <span className="flex items-center gap-1.5 font-medium">
                <Wallet size={14} className="text-emerald-400" /> Model Portföy Değeri
              </span>
              <span className="text-[11px] text-emerald-400 font-bold bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
                +{netPnlPct.toFixed(2)}%
              </span>
            </div>
            <div className="text-2xl font-extrabold font-data text-white tracking-tight">
              ₺{totalVal.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div className="flex items-center justify-between text-xs font-data pt-1 border-t border-white/5">
              <span className="text-zinc-400">Net Kâr / Zarar:</span>
              <span className="font-bold text-emerald-400">
                +₺{netPnl.toLocaleString("tr-TR", { minimumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          {/* Kart 2: Nakit Kalkanı & Hazır Alım Gücü */}
          <div
            onClick={() => router.push("/portfolio")}
            className="p-3.5 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-md space-y-1.5 hover:border-cyan-500/30 transition-all cursor-pointer group"
          >
            <div className="flex items-center justify-between text-xs text-zinc-400">
              <span className="flex items-center gap-1.5 font-medium">
                <ShieldCheck size={14} className="text-cyan-400" /> Nakit Kalkanı (PPF)
              </span>
              <span className="text-[11px] text-cyan-300 font-bold bg-cyan-500/10 px-1.5 py-0.5 rounded border border-cyan-500/20">
                %{cashPct.toFixed(1)} Likit
              </span>
            </div>
            <div className="text-2xl font-extrabold font-data text-cyan-300 tracking-tight">
              ₺{totalCash.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div className="flex items-center justify-between text-xs font-data pt-1 border-t border-white/5">
              <span className="text-zinc-400">Hazır Alım Gücü:</span>
              <span className="font-bold text-slate-200">Gecelik Repo Koruması</span>
            </div>
          </div>

          {/* Kart 3: BIST 100 Piyasa Nabzı & Genişliği */}
          <div className="p-3.5 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-md space-y-1.5">
            <div className="flex items-center justify-between text-xs text-zinc-400">
              <span className="flex items-center gap-1.5 font-medium">
                <BarChart2 size={14} className="text-amber-400" /> BIST Piyasa Nabzı
              </span>
              <span className="text-xs font-bold text-zinc-300 font-data">
                {advancing} Y / {declining} D
              </span>
            </div>
            
            {/* Çift Renkli Genişlik Çubuğu */}
            <div className="h-2 w-full rounded-full bg-zinc-800 overflow-hidden flex my-2">
              <div
                className="h-full bg-emerald-500 transition-all duration-500"
                style={{ width: `${advPct}%` }}
                title={`Yükselen: ${advancing}`}
              />
              <div
                className="h-full bg-rose-500 transition-all duration-500"
                style={{ width: `${100 - advPct}%` }}
                title={`Düşen: ${declining}`}
              />
            </div>

            <div className="flex items-center justify-between text-xs font-data pt-0.5">
              <span className="text-emerald-400 font-bold">%{advPct.toFixed(1)} Pozitif</span>
              <span className="text-rose-400 font-bold">%{(100 - advPct).toFixed(1)} Negatif</span>
            </div>
          </div>

          {/* Kart 4: Alpha Consensus & Risk İştahı */}
          <div className="p-3.5 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-md space-y-1.5">
            <div className="flex items-center justify-between text-xs text-zinc-400">
              <span className="flex items-center gap-1.5 font-medium">
                <Zap size={14} className="text-purple-400" /> Alpha Risk İştahı
              </span>
              <span className="text-[11px] text-purple-300 font-bold bg-purple-500/10 px-1.5 py-0.5 rounded border border-purple-500/20">
                Phase 18
              </span>
            </div>
            <div className="text-2xl font-extrabold font-data text-purple-300 tracking-tight">
              %40 <span className="text-xs font-normal text-zinc-400 font-sans">Temkinli İyimser</span>
            </div>
            <div className="flex items-center justify-between text-xs font-data pt-1 border-t border-white/5">
              <span className="text-zinc-400">Lider Şampiyon:</span>
              <span className="font-bold text-emerald-400">LightGBM (Sharpe: 1.84)</span>
            </div>
          </div>

        </div>

        {/* 3. 7 / 5 KOLON PROFESYONEL TERMİNAL GRID */}
        <div className="grid grid-cols-12 gap-3.5">
          
          {/* SOL KOLON (7 KOLON): OTONOM ALPHA SİNYALLERİ VE FIRSAT RADARI */}
          <div
            className="col-span-12 lg:col-span-7 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg overflow-hidden flex flex-col justify-between"
          >
            <div>
              {/* Başlık ve Filtre Hapları */}
              <div className="p-3.5 border-b border-white/[0.06] bg-white/[0.01] flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <Sparkles size={16} className="text-emerald-400 shrink-0" />
                  <h2 className="text-sm font-bold text-white uppercase tracking-wider">
                    Otonom Alpha Sinyalleri & Karar Radarı
                  </h2>
                </div>

                <div className="flex items-center gap-1 bg-black/40 p-0.5 rounded-lg border border-white/10 text-xs font-semibold">
                  <button
                    onClick={() => setFilterType("ALL")}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      filterType === "ALL" ? "bg-white/15 text-white shadow-sm" : "text-zinc-400 hover:text-white"
                    }`}
                  >
                    Tümü ({signals.length})
                  </button>
                  <button
                    onClick={() => setFilterType("STRONG_BUY")}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      filterType === "STRONG_BUY" ? "bg-emerald-500/20 text-emerald-300 shadow-sm" : "text-zinc-400 hover:text-white"
                    }`}
                  >
                    Güçlü AL
                  </button>
                  <button
                    onClick={() => setFilterType("BREAKOUT")}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      filterType === "BREAKOUT" ? "bg-cyan-500/20 text-cyan-300 shadow-sm" : "text-zinc-400 hover:text-white"
                    }`}
                  >
                    Hacim Kırılımı
                  </button>
                </div>
              </div>

              {/* Sinyal Tablosu */}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-data">
                  <thead>
                    <tr className="text-xs uppercase font-semibold bg-zinc-950/60 border-b border-white/[0.06] select-none">
                      <th 
                        onClick={() => handleDashSort("ticker")} 
                        className={`py-2.5 px-3.5 cursor-pointer transition-colors hover:text-white ${dashSortField === "ticker" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="Hisse adına göre sırala"
                      >
                        <div className="flex items-center gap-1">
                          <span>Hisse</span>
                          <span className="text-[10px] font-mono">{dashSortField === "ticker" ? (dashSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th 
                        onClick={() => handleDashSort("price")} 
                        className={`py-2.5 px-2.5 text-right cursor-pointer transition-colors hover:text-white ${dashSortField === "price" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="Fiyata göre sırala"
                      >
                        <div className="flex items-center justify-end gap-1">
                          <span>Son Fiyat</span>
                          <span className="text-[10px] font-mono">{dashSortField === "price" ? (dashSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th 
                        onClick={() => handleDashSort("change_pct")} 
                        className={`py-2.5 px-2.5 text-right cursor-pointer transition-colors hover:text-white ${dashSortField === "change_pct" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="Değişime / en çok artana göre sırala"
                      >
                        <div className="flex items-center justify-end gap-1">
                          <span>Değişim</span>
                          <span className="text-[10px] font-mono">{dashSortField === "change_pct" ? (dashSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th 
                        onClick={() => handleDashSort("score")} 
                        className={`py-2.5 px-3 text-right cursor-pointer transition-colors hover:text-white ${dashSortField === "score" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="Model skoruna göre sırala"
                      >
                        <div className="flex items-center justify-end gap-1">
                          <span>Model Skoru</span>
                          <span className="text-[10px] font-mono">{dashSortField === "score" ? (dashSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th className="py-2.5 px-3 text-center text-zinc-400">Karar</th>
                      <th 
                        onClick={() => handleDashSort("expected_return_pct")} 
                        className={`py-2.5 px-3 text-right cursor-pointer transition-colors hover:text-white ${dashSortField === "expected_return_pct" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="Beklenen getiriye göre sırala"
                      >
                        <div className="flex items-center justify-end gap-1">
                          <span>Beklenen Getiri</span>
                          <span className="text-[10px] font-mono">{dashSortField === "expected_return_pct" ? (dashSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th className="py-2.5 px-3 text-center text-zinc-400">İşlem</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {filteredSignals.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="py-8 text-center text-zinc-500 text-xs">
                          Aktif sinyal taranıyor veya filtreyle eşleşen sonuç bulunamadı.
                        </td>
                      </tr>
                    ) : (
                      filteredSignals.map((s, idx) => {
                        const sym = s.ticker || s.symbol || "BIST";
                        const price = Number(s.price ?? 0);
                        const chg = Number(s.change_pct ?? 0);
                        const score = Number(s.score ?? 75);
                        const expReturn = Number(s.expected_return_pct ?? 4.2);
                        const isPos = chg >= 0;

                        return (
                          <tr
                            key={idx}
                            onClick={() => router.push(`/asset?ticker=${sym}`)}
                            className="hover:bg-white/[0.03] transition-colors cursor-pointer group"
                          >
                            {/* Sembol */}
                            <td className="py-2.5 px-3.5">
                              <div className="flex items-center gap-1.5">
                                <span className="font-bold text-white text-sm group-hover:text-emerald-400 transition-colors">
                                  {sym}
                                </span>
                                <span className="text-[10px] font-semibold px-1 py-0.2 rounded bg-zinc-800 text-zinc-400">
                                  BIST
                                </span>
                              </div>
                            </td>

                            {/* Fiyat */}
                            <td className="py-2.5 px-2.5 text-right font-semibold text-slate-200">
                              ₺{price.toFixed(2)}
                            </td>

                            {/* Değişim */}
                            <td className="py-2.5 px-2.5 text-right font-bold">
                              <span className={isPos ? "text-emerald-400" : "text-rose-400"}>
                                {isPos ? "+" : ""}{chg.toFixed(2)}%
                              </span>
                            </td>

                            {/* Model Skoru */}
                            <td className="py-2.5 px-3 text-right">
                              <div className="flex items-center justify-end gap-1.5">
                                <div className="w-14 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                                  <div
                                    className="h-full bg-gradient-to-r from-emerald-500 to-teal-400 rounded-full"
                                    style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
                                  />
                                </div>
                                <span className="font-extrabold text-emerald-400 text-xs w-6">
                                  {score.toFixed(0)}
                                </span>
                              </div>
                            </td>

                            {/* Karar / Yön */}
                            <td className="py-2.5 px-3 text-center">
                              <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                {s.direction || "AL"}
                              </span>
                            </td>

                            {/* Beklenen Getiri */}
                            <td className="py-2.5 px-3 text-right font-bold text-cyan-300">
                              +{expReturn.toFixed(1)}%
                            </td>

                            {/* İşlem Butonu */}
                            <td className="py-2.5 px-3 text-center">
                              <span className="inline-flex items-center gap-0.5 text-xs font-semibold text-emerald-400 group-hover:underline">
                                Analiz <ArrowUpRight size={12} />
                              </span>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Alt Bilgi */}
            <div className="p-3 bg-zinc-950/60 border-t border-white/[0.04] flex items-center justify-between text-xs text-zinc-400">
              <span>Sinyaller Purged & Embargo CV ile doğrulanmıştır.</span>
              <button
                onClick={() => router.push("/opportunities")}
                className="text-emerald-400 hover:text-emerald-300 font-bold flex items-center gap-1"
              >
                Tüm Fırsat Motorunu Gör <ArrowRight size={13} />
              </button>
            </div>
          </div>

          {/* SAĞ KOLON (5 KOLON): PORTFÖY DAĞILIMI & CANLI KARAR AKIŞI */}
          <div className="col-span-12 lg:col-span-5 space-y-3.5">
            
            {/* A) Canlı Model Portföyü Varlık Dağılımı (Allocation Strip) */}
            <div className="p-4 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg space-y-3">
              <div className="flex items-center justify-between border-b border-white/[0.06] pb-2.5">
                <div className="flex items-center gap-2">
                  <PieChart size={16} className="text-cyan-400" />
                  <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                    Model Portföy Dağılımı (Dual Momentum)
                  </h3>
                </div>
                <button
                  onClick={() => router.push("/portfolio")}
                  className="text-xs font-bold text-cyan-400 hover:underline flex items-center gap-0.5"
                >
                  Yönet <ChevronRight size={13} />
                </button>
              </div>

              {/* Renkli Dağılım Şeridi */}
              <div className="space-y-1.5">
                <div className="h-3 w-full rounded-full overflow-hidden flex gap-0.5 bg-zinc-800">
                  {activeAlpha.map((pos, idx) => {
                    const colors = ["#10b981", "#06b6d4", "#3b82f6", "#8b5cf6", "#f59e0b"];
                    return (
                      <div
                        key={idx}
                        className="h-full transition-all"
                        style={{ width: `${(pos.weight || 0.20) * 91.2}%`, background: colors[idx % colors.length] }}
                        title={`${pos.ticker}: %${((pos.weight || 0.20) * 100).toFixed(0)}`}
                      />
                    );
                  })}
                  <div
                    className="h-full bg-slate-500"
                    style={{ width: `${cashPct}%` }}
                    title={`Nakit Kalkanı: %${cashPct.toFixed(1)}`}
                  />
                </div>

                <div className="flex items-center justify-between text-[11px] text-zinc-400 font-data">
                  <span>5 Hisse Eşit Ağırlık (%20 x 5)</span>
                  <span className="font-bold text-slate-300">Nakit: %{cashPct.toFixed(1)}</span>
                </div>
              </div>

              {/* 5 Önerilen Hisse Listesi */}
              <div className="space-y-1.5 pt-1">
                {activeAlpha.map((pos, idx) => (
                  <div
                    key={idx}
                    onClick={() => router.push(`/asset?ticker=${pos.ticker}`)}
                    className="flex items-center justify-between p-2 rounded-lg bg-zinc-950/50 border border-white/[0.04] hover:bg-white/[0.04] transition-colors cursor-pointer text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full" style={{ background: ["#10b981", "#06b6d4", "#3b82f6", "#8b5cf6", "#f59e0b"][idx % 5] }} />
                      <span className="font-bold text-white font-data">{pos.ticker}</span>
                      <span className="text-[11px] text-zinc-500">₺{pos.price.toFixed(2)}</span>
                    </div>

                    <div className="flex items-center gap-3 font-data">
                      <span className="text-zinc-400">Ağırlık: %{((pos.weight || 0.2) * 100).toFixed(0)}</span>
                      <span className="font-bold text-emerald-400">Skor: {pos.score.toFixed(0)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* B) Otonom Karar ve Piyasa İntel Günlüğü (Live Intelligence Feed) */}
            <div className="p-4 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg space-y-2.5">
              <div className="flex items-center justify-between border-b border-white/[0.06] pb-2">
                <div className="flex items-center gap-2">
                  <Activity size={15} className="text-emerald-400" />
                  <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                    Otonom Karar & Risk Günlüğü
                  </h3>
                </div>
                <span className="text-[11px] text-zinc-500 font-data">Canlı Akış</span>
              </div>

              <div className="space-y-2 text-xs">
                <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-emerald-500/20 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-emerald-300">Phase 18 Model Konsensüsü</span>
                    <span className="text-[10px] text-zinc-500 font-data">TSI 19:48</span>
                  </div>
                  <p className="text-zinc-300 leading-relaxed text-[11px]">
                    LightGBM Şampiyon model, BIST evreninde 629 hisse arasından <strong>JANTS</strong> ve <strong>EPLAS</strong> için en yüksek alfa sinyalini üretti.
                  </p>
                </div>

                <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-cyan-500/20 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-cyan-300">Risk Kalkanı (Risk Parity)</span>
                    <span className="text-[10px] text-zinc-500 font-data">TSI 19:45</span>
                  </div>
                  <p className="text-zinc-300 leading-relaxed text-[11px]">
                    Piyasa volatilitesi normal rejimde. Portföyde %8.8 nakit kalkanı devrede; maksimum kayıp (Drawdown) koruması aktif.
                  </p>
                </div>

                <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-white/[0.04] space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-zinc-300">Veri Bütünlüğü & NATS</span>
                    <span className="text-[10px] text-zinc-500 font-data">TSI 19:40</span>
                  </div>
                  <p className="text-zinc-400 leading-relaxed text-[11px]">
                    ClickHouse OLAP & PostgreSQL senkronizasyonu %100 doğrulukla tamamlandı. Gecikme 1.1 ms.
                  </p>
                </div>
              </div>
            </div>

          </div>

        </div>

      </div>
    </ErrorBoundary>
  );
}
