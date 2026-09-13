"use client";

import { useState, useMemo, useEffect } from "react";
import { useRouter } from "next/navigation";
import { usePolling, useDebounce } from "@/lib/api";
import {
  Target, ArrowUpRight, ArrowDownRight, Flame, Eye, Star, Layers,
  TrendingUp, ShieldAlert, BarChart3, Zap, Filter, Search, RefreshCw, ExternalLink
} from "lucide-react";
import { SkeletonList, SkeletonCard, SkeletonTable, SkeletonChart } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

interface OpportunitySignal {
  ticker: string;
  symbol: string;
  name: string;
  company_name?: string;
  confidence_score?: number;
  price: number;
  change_pct: number;
  score: number;
  direction: "LONG" | "SHORT";
  signal: string;
  signal_type: string;
  spec_category: "HIGH_CONVICTION" | "CANDIDATE" | "WATCH" | "NORMAL";
  spec_reason: string;
  expected_return_pct: number;
  target_price: number;
  target_price_2: number;
  stop_loss: number;
  risk_reward_ratio: number;
  rsi: number;
  volume_ratio: number;
  momentum_1m: number;
  momentum_3m: number;
  horizon: string;
  risk_level: string;
  [key: string]: any;
}

const CAT_FILTERS = [
  { id: "ALL", label: "Tüm Fırsatlar", icon: Layers },
  { id: "HIGH_CONVICTION", label: "Yüksek Güven", icon: Flame, color: "#ff4466" },
  { id: "VOLUME_BREAKOUT", label: "Hacim Kırılımı", icon: Zap, color: "#ffaa00" },
  { id: "PULLBACK_BOUNCE", label: "Dip / Swing", icon: Target, color: "#00e5a0" },
  { id: "MOMENTUM_LEADER", label: "Trend Lideri", icon: TrendingUp, color: "#00c8ff" },
];

export default function OpportunitiesPage() {
  const router = useRouter();
  const { data: rawSignals, loading, refetch } = usePolling<OpportunitySignal[] | { signals: OpportunitySignal[] }>(
    "/scanner/signals?limit=50",
    10000
  );

  const [activeFilter, setActiveFilter] = useState<string>("ALL");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const debouncedSearch = useDebounce(searchTerm, 150);
  const [flashMap, setFlashMap] = useState<Record<string, "up" | "down">>({});
  const prevPricesRef = useState<Record<string, number>>({})[0];

  const signals = useMemo(() => {
    if (!rawSignals) return [];
    const list = Array.isArray(rawSignals) ? rawSignals : (rawSignals.signals || []);
    return list;
  }, [rawSignals]);

  useEffect(() => {
    if (!signals || signals.length === 0) return;
    const nextFlash: Record<string, "up" | "down"> = {};
    for (const s of signals) {
      const sym = s.symbol || s.ticker;
      const price = Number(s.price ?? 0);
      const prev = prevPricesRef[sym];
      if (prev !== undefined && price > 0) {
        if (price > prev) nextFlash[sym] = "up";
        else if (price < prev) nextFlash[sym] = "down";
      }
      prevPricesRef[sym] = price;
    }
    if (Object.keys(nextFlash).length > 0) {
      setFlashMap(nextFlash);
      const timer = setTimeout(() => setFlashMap({}), 1300);
      return () => clearTimeout(timer);
    }
  }, [rawSignals]);

  const filteredSignals = useMemo(() => {
    const matched = signals.filter((s) => {
      // Kategori filtresi
      if (activeFilter !== "ALL") {
        const cat = String(s.spec_category || "");
        const stype = String(s.signal_type || (s as any).strategy_type || "");
        const sig = String(s.signal || "").toUpperCase();
        const tags = Array.isArray((s as any).tags) ? (s as any).tags : [];
        const isHigh = Boolean((s as any).is_high_conviction) || Number(s.score ?? 0) >= 80 || cat === "HIGH_CONVICTION" || tags.includes("HIGH_CONVICTION");

        if (activeFilter === "HIGH_CONVICTION") {
          if (!isHigh) return false;
        } else if (activeFilter === "VOLUME_BREAKOUT") {
          const isVol = stype === "VOLUME_BREAKOUT" || cat === "VOLUME_BREAKOUT" || tags.includes("VOLUME_BREAKOUT") || sig.includes("HACİM") || sig.includes("KIRILIM") || Number(s.volume_ratio ?? 0) >= 1.2;
          if (!isVol) return false;
        } else if (activeFilter === "PULLBACK_BOUNCE") {
          const isDip = stype === "PULLBACK_BOUNCE" || cat === "PULLBACK_BOUNCE" || tags.includes("PULLBACK_BOUNCE") || sig.includes("DİP") || sig.includes("DÖNÜŞ") || Number(s.rsi ?? 50) <= 50;
          if (!isDip) return false;
        } else if (activeFilter === "MOMENTUM_LEADER") {
          const isMom = stype === "MOMENTUM_LEADER" || cat === "MOMENTUM_LEADER" || tags.includes("MOMENTUM_LEADER") || sig.includes("TREND") || sig.includes("MOMENTUM");
          if (!isMom) return false;
        }
      }

      // Arama filtresi with debounce
      if (debouncedSearch) {
        const q = debouncedSearch.toLowerCase().trim();
        const sym = (s.symbol || s.ticker || "").toLowerCase();
        const nm = (s.name || s.company_name || "").toLowerCase();
        const rsn = (s.spec_reason || "").toLowerCase();
        return sym.includes(q) || nm.includes(q) || rsn.includes(q);
      }
      return true;
    });

    // 4. KURAL: Sıralama daima En Çok Güven (score) ve En Yüksek Getiri (expected_return_pct) olmalı
    return [...matched].sort((a, b) => {
      const scoreA = Number(a.score ?? a.confidence_score ?? 0);
      const scoreB = Number(b.score ?? b.confidence_score ?? 0);
      if (scoreB !== scoreA) return scoreB - scoreA;
      const retA = Number(a.expected_return_pct ?? 0);
      const retB = Number(b.expected_return_pct ?? 0);
      return retB - retA;
    });
  }, [signals, activeFilter, debouncedSearch]);

  // Kategori bazlı sinyal sayıları
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {
      ALL: signals.length,
      HIGH_CONVICTION: 0,
      VOLUME_BREAKOUT: 0,
      PULLBACK_BOUNCE: 0,
      MOMENTUM_LEADER: 0,
    };
    for (const s of signals) {
      const cat = String(s.spec_category || "");
      const stype = String(s.signal_type || (s as any).strategy_type || "");
      const sig = String(s.signal || "").toUpperCase();
      const tags = Array.isArray((s as any).tags) ? (s as any).tags : [];

      if (Boolean((s as any).is_high_conviction) || Number(s.score ?? 0) >= 80 || cat === "HIGH_CONVICTION" || tags.includes("HIGH_CONVICTION")) {
        counts.HIGH_CONVICTION++;
      }
      if (stype === "VOLUME_BREAKOUT" || cat === "VOLUME_BREAKOUT" || tags.includes("VOLUME_BREAKOUT") || sig.includes("HACİM") || sig.includes("KIRILIM") || Number(s.volume_ratio ?? 0) >= 1.2) {
        counts.VOLUME_BREAKOUT++;
      }
      if (stype === "PULLBACK_BOUNCE" || cat === "PULLBACK_BOUNCE" || tags.includes("PULLBACK_BOUNCE") || sig.includes("DİP") || sig.includes("DÖNÜŞ") || Number(s.rsi ?? 50) <= 50) {
        counts.PULLBACK_BOUNCE++;
      }
      if (stype === "MOMENTUM_LEADER" || cat === "MOMENTUM_LEADER" || tags.includes("MOMENTUM_LEADER") || sig.includes("TREND") || sig.includes("MOMENTUM")) {
        counts.MOMENTUM_LEADER++;
      }
    }
    return counts;
  }, [signals]);

  // Portföy / Tarama Genel Metrikleri
  const metrics = useMemo(() => {
    if (signals.length === 0) return { total: 0, highConv: 0, avgReturn: 0, avgRR: 0 };
    let sumReturn = 0;
    let sumRR = 0;
    for (const s of signals) {
      sumReturn += Number(s.expected_return_pct ?? 12.0);
      sumRR += Number(s.risk_reward_ratio ?? 2.0);
    }
    return {
      total: signals.length,
      highConv: categoryCounts.HIGH_CONVICTION,
      avgReturn: (sumReturn / signals.length).toFixed(1),
      avgRR: (sumRR / signals.length).toFixed(2),
    };
  }, [signals, categoryCounts]);

  const [viewMode, setViewMode] = useState<"grid" | "table">("grid");

  return (
    <ErrorBoundary name="opportunities">
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold gradient-text">Piyasa Fırsatları & Algoritmik Sinyaller</h1>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              CANLI OTONOM TARAMA
            </span>
          </div>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Phase 18 LightGBM + CatBoost Ensemble · 20G Hacim Kırılımları · Asimetrik R/R Fırsatları
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* View Switcher */}
          <div className="flex items-center p-0.5 rounded-lg bg-zinc-900 border border-zinc-800">
            <button
              onClick={() => setViewMode("grid")}
              className={`px-2.5 py-1 text-xs font-semibold rounded-md transition-colors ${
                viewMode === "grid" ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
              }`}
              title="Kart Görünümü"
            >
              Kartlar
            </button>
            <button
              onClick={() => setViewMode("table")}
              className={`px-2.5 py-1 text-xs font-semibold rounded-md transition-colors ${
                viewMode === "table" ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
              }`}
              title="Tablo Görünümü"
            >
              Tablo
            </button>
          </div>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-xs">
            <Search size={12} className="text-zinc-500" />
            <input
              type="text"
              placeholder="Hisse veya sinyal ara..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-transparent text-zinc-200 focus:outline-none w-36 text-xs"
            />
          </div>
          <button
            onClick={() => refetch()}
            className="p-2 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
            title="Yenile"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* KPI Overview Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
          <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
            <span>Aktif Fırsat</span>
            <Layers size={14} className="text-cyan-400" />
          </div>
          <div className="text-base font-semibold font-data text-zinc-100">{metrics.total} Hisse</div>
          <p className="text-[10px] text-zinc-500">649 BIST hissesi içinden taranan</p>
        </div>

        <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
          <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
            <span>Yüksek Güvenilirlik</span>
            <Flame size={14} className="text-red-400" />
          </div>
          <div className="text-base font-semibold font-data text-red-400">{metrics.highConv} Sinyal</div>
          <p className="text-[10px] text-zinc-500">Skor ≥ 80 asimetrik kurulum</p>
        </div>

        <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
          <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
            <span>Ort. Beklenen Alpha</span>
            <TrendingUp size={14} className="text-emerald-400" />
          </div>
          <div className="text-base font-semibold font-data text-emerald-400">+{metrics.avgReturn}%</div>
          <p className="text-[10px] text-zinc-500">Hedef 1 potansiyel kâr</p>
        </div>

        <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
          <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
            <span>Ort. Risk / Ödül</span>
            <BarChart3 size={14} className="text-amber-400" />
          </div>
          <div className="text-base font-semibold font-data text-amber-400">{metrics.avgRR}x</div>
          <p className="text-[10px] text-zinc-500">Kayıp / Kazanç asimetrisi</p>
        </div>
      </div>

      {/* Filter Tabs with Counter Badges */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 custom-scrollbar">
        {CAT_FILTERS.map((f) => {
          const Icon = f.icon;
          const isActive = activeFilter === f.id;
          const count = categoryCounts[f.id] ?? 0;
          return (
            <button
              key={f.id}
              onClick={() => setActiveFilter(f.id)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                isActive
                  ? "bg-zinc-100 text-zinc-900 shadow-md"
                  : "bg-zinc-900/80 text-zinc-400 hover:text-zinc-200 border border-zinc-800"
              }`}
            >
              <Icon size={12} style={{ color: isActive ? "#000" : f.color }} />
              <span>{f.label}</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                  isActive ? "bg-zinc-900 text-zinc-100" : "bg-zinc-800 text-zinc-400"
                }`}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Main Content: Grid or Table */}
      {filteredSignals.length === 0 ? (
        <div className="text-center py-16 text-zinc-500 text-xs rounded-xl bg-zinc-900/30 border border-zinc-800/50">
          {loading ? <SkeletonList count={5} /> : "Bu kriterde aktif sinyal bulunamadı."}
        </div>
      ) : viewMode === "grid" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredSignals.map((sig) => {
            const sym = sig.symbol || sig.ticker;
            const isHighConviction = Boolean((sig as any).is_high_conviction) || sig.spec_category === "HIGH_CONVICTION" || (sig.score ?? 0) >= 80;
            const flashDir = flashMap[sym];
            const flashClass = flashDir === "up" ? "flash-up" : (flashDir === "down" ? "flash-down" : "");
            const currentPrice = Number(sig.price ?? 50.0);
            const targetPrice = Number(sig.target_price ?? (currentPrice * 1.12));
            const stopLoss = Number(sig.stop_loss ?? (currentPrice * 0.94));

            // Risk reward progress position (0 to 100%)
            const totalSpan = Math.max(targetPrice - stopLoss, 0.01);
            const currentOffset = Math.max(0, Math.min(100, ((currentPrice - stopLoss) / totalSpan) * 100));

            return (
              <div
                key={sig.symbol}
                onClick={() => router.push(`/asset?symbol=${sig.symbol}`)}
                className={`rounded-xl p-4.5 bg-zinc-900/50 hover:bg-zinc-900/80 border border-zinc-800/80 hover:border-zinc-700 transition-all cursor-pointer space-y-3.5 relative overflow-hidden group ${flashClass}`}
              >
                {/* Top Badge & Score */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold font-data text-zinc-100 group-hover:text-cyan-400 transition-colors">
                      {sig.symbol}
                    </span>
                    <span
                      className={`text-[9px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wider ${
                        isHighConviction
                          ? "bg-red-500/10 text-red-400 border border-red-500/30"
                          : "bg-cyan-500/10 text-cyan-400 border border-cyan-500/30"
                      }`}
                    >
                      {String(sig.signal_type || sig.signal || "AL").replace(/_/g, " ")}
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-zinc-500">Skor</span>
                    <span
                      className={`text-xs font-semibold font-data px-1.5 py-0.5 rounded ${
                        (sig.score ?? 50) >= 90
                          ? "bg-emerald-500/15 text-emerald-400"
                          : "bg-cyan-500/15 text-cyan-400"
                      }`}
                    >
                      {sig.score ?? 80}
                    </span>
                  </div>
                </div>

                {/* Reason Catalyst */}
                <p className="text-[11px] text-zinc-400 line-clamp-2 leading-relaxed bg-zinc-950/40 p-2 rounded-lg border border-zinc-800/40 font-normal">
                  {sig.spec_reason || "Phase 18 Otonom Makine Öğrenmesi Yüksek Güvenilirlikli Sinyali"}
                </p>

                {/* Price & Targets Grid (Sol: Stop Loss, Orta: Giriş, Sağ: Hedef) */}
                <div className="grid grid-cols-3 gap-2 text-center pt-1.5 border-t border-zinc-800/60">
                  {/* Stop Loss (Sol) */}
                  <div className="py-1.5 px-2 rounded-lg bg-red-950/20 border border-red-500/20 flex flex-col justify-center">
                    <div className="flex items-center justify-center gap-1 mb-0.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                      <span className="text-[9px] text-red-400/90 uppercase font-medium tracking-wide">Stop Loss</span>
                    </div>
                    <span className="text-xs font-semibold font-data text-red-400">
                      ₺{stopLoss.toFixed(2)}
                    </span>
                    <span className="text-[8.5px] text-red-400/70 font-normal mt-0.5">
                      -%{currentPrice > 0 ? Math.abs((currentPrice - stopLoss) / currentPrice * 100).toFixed(1) : "5.0"}
                    </span>
                  </div>

                  {/* Giriş / Canlı Fiyat (Orta) */}
                  <div className="py-1.5 px-2 rounded-lg bg-zinc-900/60 border border-zinc-800 flex flex-col justify-center">
                    <div className="flex items-center justify-center gap-1 mb-0.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-400/80 animate-pulse" />
                      <span className="text-[9px] text-zinc-400 uppercase font-medium tracking-wide">Giriş</span>
                    </div>
                    <span className="text-xs font-semibold font-data text-zinc-200">
                      ₺{currentPrice.toFixed(2)}
                    </span>
                    <span className="text-[8.5px] text-zinc-500 font-normal mt-0.5">
                      Canlı Fiyat
                    </span>
                  </div>

                  {/* Hedef Fiyat (Sağ) */}
                  <div className="py-1.5 px-2 rounded-lg bg-emerald-950/20 border border-emerald-500/20 flex flex-col justify-center">
                    <div className="flex items-center justify-center gap-1 mb-0.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                      <span className="text-[9px] text-emerald-400/90 uppercase font-medium tracking-wide">Hedef</span>
                    </div>
                    <span className="text-xs font-semibold font-data text-emerald-400">
                      ₺{targetPrice.toFixed(2)}
                    </span>
                    <span className="text-[8.5px] text-emerald-400/80 font-normal mt-0.5">
                      +%{sig.expected_return_pct ? Number(sig.expected_return_pct).toFixed(1) : "12.0"}
                    </span>
                  </div>
                </div>

                {/* Risk/Reward Mini Visual Bar */}
                <div className="space-y-1.5 px-0.5">
                  <div className="h-2 w-full rounded-full bg-zinc-950 overflow-hidden relative border border-zinc-800/80">
                    <div
                      className="h-full bg-gradient-to-r from-red-500 via-amber-400 to-emerald-500 rounded-full"
                      style={{ width: "100%" }}
                    />
                    <div
                      className="absolute top-0 bottom-0 w-2 bg-white shadow-md -ml-1 rounded-full border border-zinc-900"
                      style={{ left: `${currentOffset}%` }}
                      title="Mevcut Fiyat Seviyesi"
                    />
                  </div>
                </div>

                {/* Metrics Footer */}
                <div className="flex items-center justify-between text-[10px] text-zinc-400 pt-1">
                  <div className="flex items-center gap-3">
                    <span>R/R: <strong className="text-zinc-200 font-data">{sig.risk_reward_ratio ?? 2.0}x</strong></span>
                    <span>Hacim: <strong className="text-amber-400 font-data">{sig.volume_ratio ?? 1.8}x</strong></span>
                    <span>RSI: <strong className="text-zinc-200 font-data">{sig.rsi ?? 54.0}</strong></span>
                  </div>
                  <div className="flex items-center gap-1 text-cyan-400 group-hover:translate-x-0.5 transition-transform">
                    <span>Grafik</span>
                    <ExternalLink size={10} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* Tablo Görünümü */
        <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-950/60 text-zinc-400 border-b border-zinc-800">
                <tr>
                  <th className="p-3 font-semibold">Sembol</th>
                  <th className="p-3 font-semibold">Sinyal / Strateji</th>
                  <th className="p-3 font-semibold text-right">Fiyat</th>
                  <th className="p-3 font-semibold text-right">Değişim</th>
                  <th className="p-3 font-semibold text-right">ML Skoru</th>
                  <th className="p-3 font-semibold text-right">Hedef Fiyat</th>
                  <th className="p-3 font-semibold text-right">Beklenen Alpha</th>
                  <th className="p-3 font-semibold text-right">Stop Loss</th>
                  <th className="p-3 font-semibold text-right">R/R</th>
                  <th className="p-3 font-semibold text-right">RSI</th>
                  <th className="p-3 font-semibold text-right">Hacim</th>
                  <th className="p-3 font-semibold text-center">Detay</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/50">
                {filteredSignals.map((sig) => {
                  const sym = sig.symbol || sig.ticker;
                  const isHigh = Boolean((sig as any).is_high_conviction) || (sig.score ?? 0) >= 80;
                  const price = Number(sig.price ?? 0);
                  const chg = Number(sig.change_pct ?? 0);
                  const target = Number(sig.target_price ?? (price * 1.12));
                  const stop = Number(sig.stop_loss ?? (price * 0.94));
                  return (
                    <tr
                      key={sym}
                      onClick={() => router.push(`/asset?symbol=${sym}`)}
                      className="hover:bg-zinc-800/40 transition-colors cursor-pointer"
                    >
                      <td className="p-3 font-bold font-data text-zinc-100 flex items-center gap-1.5">
                        <span>{sym}</span>
                        {isHigh && <Flame size={12} className="text-red-400 inline" />}
                      </td>
                      <td className="p-3">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                          isHigh ? "bg-red-500/10 text-red-400 border border-red-500/20" : "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20"
                        }`}>
                          {String(sig.signal_type || sig.signal || "AL").replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="p-3 text-right font-data text-zinc-200">₺{price.toFixed(2)}</td>
                      <td className={`p-3 text-right font-data font-semibold ${chg >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {chg >= 0 ? `+${chg.toFixed(2)}%` : `${chg.toFixed(2)}%`}
                      </td>
                      <td className="p-3 text-right font-data font-bold text-cyan-400">{sig.score ?? 80}</td>
                      <td className="p-3 text-right font-data text-emerald-400">₺{target.toFixed(2)}</td>
                      <td className="p-3 text-right font-data font-bold text-emerald-400">+{sig.expected_return_pct ?? 12}%</td>
                      <td className="p-3 text-right font-data text-red-400">₺{stop.toFixed(2)}</td>
                      <td className="p-3 text-right font-data text-zinc-300">{sig.risk_reward_ratio ?? 2.0}x</td>
                      <td className="p-3 text-right font-data text-zinc-400">{sig.rsi ?? 50}</td>
                      <td className="p-3 text-right font-data text-amber-400">{sig.volume_ratio ?? 1.5}x</td>
                      <td className="p-3 text-center text-cyan-400 hover:text-cyan-300">
                        <ExternalLink size={12} className="inline" />
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
