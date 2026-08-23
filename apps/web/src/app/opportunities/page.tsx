"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling, useDebounce } from "@/lib/api";
import {
  Target, ArrowUpRight, ArrowDownRight, Flame, Eye, Star, Layers,
  TrendingUp, ShieldAlert, BarChart3, Zap, Filter, Search, RefreshCw, ExternalLink
} from "lucide-react";

interface OpportunitySignal {
  ticker: string;
  symbol: string;
  name: string;
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
  const { data: rawSignals, loading, refetch } = usePolling<OpportunitySignal[]>(
    "/scanner/signals?limit=50",
    15000
  );

  const [activeFilter, setActiveFilter] = useState<string>("ALL");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const debouncedSearch = useDebounce(searchTerm, 150);

  const signals = useMemo(() => {
    if (!rawSignals) return [];
    const list = Array.isArray(rawSignals) ? rawSignals : ((rawSignals as any).signals || []);
    return list;
  }, [rawSignals]);

  const filteredSignals = useMemo(() => {
    return signals.filter((s) => {
      // Kategori filtresi
      if (activeFilter === "HIGH_CONVICTION" && s.spec_category !== "HIGH_CONVICTION") return false;
      if (activeFilter === "VOLUME_BREAKOUT" && s.signal_type !== "VOLUME_BREAKOUT") return false;
      if (activeFilter === "PULLBACK_BOUNCE" && s.signal_type !== "PULLBACK_BOUNCE") return false;
      if (activeFilter === "MOMENTUM_LEADER" && s.signal_type !== "MOMENTUM_LEADER") return false;

      // Arama filtresi with debounce
      if (debouncedSearch) {
        const q = debouncedSearch.toLowerCase();
        const sym = (s.symbol || s.ticker || "").toLowerCase();
        const rsn = (s.spec_reason || "").toLowerCase();
        return sym.includes(q) || rsn.includes(q);
      }
      return true;
    });
  }, [signals, activeFilter, debouncedSearch]);

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold gradient-text">Piyasa Fırsatları & Algoritmik Sinyaller</h1>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              CANLI TARAMA
            </span>
          </div>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            20G Hacim Kırılımları · Trend İçi Dip Alımları · Yüksek R/R Asimetrik İşlem Kurulumları
          </p>
        </div>

        <div className="flex items-center gap-2">
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
            onClick={() => refresh()}
            className="p-2 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
            title="Yenile"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 custom-scrollbar">
        {CAT_FILTERS.map((f) => {
          const Icon = f.icon;
          const isActive = activeFilter === f.id;
          return (
            <button
              key={f.id}
              onClick={() => setActiveFilter(f.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                isActive
                  ? "bg-zinc-100 text-zinc-900 shadow-md"
                  : "bg-zinc-900/80 text-zinc-400 hover:text-zinc-200 border border-zinc-800"
              }`}
            >
              <Icon size={12} style={{ color: isActive ? "#000" : f.color }} />
              <span>{f.label}</span>
            </button>
          );
        })}
      </div>

      {/* Signal Cards Grid */}
      {filteredSignals.length === 0 ? (
        <div className="text-center py-16 text-zinc-500 text-xs rounded-xl bg-zinc-900/30 border border-zinc-800/50">
          {loading ? "Piyasa fırsatları taranıyor..." : "Bu kriterde aktif sinyal bulunamadı."}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredSignals.map((sig) => {
            const isHighConviction = sig.spec_category === "HIGH_CONVICTION";
            return (
              <div
                key={sig.symbol}
                onClick={() => router.push(`/asset?symbol=${sig.symbol}`)}
                className="rounded-xl p-4.5 bg-zinc-900/50 hover:bg-zinc-900/80 border border-zinc-800/80 hover:border-zinc-700 transition-all cursor-pointer space-y-3.5 relative overflow-hidden group"
              >
                {/* Top Badge & Score */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-base font-bold font-data text-zinc-100 group-hover:text-cyan-400 transition-colors">
                      {sig.symbol}
                    </span>
                    <span
                      className={`text-[9px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider ${
                        isHighConviction
                          ? "bg-red-500/10 text-red-400 border border-red-500/30"
                          : "bg-cyan-500/10 text-cyan-400 border border-cyan-500/30"
                      }`}
                    >
                      {sig.signal_type.replace("_", " ")}
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-zinc-500">Skor</span>
                    <span
                      className={`text-xs font-bold font-data px-1.5 py-0.5 rounded ${
                        sig.score >= 90
                          ? "bg-emerald-500/15 text-emerald-400"
                          : "bg-cyan-500/15 text-cyan-400"
                      }`}
                    >
                      {sig.score}
                    </span>
                  </div>
                </div>

                {/* Reason Catalyst */}
                <p className="text-xs text-zinc-300 line-clamp-2 leading-relaxed bg-zinc-950/40 p-2 rounded-lg border border-zinc-800/40">
                  {sig.spec_reason}
                </p>

                {/* Price & Targets Grid */}
                <div className="grid grid-cols-3 gap-2 text-center pt-1 border-t border-zinc-800/50">
                  <div className="p-2 rounded-lg bg-zinc-950/30">
                    <span className="text-[9px] text-zinc-500 uppercase block font-semibold">Giriş / Fiyat</span>
                    <span className="text-xs font-bold font-data text-zinc-200">₺{sig.price.toFixed(2)}</span>
                  </div>

                  <div className="p-2 rounded-lg bg-emerald-950/20 border border-emerald-500/20">
                    <span className="text-[9px] text-emerald-400 uppercase block font-semibold">Hedef (+%{sig.expected_return_pct})</span>
                    <span className="text-xs font-bold font-data text-emerald-400">₺{sig.target_price.toFixed(2)}</span>
                  </div>

                  <div className="p-2 rounded-lg bg-red-950/20 border border-red-500/20">
                    <span className="text-[9px] text-red-400 uppercase block font-semibold">Stop Loss</span>
                    <span className="text-xs font-bold font-data text-red-400">₺{sig.stop_loss.toFixed(2)}</span>
                  </div>
                </div>

                {/* Metrics Footer */}
                <div className="flex items-center justify-between text-[10px] text-zinc-400 pt-1">
                  <div className="flex items-center gap-3">
                    <span>R/R: <strong className="text-zinc-200 font-data">{sig.risk_reward_ratio}x</strong></span>
                    <span>Hacim: <strong className="text-amber-400 font-data">{sig.volume_ratio}x</strong></span>
                    <span>RSI: <strong className="text-zinc-200 font-data">{sig.rsi}</strong></span>
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
      )}
    </div>
  );
}
