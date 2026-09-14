"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling, type PortfolioData, apiFetch } from "@/lib/api";
import type { OrderData, PortfolioMetrics } from "@/types/api";
import { 
  Briefcase, TrendingUp, TrendingDown, Wallet, ArrowUpRight, ArrowDownRight, 
  RefreshCw, PieChart, CheckCircle2, AlertCircle, Zap, Coins, Receipt,
  Search, LayoutGrid, ListFilter, ArrowRight, ShieldCheck, Sparkles, Filter
} from "lucide-react";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { useIstanbulClock } from "@/lib/time";

// Sektör renk paleti (Ultra lüks HSL tonları)
const SECTOR_COLORS: Record<string, string> = {
  "BANKACILIK": "#00e5a0",
  "HAVACILIK": "#00c8ff",
  "ENERJI": "#9966ff",
  "SANAYI": "#ffaa00",
  "HOLDING": "#38bdf8",
  "PERAKENDE": "#f472b6",
  "DEMIR_CELIK": "#fb923c",
  "TELEKOM": "#a78bfa",
  "GIDA": "#4ade80",
  "OTOMOTIV": "#e879f9",
  "NAKIT": "#71717a",
  "DIGER": "#a1a1aa",
};

export default function PortfolioPage() {
  const router = useRouter();
  const clock = useIstanbulClock();
  
  // Dengeli polling (SSD ve ağ koruması)
  const { data, loading, refetch } = usePolling<PortfolioData | null>("/portfolio", 4000);
  const { data: ordersData, refetch: refetchOrders } = usePolling<{ orders: OrderData[] } | null>("/portfolio/orders", 8000);
  const { data: metricsData } = usePolling<PortfolioMetrics | null>("/portfolio/metrics", 10000);
  
  const [mounted, setMounted] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [actionMsg, setActionMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [flashMap, setFlashMap] = useState<Record<string, "up" | "down">>({});
  
  // Görünüm ve Filtre State'leri
  const [viewMode, setViewMode] = useState<"table" | "grid">("table");
  const [mainTab, setMainTab] = useState<"positions" | "orders" | "t2">("positions");
  const [searchTerm, setSearchTerm] = useState("");
  const [pnlFilter, setPnlFilter] = useState<"ALL" | "PROFIT" | "LOSS">("ALL");
  const [orderFilter, setOrderFilter] = useState<"ALL" | "BUY" | "SELL">("ALL");

  // Kolon Sıralama State'leri
  type PositionSortField = "ticker" | "quantity" | "current_price" | "market_value" | "unrealized_pnl" | "unrealized_pnl_pct";
  type OrderSortField = "date" | "ticker" | "quantity" | "execution_price" | "realized_pnl";

  const [sortField, setSortField] = useState<PositionSortField>("market_value");
  const [sortAsc, setSortAsc] = useState<boolean>(false);

  const [orderSortField, setOrderSortField] = useState<OrderSortField>("date");
  const [orderSortAsc, setOrderSortAsc] = useState<boolean>(false);

  const handleSort = (field: PositionSortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(field === "ticker"); // Default: Ticker için A-Z (true), nümerik değerler için azalan (false)
    }
  };

  const handleOrderSort = (field: OrderSortField) => {
    if (orderSortField === field) {
      setOrderSortAsc(!orderSortAsc);
    } else {
      setOrderSortField(field);
      setOrderSortAsc(field === "ticker" || field === "date");
    }
  };

  const prevPricesRef = useRef<Record<string, number>>({});

  useEffect(() => {
    setMounted(true);
  }, []);

  const marketOpen = mounted ? clock.isMarketOpen : false;

  const rawP = (data?.portfolio ?? ((data as unknown) as Record<string, any>) ?? {}) as Record<string, any>;
  const currentCapital = Number(rawP.total_value ?? rawP.current_capital ?? 1000000);
  const investedValue = Number(rawP.invested_value ?? (currentCapital - (rawP.cash ?? rawP.total_cash ?? 0)));
  const cashBalance = Number(rawP.cash ?? rawP.total_cash ?? rawP.settled_cash ?? 0);
  const settledCash = Number(rawP.settled_cash ?? cashBalance);
  const unsettledT1 = Number(rawP.unsettled_cash_t1 ?? 0);
  const unsettledT2 = Number(rawP.unsettled_cash_t2 ?? 0);
  const purchasingPower = Number(rawP.purchasing_power ?? cashBalance);
  const totalPnl = Number(rawP.total_pnl ?? rawP.unrealized_pnl ?? 0);
  const totalReturnPct = Number(rawP.total_return_pct ?? (currentCapital > 1000000 ? ((currentCapital - 1000000) / 1000000) * 100 : 0));
  const positions = data?.positions ?? (rawP.positions as PortfolioData["positions"]) ?? [];
  const orders = ordersData?.orders ?? [];
  const sectorWeights = (rawP.sector_weights ?? {}) as Record<string, number>;
  const totalPnlPos = totalPnl >= 0;

  // Fiyat değişim animasyonu
  useEffect(() => {
    if (!positions || positions.length === 0) return;
    const nextFlash: Record<string, "up" | "down"> = {};
    for (const pos of positions) {
      const sym = pos.ticker || pos.symbol || "";
      if (!sym) continue;
      const price = Number(pos.current_price ?? pos.avg_cost ?? 0);
      const prev = prevPricesRef.current[sym];
      if (prev !== undefined && price > 0) {
        if (price > prev) nextFlash[sym] = "up";
        else if (price < prev) nextFlash[sym] = "down";
      }
      prevPricesRef.current[sym] = price;
    }
    if (Object.keys(nextFlash).length > 0) {
      setFlashMap(nextFlash);
      const timer = setTimeout(() => setFlashMap({}), 1300);
      return () => clearTimeout(timer);
    }
  }, [data]);

  // Filtrelenmiş ve Sıralanmış Pozisyonlar
  const filteredPositions = useMemo(() => {
    const matched = positions.filter((pos) => {
      const sym = (pos.ticker || pos.symbol || "").toUpperCase();
      const name = (pos.name || pos.company_name || "").toLowerCase();
      const sec = (pos.sector || "").toLowerCase();
      const q = searchTerm.trim().toLowerCase();
      
      const matchesSearch = !q || sym.includes(q.toUpperCase()) || name.includes(q) || sec.includes(q);
      if (!matchesSearch) return false;

      const pnlVal = Number(pos.unrealized_pnl ?? 0);
      if (pnlFilter === "PROFIT") return pnlVal > 0;
      if (pnlFilter === "LOSS") return pnlVal < 0;
      return true;
    });

    return [...matched].sort((a, b) => {
      if (sortField === "ticker") {
        const valA = (a.ticker || a.symbol || "").toUpperCase();
        const valB = (b.ticker || b.symbol || "").toUpperCase();
        return sortAsc ? valA.localeCompare(valB, "tr") : valB.localeCompare(valA, "tr");
      }
      if (sortField === "quantity") {
        const valA = Number(a.quantity ?? 0);
        const valB = Number(b.quantity ?? 0);
        return sortAsc ? valA - valB : valB - valA;
      }
      if (sortField === "current_price") {
        const valA = Number(a.current_price ?? a.avg_cost ?? 0);
        const valB = Number(b.current_price ?? b.avg_cost ?? 0);
        return sortAsc ? valA - valB : valB - valA;
      }
      if (sortField === "market_value") {
        const valA = Number(a.market_value ?? 0);
        const valB = Number(b.market_value ?? 0);
        return sortAsc ? valA - valB : valB - valA;
      }
      if (sortField === "unrealized_pnl") {
        const valA = Number(a.unrealized_pnl ?? 0);
        const valB = Number(b.unrealized_pnl ?? 0);
        return sortAsc ? valA - valB : valB - valA;
      }
      if (sortField === "unrealized_pnl_pct") {
        const valA = Number(a.unrealized_pnl_pct ?? 0);
        const valB = Number(b.unrealized_pnl_pct ?? 0);
        return sortAsc ? valA - valB : valB - valA;
      }
      return 0;
    });
  }, [positions, searchTerm, pnlFilter, sortField, sortAsc]);

  // Filtrelenmiş ve Sıralanmış Emirler
  const filteredOrders = useMemo(() => {
    const matched = orders.filter((ord) => {
      if (orderFilter === "BUY") return ord.side === "BUY";
      if (orderFilter === "SELL") return ord.side === "SELL";
      return true;
    });

    return [...matched].sort((a, b) => {
      if (orderSortField === "ticker") {
        const valA = (ordA_ticker(a)).toUpperCase();
        const valB = (ordA_ticker(b)).toUpperCase();
        return orderSortAsc ? valA.localeCompare(valB, "tr") : valB.localeCompare(valA, "tr");
      }
      if (orderSortField === "date") {
        const valA = a.date || "";
        const valB = b.date || "";
        return orderSortAsc ? valA.localeCompare(valB, "tr") : valB.localeCompare(valA, "tr");
      }
      if (orderSortField === "quantity") {
        const valA = Number(a.quantity ?? 0);
        const valB = Number(b.quantity ?? 0);
        return orderSortAsc ? valA - valB : valB - valA;
      }
      if (orderSortField === "execution_price") {
        const valA = Number(a.execution_price ?? a.exit_price ?? a.signal_price ?? 0);
        const valB = Number(b.execution_price ?? b.exit_price ?? b.signal_price ?? 0);
        return orderSortAsc ? valA - valB : valB - valA;
      }
      if (orderSortField === "realized_pnl") {
        const valA = Number(a.realized_pnl ?? 0);
        const valB = Number(b.realized_pnl ?? 0);
        return orderSortAsc ? valA - valB : valB - valA;
      }
      return 0;
    });
  }, [orders, orderFilter, orderSortField, orderSortAsc]);

  function ordA_ticker(ord: OrderData): string {
    return ord.ticker || (ord as any).symbol || "";
  }

  // Varlık Dağılımı Hesaplama (Segment Bar)
  const allocationSegments = useMemo(() => {
    const segments: Array<{ label: string; pct: number; color: string }> = [];
    const cashPct = currentCapital > 0 ? (cashBalance / currentCapital) * 100 : 0;
    
    // Sektörleri ekle
    Object.entries(sectorWeights).forEach(([sec, w], idx) => {
      const pct = Number(w) * 100;
      if (pct > 0.5) {
        const colorKey = sec.toUpperCase().replace(/\s+/g, "_");
        const color = SECTOR_COLORS[colorKey] || Object.values(SECTOR_COLORS)[idx % Object.values(SECTOR_COLORS).length];
        segments.push({ label: sec, pct, color });
      }
    });

    // Nakit segmenti
    if (cashPct > 0.5) {
      segments.push({ label: "Nakit", pct: cashPct, color: SECTOR_COLORS["NAKIT"] });
    }

    return segments.sort((a, b) => b.pct - a.pct);
  }, [sectorWeights, cashBalance, currentCapital]);

  const handleRunRebalanceCycle = async () => {
    setTriggering(true);
    setActionMsg(null);
    try {
      await apiFetch("/portfolio/trigger", { method: "POST" });
      setActionMsg({ 
        type: "success", 
        text: "Seans sinyal ve portföy emir yürütme döngüsü tetiklendi. Veriler güncelleniyor..." 
      });
      setTimeout(() => {
        refetch();
        refetchOrders();
      }, 2500);
    } catch {
      try {
        await apiFetch("/scanner/trigger?scan_type=manual", { method: "POST" });
        setActionMsg({ 
          type: "success", 
          text: "Tarama ve sinyal döngüsü tetiklendi. Veriler güncelleniyor..." 
        });
      } catch (err: unknown) {
        setActionMsg({ type: "error", text: `İşlem tetiklenirken hata oluştu: ${err instanceof Error ? err.message : String(err)}` });
      }
    } finally {
      setTriggering(false);
    }
  };

  return (
    <ErrorBoundary name="portfolio">
      {/* Ambient Glow Background Effect */}
      <div className="relative min-h-screen pb-16 overflow-hidden" style={{ background: "var(--color-bg-primary)" }}>
        <div 
          className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[1000px] h-[450px] opacity-25 blur-[120px] rounded-full"
          style={{ background: totalPnlPos ? "radial-gradient(ellipse, #00e5a0 0%, #00c8ff 40%, transparent 70%)" : "radial-gradient(ellipse, #ff4466 0%, #ffaa00 40%, transparent 70%)" }}
        />

        <div className="relative max-w-7xl mx-auto p-3 md:p-4 lg:p-5 space-y-3">

          {/* 1. COMPACT LUXURY HERO HEADER */}
          <div className="relative rounded-xl p-4 md:p-5 border border-white/[0.08] backdrop-blur-2xl shadow-xl overflow-hidden"
               style={{ background: "linear-gradient(135deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%)" }}>
            
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
              {/* Sol: Bakiye & Kâr/Zarar */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold tracking-wider text-zinc-400 uppercase">
                    Net Portföy Değeri (NAV)
                  </span>
                  <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-white/[0.04] border border-white/[0.08]">
                    <span className={`w-1.5 h-1.5 rounded-full ${marketOpen ? "bg-emerald-400 shadow-[0_0_6px_#00e5a0]" : "bg-amber-400"}`} />
                    <span className="text-[9px] font-semibold text-zinc-300">
                      {marketOpen ? "BIST AÇIK" : "BIST KAPALI"}
                    </span>
                  </div>
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-purple-500/10 text-purple-300 border border-purple-500/20 font-medium">
                    Hedge Fund Modu
                  </span>
                </div>

                <div className="flex flex-wrap items-baseline gap-3">
                  <span className="text-2xl md:text-3xl font-extrabold font-data tracking-tight text-white drop-shadow-sm">
                    ₺{currentCapital.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>

                  <div className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-lg text-xs font-bold font-data border ${
                    totalPnlPos 
                      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 shadow-[0_0_12px_rgba(0,229,160,0.12)]" 
                      : "bg-rose-500/10 text-rose-400 border-rose-500/20 shadow-[0_0_12px_rgba(255,68,102,0.12)]"
                  }`}>
                    {totalPnlPos ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
                    <span>{totalPnlPos ? "+" : ""}₺{totalPnl.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                    <span className="opacity-80">({totalPnlPos ? "+" : ""}%{totalReturnPct.toFixed(2)})</span>
                  </div>

                  <span className="text-[11px] text-zinc-500">
                    Başlangıç: ₺1M
                  </span>
                </div>
              </div>

              {/* Sağ: İki Kompakt Metrik Kartı & Seansı Çalıştır */}
              <div className="flex flex-wrap items-center gap-2.5">
                {/* Alım Gücü Mini Kartı */}
                <div className="px-3 py-2 rounded-lg border border-white/[0.06] bg-white/[0.02] backdrop-blur-md min-w-[130px]">
                  <div className="flex items-center justify-between text-[10px] text-zinc-400 font-medium">
                    <span>Alım Gücü (T+2)</span>
                    <Coins size={12} className="text-amber-400" />
                  </div>
                  <div className="text-sm md:text-base font-bold font-data text-white">
                    ₺{purchasingPower.toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
                  </div>
                </div>

                {/* Hisse Portföyü Mini Kartı */}
                <div className="px-3 py-2 rounded-lg border border-white/[0.06] bg-white/[0.02] backdrop-blur-md min-w-[130px]">
                  <div className="flex items-center justify-between text-[10px] text-zinc-400 font-medium">
                    <span>Hisse Yatırımı</span>
                    <Briefcase size={12} className="text-cyan-400" />
                  </div>
                  <div className="text-sm md:text-base font-bold font-data text-white">
                    ₺{investedValue.toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
                  </div>
                </div>

                {/* Seansı Çalıştır Butonu */}
                <button
                  onClick={handleRunRebalanceCycle}
                  disabled={triggering}
                  className="flex items-center gap-2 px-3.5 py-2.5 rounded-lg font-bold text-xs bg-gradient-to-r from-emerald-400 to-teal-500 hover:from-emerald-300 hover:to-teal-400 text-zinc-950 shadow-md shadow-emerald-500/20 active:scale-95 transition-all cursor-pointer disabled:opacity-50"
                  title="Yapay zeka portföy dengeleme seansını manuel tetikle"
                >
                  <Zap size={14} className={triggering ? "animate-spin" : ""} />
                  <span>{triggering ? "Yürütülüyor..." : "Seansı Çalıştır"}</span>
                </button>
              </div>
            </div>

            {/* 2. REVOLUT / APPLE WALLET STYLE ALLOCATION STRIP (KOMPAKT) */}
            {allocationSegments.length > 0 && (
              <div className="mt-3.5 pt-3 border-t border-white/[0.06] space-y-2">
                {/* Segment Çubuğu */}
                <div className="h-1.5 w-full rounded-full overflow-hidden flex bg-zinc-900 border border-white/[0.05] p-0.5 gap-0.5">
                  {allocationSegments.map((seg, i) => (
                    <div
                      key={i}
                      style={{ width: `${seg.pct}%`, backgroundColor: seg.color }}
                      className="h-full rounded-full transition-all duration-500 hover:opacity-80"
                      title={`${seg.label}: %${seg.pct.toFixed(1)}`}
                    />
                  ))}
                </div>

                {/* Sektör Etiketleri (Kompakt Tek Satır/Wrap) */}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]">
                  <span className="text-zinc-500 font-medium">Dağılım:</span>
                  {allocationSegments.map((seg, i) => (
                    <div key={i} className="flex items-center gap-1 text-zinc-400">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: seg.color }} />
                      <span className="font-medium text-zinc-300">{seg.label}</span>
                      <span className="font-data font-semibold text-zinc-400">%{seg.pct.toFixed(1)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {actionMsg && (
            <div className={`p-2.5 px-3 rounded-lg border text-xs font-medium flex items-center justify-between transition-all ${
              actionMsg.type === "success" 
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                : "bg-rose-500/10 border-rose-500/30 text-rose-300"
            }`}>
              <div className="flex items-center gap-2">
                {actionMsg.type === "success" ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                <span>{actionMsg.text}</span>
              </div>
              <button onClick={() => setActionMsg(null)} className="text-zinc-400 hover:text-white text-[11px] cursor-pointer">
                ✕
              </button>
            </div>
          )}

          {/* 3. ANA GEZİNTİ ÇUBUĞU (SEKMELER + ARAMA + GÖRÜNÜM SEÇİCİ) */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 bg-zinc-900/60 p-1.5 rounded-xl border border-white/[0.06] backdrop-blur-md">
            {/* Sol: Ana Sekmeler */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => setMainTab("positions")}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  mainTab === "positions"
                    ? "bg-emerald-500 text-zinc-950 font-bold shadow-sm"
                    : "text-zinc-400 hover:text-white hover:bg-white/[0.04]"
                }`}
              >
                <Briefcase size={14} />
                <span>Açık Pozisyonlar</span>
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${mainTab === "positions" ? "bg-zinc-950/20 text-zinc-950" : "bg-zinc-800 text-zinc-300"}`}>
                  {positions.length}
                </span>
              </button>

              <button
                onClick={() => setMainTab("orders")}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  mainTab === "orders"
                    ? "bg-emerald-500 text-zinc-950 font-bold shadow-sm"
                    : "text-zinc-400 hover:text-white hover:bg-white/[0.04]"
                }`}
              >
                <Receipt size={14} />
                <span>Emir & İşlem Defteri</span>
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${mainTab === "orders" ? "bg-zinc-950/20 text-zinc-950" : "bg-zinc-800 text-zinc-300"}`}>
                  {orders.length}
                </span>
              </button>

              <button
                onClick={() => setMainTab("t2")}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  mainTab === "t2"
                    ? "bg-emerald-500 text-zinc-950 font-bold shadow-sm"
                    : "text-zinc-400 hover:text-white hover:bg-white/[0.04]"
                }`}
              >
                <Coins size={14} />
                <span>T+2 Takasbank</span>
              </button>
            </div>

            {/* Sağ: Arama ve Görünüm Kontrolleri (Pozisyon Sekmesinde Aktif) */}
            {mainTab === "positions" && (
              <div className="flex items-center gap-2">
                {/* Hızlı Arama */}
                <div className="relative">
                  <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                  <input
                    type="text"
                    placeholder="Hisse ara (örn: THYAO)..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-44 md:w-56 pl-8 pr-3 py-1.5 rounded-lg text-xs bg-zinc-950/80 border border-white/[0.08] text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-emerald-500/50"
                  />
                </div>

                {/* K/Z Filtresi */}
                <div className="flex bg-zinc-950/80 p-0.5 rounded-lg border border-white/[0.08] text-[11px]">
                  <button
                    onClick={() => setPnlFilter("ALL")}
                    className={`px-2 py-1 rounded font-medium transition-all cursor-pointer ${pnlFilter === "ALL" ? "bg-zinc-800 text-white font-semibold" : "text-zinc-400 hover:text-zinc-200"}`}
                  >
                    Tümü
                  </button>
                  <button
                    onClick={() => setPnlFilter("PROFIT")}
                    className={`px-2 py-1 rounded font-medium transition-all cursor-pointer ${pnlFilter === "PROFIT" ? "bg-emerald-500/20 text-emerald-300 font-semibold" : "text-zinc-400 hover:text-zinc-200"}`}
                  >
                    Kârdakiler
                  </button>
                  <button
                    onClick={() => setPnlFilter("LOSS")}
                    className={`px-2 py-1 rounded font-medium transition-all cursor-pointer ${pnlFilter === "LOSS" ? "bg-rose-500/20 text-rose-300 font-semibold" : "text-zinc-400 hover:text-zinc-200"}`}
                  >
                    Zarardakiler
                  </button>
                </div>

                {/* Hızlı Sıralama Seçici */}
                <div className="hidden sm:flex items-center gap-1.5 bg-zinc-950/80 px-2.5 py-1 rounded-lg border border-white/[0.08] text-[11px]">
                  <span className="text-zinc-500">Sırala:</span>
                  <select
                    value={sortField}
                    onChange={(e) => {
                      setSortField(e.target.value as any);
                      setSortAsc(false);
                    }}
                    className="bg-transparent text-emerald-400 font-medium focus:outline-none cursor-pointer text-[11px]"
                  >
                    <option value="market_value" className="bg-zinc-900 text-white">En Büyük Hisse (Değer)</option>
                    <option value="unrealized_pnl_pct" className="bg-zinc-900 text-white">En Çok Artan (K/Z %)</option>
                    <option value="unrealized_pnl" className="bg-zinc-900 text-white">En Çok Kazandıran (TL)</option>
                    <option value="quantity" className="bg-zinc-900 text-white">Adet (Lot)</option>
                    <option value="current_price" className="bg-zinc-900 text-white">Anlık Fiyat</option>
                    <option value="ticker" className="bg-zinc-900 text-white">Sembol (A-Z)</option>
                  </select>
                  <button
                    onClick={() => setSortAsc(!sortAsc)}
                    className="px-0.5 text-xs font-mono text-zinc-400 hover:text-white"
                    title={sortAsc ? "Artan Sıralama (Küçükten Büyüğe)" : "Azalan Sıralama (Büyükten Küçüğe)"}
                  >
                    {sortAsc ? "▲" : "▼"}
                  </button>
                </div>

                {/* Tablo / Grid Görünüm Değiştirici */}
                <div className="flex bg-zinc-950/80 p-0.5 rounded-lg border border-white/[0.08]">
                  <button
                    onClick={() => setViewMode("table")}
                    className={`p-1.5 rounded transition-all cursor-pointer ${viewMode === "table" ? "bg-zinc-800 text-emerald-400" : "text-zinc-500 hover:text-zinc-300"}`}
                    title="Tablo Görünümü"
                  >
                    <ListFilter size={14} />
                  </button>
                  <button
                    onClick={() => setViewMode("grid")}
                    className={`p-1.5 rounded transition-all cursor-pointer ${viewMode === "grid" ? "bg-zinc-800 text-emerald-400" : "text-zinc-500 hover:text-zinc-300"}`}
                    title="Kart / Grid Görünümü"
                  >
                    <LayoutGrid size={14} />
                  </button>
                </div>
              </div>
            )}

            {/* Emir Defteri Filtresi */}
            {mainTab === "orders" && (
              <div className="flex items-center gap-1 bg-zinc-950/80 p-0.5 rounded-lg border border-white/[0.08] text-[11px]">
                {(["ALL", "BUY", "SELL"] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setOrderFilter(f)}
                    className={`px-2.5 py-1 rounded font-medium transition-all cursor-pointer ${
                      orderFilter === f ? "bg-zinc-800 text-white font-semibold" : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    {f === "ALL" ? "Tüm Emirler" : f === "BUY" ? "Alışlar" : "Satışlar"}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 4. POZİSYONLAR: PRO TABLO VEYA MODERN KART GÖRÜNÜMÜ */}
          {mainTab === "positions" && (
            <>
              {filteredPositions.length === 0 ? (
                <div className="rounded-2xl p-12 text-center border border-white/[0.06] bg-zinc-900/20 backdrop-blur-md">
                  <Wallet size={36} className="mx-auto mb-3 text-zinc-600" />
                  <p className="text-sm font-semibold text-zinc-300">Aramanıza uygun pozisyon bulunamadı</p>
                  <p className="text-xs text-zinc-500 mt-1">Filtreleri temizleyebilir veya yeni seans çalıştırabilirsiniz.</p>
                </div>
              ) : viewMode === "table" ? (
                /* 4A. PRO TABLO GÖRÜNÜMÜ */
                <div className="rounded-2xl border border-white/[0.08] overflow-hidden bg-zinc-900/30 backdrop-blur-xl shadow-xl">
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b border-white/[0.06] text-[11px] font-bold uppercase tracking-wider bg-white/[0.01] select-none">
                          {/* Varlık / Hisse */}
                          <th 
                            onClick={() => handleSort("ticker")} 
                            className={`py-3.5 px-5 cursor-pointer transition-colors hover:text-white ${sortField === "ticker" ? "text-emerald-400" : "text-zinc-400"}`}
                            title="Sembol adına göre sırala"
                          >
                            <div className="flex items-center gap-1.5">
                              <span>Varlık / Hisse</span>
                              <span className="text-xs font-mono">{sortField === "ticker" ? (sortAsc ? "▲" : "▼") : "↕"}</span>
                            </div>
                          </th>

                          {/* Adet (Lot) */}
                          <th 
                            onClick={() => handleSort("quantity")} 
                            className={`py-3.5 px-4 text-right cursor-pointer transition-colors hover:text-white ${sortField === "quantity" ? "text-emerald-400" : "text-zinc-400"}`}
                            title="Lot büyüklüğüne göre sırala"
                          >
                            <div className="flex items-center justify-end gap-1.5">
                              <span>Adet (Lot)</span>
                              <span className="text-xs font-mono">{sortField === "quantity" ? (sortAsc ? "▲" : "▼") : "↕"}</span>
                            </div>
                          </th>

                          {/* Anlık Fiyat & Maliyet */}
                          <th 
                            onClick={() => handleSort("current_price")} 
                            className={`py-3.5 px-4 text-right cursor-pointer transition-colors hover:text-white ${sortField === "current_price" ? "text-emerald-400" : "text-zinc-400"}`}
                            title="Anlık fiyata göre sırala"
                          >
                            <div className="flex items-center justify-end gap-1.5">
                              <span>Anlık Fiyat & Maliyet</span>
                              <span className="text-xs font-mono">{sortField === "current_price" ? (sortAsc ? "▲" : "▼") : "↕"}</span>
                            </div>
                          </th>

                          {/* Toplam Değer & Pay (En büyük hisse) */}
                          <th 
                            onClick={() => handleSort("market_value")} 
                            className={`py-3.5 px-4 text-right cursor-pointer transition-colors hover:text-white ${sortField === "market_value" ? "text-emerald-400" : "text-zinc-400"}`}
                            title="En büyük hisseye / piyasa değerine göre sırala"
                          >
                            <div className="flex items-center justify-end gap-1.5">
                              <span>Toplam Değer & Pay</span>
                              <span className="text-xs font-mono">{sortField === "market_value" ? (sortAsc ? "▲" : "▼") : "↕"}</span>
                            </div>
                          </th>

                          {/* Kâr / Zarar Durumu (En çok artan) */}
                          <th 
                            onClick={() => handleSort("unrealized_pnl_pct")} 
                            className={`py-3.5 px-5 text-right cursor-pointer transition-colors hover:text-white ${sortField === "unrealized_pnl_pct" ? "text-emerald-400" : "text-zinc-400"}`}
                            title="En çok artan / kâr-zarar yüzdesine göre sırala"
                          >
                            <div className="flex items-center justify-end gap-1.5">
                              <span>Kâr / Zarar Durumu</span>
                              <span className="text-xs font-mono">{sortField === "unrealized_pnl_pct" ? (sortAsc ? "▲" : "▼") : "↕"}</span>
                            </div>
                          </th>

                          {/* İşlem */}
                          <th className="py-3.5 px-4 text-center text-zinc-400">İşlem</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/[0.04] text-xs">
                        {filteredPositions.map((pos, idx) => {
                          const sym = pos.ticker || pos.symbol || "";
                          const pnlVal = Number(pos.unrealized_pnl ?? 0);
                          const pnlPct = Number(pos.unrealized_pnl_pct ?? 0);
                          const dailyChg = Number(pos.daily_change_pct ?? 0);
                          const isPos = pnlVal >= 0;
                          const curPrice = Number(pos.current_price ?? pos.avg_cost ?? 0);
                          const avgCost = Number(pos.avg_cost ?? 0);
                          const weight = Number(pos.weight_pct ?? 0);
                          const flash = sym ? flashMap[sym] : undefined;

                          return (
                            <tr 
                              key={idx}
                              onClick={() => router.push(`/asset?symbol=${sym}`)}
                              className="hover:bg-white/[0.03] transition-all cursor-pointer group"
                            >
                              {/* Varlık / Hisse */}
                              <td className="py-3.5 px-5">
                                <div className="flex items-center gap-3">
                                  <div className="w-9 h-9 rounded-xl flex items-center justify-center font-bold font-data text-xs bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 group-hover:scale-105 group-hover:bg-emerald-500/20 transition-all">
                                    {sym.slice(0, 3)}
                                  </div>
                                  <div>
                                    <div className="flex items-center gap-2">
                                      <span className="font-bold font-data text-white text-sm group-hover:text-emerald-400 transition-colors">
                                        {sym}
                                      </span>
                                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.06]">
                                        {pos.sector || "BIST"}
                                      </span>
                                    </div>
                                    <p className="text-[11px] text-zinc-400 truncate max-w-[170px] mt-0.5">
                                      {pos.name || pos.company_name || sym}
                                    </p>
                                  </div>
                                </div>
                              </td>

                              {/* Adet (Lot) */}
                              <td className="py-3.5 px-4 text-right font-data font-bold text-zinc-200">
                                {Number(pos.quantity ?? 0).toLocaleString("tr-TR")} Lot
                              </td>

                              {/* Anlık Fiyat & Maliyet */}
                              <td className="py-3.5 px-4 text-right">
                                <div className="flex items-center justify-end gap-1.5">
                                  <div className={`font-data font-bold text-sm ${flash === "up" ? "text-emerald-400" : flash === "down" ? "text-rose-400" : "text-white"}`}>
                                    ₺{curPrice.toFixed(2)}
                                  </div>
                                  <span className={`text-[10px] font-bold font-data px-1.5 py-0.2 rounded border ${
                                    dailyChg > 0 
                                      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" 
                                      : dailyChg < 0 
                                      ? "bg-rose-500/10 text-rose-400 border-rose-500/20" 
                                      : "bg-white/[0.04] text-zinc-400 border-white/[0.06]"
                                  }`} title="Bugünkü borsa değişimi">
                                    {dailyChg > 0 ? "+" : ""}%{dailyChg.toFixed(2)} Bugün
                                  </span>
                                </div>
                                <div className="font-data text-[11px] text-zinc-500 mt-0.5">
                                  Maliyet: ₺{avgCost.toFixed(2)}
                                </div>
                              </td>

                              {/* Toplam Değer & Pay */}
                              <td className="py-3.5 px-4 text-right">
                                <div className="font-data font-bold text-zinc-100">
                                  ₺{Number(pos.market_value ?? 0).toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
                                </div>
                                <div className="flex items-center justify-end gap-1 text-[11px] text-zinc-500 font-data">
                                  <span>Pay:</span>
                                  <span className="text-zinc-300 font-semibold">%{weight.toFixed(1)}</span>
                                </div>
                              </td>

                              {/* Kâr / Zarar */}
                              <td className="py-3.5 px-5 text-right">
                                <div className="flex flex-col items-end gap-0.5">
                                  <span className={`font-extrabold font-data text-sm ${isPos ? "text-emerald-400" : "text-rose-400"}`}>
                                    {isPos ? "+" : ""}₺{pnlVal.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                  </span>
                                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded border ${
                                    isPos 
                                      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" 
                                      : "bg-rose-500/10 text-rose-400 border-rose-500/20"
                                  }`} title="Alış maliyetine göre toplam kâr/zarar">
                                    {isPos ? "+" : ""}%{pnlPct.toFixed(2)} Maliyetten
                                  </span>
                                </div>
                              </td>

                              {/* İşlem */}
                              <td className="py-3.5 px-4 text-center">
                                <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-white/[0.04] text-zinc-400 group-hover:bg-emerald-500 group-hover:text-zinc-950 transition-all">
                                  <ArrowRight size={13} />
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                /* 4B. REVOLUT / APPLE WALLET STYLE GRID CARDS */
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {filteredPositions.map((pos, idx) => {
                    const sym = pos.ticker || pos.symbol || "";
                    const pnlVal = Number(pos.unrealized_pnl ?? 0);
                    const pnlPct = Number(pos.unrealized_pnl_pct ?? 0);
                    const dailyChg = Number(pos.daily_change_pct ?? 0);
                    const isPos = pnlVal >= 0;
                    const curPrice = Number(pos.current_price ?? pos.avg_cost ?? 0);
                    const avgCost = Number(pos.avg_cost ?? 0);
                    const weight = Number(pos.weight_pct ?? 0);

                    return (
                      <div
                        key={idx}
                        onClick={() => router.push(`/asset?symbol=${sym}`)}
                        className="rounded-2xl p-4.5 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl hover:bg-zinc-900/60 hover:border-white/[0.15] transition-all cursor-pointer flex flex-col gap-3 group shadow-lg"
                      >
                        {/* Başlık ve Ticker */}
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-xl flex items-center justify-center font-bold font-data text-xs bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 group-hover:scale-105 group-hover:bg-emerald-500/20 transition-all">
                              {sym.slice(0, 3)}
                            </div>
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-bold font-data text-white group-hover:text-emerald-400 transition-colors">
                                  {sym}
                                </span>
                                <span className="text-[9px] px-1.5 py-0.2 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.06]">
                                  {pos.sector || "BIST"}
                                </span>
                              </div>
                              <p className="text-[11px] text-zinc-400 truncate max-w-[140px]">
                                {pos.name || pos.company_name || sym}
                              </p>
                            </div>
                          </div>

                          <span className={`px-2 py-0.5 rounded-lg text-xs font-bold font-data border ${
                            dailyChg > 0 
                              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" 
                              : dailyChg < 0 
                              ? "bg-rose-500/10 text-rose-400 border-rose-500/20" 
                              : "bg-white/[0.04] text-zinc-400 border-white/[0.06]"
                          }`} title="Bugünkü borsa değişimi">
                            {dailyChg > 0 ? "+" : ""}%{dailyChg.toFixed(2)} Bugün
                          </span>
                        </div>

                        {/* Metrikler */}
                        <div className="grid grid-cols-2 gap-2 pt-2 border-t border-white/[0.04] text-xs">
                          <div>
                            <span className="text-[10px] text-zinc-500 block uppercase">Fiyat & Maliyet</span>
                            <span className="font-bold font-data text-white">₺{curPrice.toFixed(2)}</span>
                            <span className="text-[10px] text-zinc-500 block">Mal: ₺{avgCost.toFixed(2)}</span>
                          </div>

                          <div className="text-right">
                            <span className="text-[10px] text-zinc-500 block uppercase">Toplam Değer</span>
                            <span className="font-bold font-data text-white">
                              ₺{Number(pos.market_value ?? 0).toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
                            </span>
                            <span className="text-[10px] text-zinc-500 block font-data">{pos.quantity} Lot · %{weight.toFixed(1)}</span>
                          </div>
                        </div>

                        {/* Net Kâr Alt Barı */}
                        <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-xs">
                          <span className="text-[11px] text-zinc-400">Net Kâr/Zarar:</span>
                          <div className="flex items-center gap-1.5 font-data">
                            <span className={`font-bold ${isPos ? "text-emerald-400" : "text-rose-400"}`}>
                              {isPos ? "+" : ""}₺{pnlVal.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </span>
                            <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded border ${
                              isPos 
                                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" 
                                : "bg-rose-500/10 text-rose-400 border-rose-500/20"
                            }`} title="Maliyete göre toplam getiri">
                              {isPos ? "+" : ""}%{pnlPct.toFixed(2)}
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {/* 5. EMİR & İŞLEM GEÇMİŞİ SEKMESİ */}
          {mainTab === "orders" && (
            <div className="rounded-2xl border border-white/[0.08] overflow-hidden bg-zinc-900/30 backdrop-blur-xl shadow-xl">
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-white/[0.06] text-[11px] font-bold uppercase tracking-wider bg-white/[0.01] select-none">
                      <th 
                        onClick={() => handleOrderSort("date")} 
                        className={`py-3.5 px-5 cursor-pointer transition-colors hover:text-white ${orderSortField === "date" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="Tarihe göre sırala"
                      >
                        <div className="flex items-center gap-1.5">
                          <span>Tarih</span>
                          <span className="text-xs font-mono">{orderSortField === "date" ? (orderSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th 
                        onClick={() => handleOrderSort("ticker")} 
                        className={`py-3.5 px-4 cursor-pointer transition-colors hover:text-white ${orderSortField === "ticker" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="Hisse adına göre sırala"
                      >
                        <div className="flex items-center gap-1.5">
                          <span>Hisse & Yön</span>
                          <span className="text-xs font-mono">{orderSortField === "ticker" ? (orderSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th 
                        onClick={() => handleOrderSort("quantity")} 
                        className={`py-3.5 px-4 text-right cursor-pointer transition-colors hover:text-white ${orderSortField === "quantity" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="Miktara göre sırala"
                      >
                        <div className="flex items-center justify-end gap-1.5">
                          <span>Miktar (Lot)</span>
                          <span className="text-xs font-mono">{orderSortField === "quantity" ? (orderSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th 
                        onClick={() => handleOrderSort("execution_price")} 
                        className={`py-3.5 px-4 text-right cursor-pointer transition-colors hover:text-white ${orderSortField === "execution_price" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="İşlem fiyatına göre sırala"
                      >
                        <div className="flex items-center justify-end gap-1.5">
                          <span>İşlem Fiyatı</span>
                          <span className="text-xs font-mono">{orderSortField === "execution_price" ? (orderSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th 
                        onClick={() => handleOrderSort("realized_pnl")} 
                        className={`py-3.5 px-4 text-right cursor-pointer transition-colors hover:text-white ${orderSortField === "realized_pnl" ? "text-emerald-400" : "text-zinc-400"}`}
                        title="Kâr / Zarara göre sırala"
                      >
                        <div className="flex items-center justify-end gap-1.5">
                          <span>Elde Edilen Kâr / Zarar</span>
                          <span className="text-xs font-mono">{orderSortField === "realized_pnl" ? (orderSortAsc ? "▲" : "▼") : "↕"}</span>
                        </div>
                      </th>
                      <th className="py-3.5 px-5 text-right text-zinc-400">Durum</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04] text-xs">
                    {filteredOrders.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="py-12 text-center text-zinc-500">
                          Seçili kategoride emir kaydı bulunmuyor.
                        </td>
                      </tr>
                    ) : (
                      filteredOrders.map((ord, idx) => {
                        const isBuy = ord.side === "BUY";
                        const pnl = ord.realized_pnl !== undefined ? Number(ord.realized_pnl) : null;
                        const isPos = (pnl ?? 0) >= 0;

                        return (
                          <tr key={idx} className="hover:bg-white/[0.02] transition-colors">
                            <td className="py-3 px-5 font-data text-zinc-400">
                              {ord.date || "2026-09-02"}
                            </td>
                            <td className="py-3 px-4">
                              <div className="flex items-center gap-2">
                                <span 
                                  onClick={() => router.push(`/asset?symbol=${ord.ticker}`)}
                                  className="font-bold font-data text-emerald-400 hover:underline cursor-pointer"
                                >
                                  {ord.ticker}
                                </span>
                                <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                                  isBuy 
                                    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" 
                                    : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                                }`}>
                                  {isBuy ? "ALIŞ" : "SATIŞ"}
                                </span>
                              </div>
                            </td>
                            <td className="py-3 px-4 text-right font-data font-bold text-zinc-200">
                              {ord.quantity?.toLocaleString("tr-TR")} Lot
                            </td>
                            <td className="py-3 px-4 text-right font-data text-white font-semibold">
                              ₺{Number(ord.execution_price ?? ord.exit_price ?? ord.signal_price ?? 0).toFixed(2)}
                            </td>
                            <td className="py-3 px-4 text-right font-data">
                              {pnl !== null ? (
                                <span className={`font-bold ${isPos ? "text-emerald-400" : "text-rose-400"}`}>
                                  {isPos ? "+" : ""}₺{pnl.toFixed(2)}
                                </span>
                              ) : (
                                <span className="text-[10px] text-zinc-500">Pozisyonda</span>
                              )}
                            </td>
                            <td className="py-3 px-5 text-right">
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                {ord.status === "FILLED" ? "GERÇEKLEŞTİ" : (ord.status || "KAPANDI")}
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
          )}

          {/* 6. T+2 TAKASBANK DETAYLARI SEKMESİ */}
          {mainTab === "t2" && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Valör Dağılımı */}
              <div className="rounded-2xl p-6 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl space-y-4">
                <div className="flex items-center gap-2 border-b border-white/[0.06] pb-3">
                  <Coins size={18} className="text-amber-400" />
                  <h3 className="text-sm font-bold uppercase tracking-wider text-white">
                    Takasbank T+2 Valör Dağılımı
                  </h3>
                </div>

                <div className="space-y-3 text-xs font-data">
                  <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.05]">
                    <span className="text-zinc-400">T+0 Serbest Nakit (Çekilebilir):</span>
                    <span className="font-bold text-white text-sm">₺{settledCash.toLocaleString("tr-TR", { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.05]">
                    <span className="text-zinc-400">T+1 Takas Alacağı (Yarın):</span>
                    <span className="font-bold text-zinc-300 text-sm">₺{unsettledT1.toLocaleString("tr-TR", { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.05]">
                    <span className="text-zinc-400">T+2 Takas Alacağı (Sonraki Gün):</span>
                    <span className="font-bold text-zinc-300 text-sm">₺{unsettledT2.toLocaleString("tr-TR", { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex items-center justify-between p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
                    <span className="text-emerald-400 font-bold">Toplam Alım Gücü:</span>
                    <span className="font-extrabold text-emerald-300 text-base">₺{purchasingPower.toLocaleString("tr-TR", { minimumFractionDigits: 2 })}</span>
                  </div>
                </div>
              </div>

              {/* Kurumsal Risk Sınırları */}
              <div className="rounded-2xl p-6 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl space-y-4">
                <div className="flex items-center gap-2 border-b border-white/[0.06] pb-3">
                  <ShieldCheck size={18} className="text-emerald-400" />
                  <h3 className="text-sm font-bold uppercase tracking-wider text-white">
                    Kurumsal BIST Risk Kapısı
                  </h3>
                </div>

                <div className="space-y-3 text-xs text-zinc-300">
                  <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.05] space-y-1">
                    <div className="font-semibold text-white">Tek Sektör Konsantrasyon Limiti: %30</div>
                    <p className="text-[11px] text-zinc-400">
                      Hiçbir sektör toplam portföyün %30'unu aşamaz. Otomatik rebalance motoru sınırı aşan sektörleri kısıtlar.
                    </p>
                  </div>
                  <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.05] space-y-1">
                    <div className="font-semibold text-white">Sentetik Likidite & Kayma (Slippage) Koruması</div>
                    <p className="text-[11px] text-zinc-400">
                      Alım ve satımlarda kademe derinliği simüle edilir, volatil piyasalarda emir hacmi bölünerek piyasa etkisi minimize edilir.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

        </div>
      </div>
    </ErrorBoundary>
  );
}
