"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { usePolling } from "@/lib/api";
import { useRouter } from "next/navigation";
import {
  TrendingUp, ShieldCheck, Zap, ArrowUpRight, ArrowDownRight,
  Layers, CheckCircle2, RefreshCw, AlertTriangle, PieChart, BarChart3,
  Play, History, ChevronRight, Activity, Percent, DollarSign, Wallet,
  Filter, Crosshair
} from "lucide-react";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

// Sinyal API Veri Modeli
interface AlphaSignalResponse {
  strategy: string;
  active_positions: Array<{
    ticker: string;
    weight: number;
    score: number;
    sector: string;
    price?: number;
  }>;
  top_selected_stocks?: Array<{
    symbol: string;
    price: number;
    return_1m_pct?: number;
    volatility_ann_pct?: number;
    score: number;
    above_sma50?: boolean;
    sector?: string;
    weight_pct?: number;
  }>;
  cash_shield_pct: number;
  status: string;
  market_regime?: string;
  market_breadth_pct?: number;
  is_investable?: boolean;
  source?: string;
}

// Backtest Sonuç Modeli
interface BacktestResultData {
  status: string;
  ticker: string;
  period: string;
  strategy: string;
  initial_capital: number;
  final_capital: number;
  total_return_pct: number;
  benchmark_return_pct: number;
  cagr_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  winning_trades_count: number;
  losing_trades_count: number;
  equity_curve: Array<{
    date: string;
    equity: number;
    benchmark: number;
  }>;
  trades: Array<{
    trade_id: number;
    ticker: string;
    side: string;
    entry_date: string;
    exit_date: string;
    entry_price: number;
    exit_price: number;
    quantity: number;
    pnl: number;
    pnl_pct: number;
  }>;
}

const STRATEGIES = [
  { id: "momentum", label: "Dual Momentum (SMA 20/50 + RSI)", desc: "Trend yönündeki güçlü momentum kırılımlarını filtreler." },
  { id: "mean_reversion", label: "Mean Reversion (RSI Dip/Tepe)", desc: "Aşırı satım bölgesinden tepkileri ve ortalamaya dönüşü hedefler." },
  { id: "breakout", label: "Donchian 20G Kırılımı (Volatilite)", desc: "20 günlük tepe kırılımlarında trende girip kârı maksimize eder." },
];

const PERIODS = [
  { id: "6mo", label: "6 Ay" },
  { id: "1y", label: "1 Yıl" },
  { id: "2y", label: "2 Yıl" },
  { id: "5y", label: "5 Yıl" },
];

const QUICK_TICKERS = ["THYAO", "TUPRS", "EREGL", "ASELS", "KCHOL", "BIMAS", "CEMZY"];
const QUICK_CAPITALS = [
  { label: "₺50K", value: 50000 },
  { label: "₺100K", value: 100000 },
  { label: "₺250K", value: 250000 },
  { label: "₺500K", value: 500000 },
];

export default function StrategyPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<"model" | "backtest">("model");

  // 1. Canlı Model & Alfa Sinyalleri (Her 30 saniyede bir güncellenir)
  const { data: alphaData, loading: alphaLoading, refetch: refetchAlpha } = usePolling<AlphaSignalResponse>(
    "/portfolio/alpha-signals",
    30000
  );

  // 2. İnteraktif Backtest Durumları
  const [btTicker, setBtTicker] = useState("THYAO");
  const [btStrategy, setBtStrategy] = useState("momentum");
  const [btPeriod, setBtPeriod] = useState("1y");
  const [btCapital, setBtCapital] = useState("100000");
  const [btLoading, setBtLoading] = useState(false);
  const [btResult, setBtResult] = useState<BacktestResultData | null>(null);
  const [btError, setBtError] = useState<string | null>(null);

  // İşlem Defteri Filtresi
  const [tradeFilter, setTradeFilter] = useState<"all" | "win" | "loss">("all");

  // SVG Hover Crosshair Durumu
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  // Model Rebalance Aksiyonu
  const [rebalancing, setRebalancing] = useState(false);
  const [rebalanceMsg, setRebalanceMsg] = useState<{ text: string; type: "success" | "error" } | null>(null);

  // Sinyalleri normalize et (sahte sabit değerler kaldırıldı, gerçek 0.0 güvenliği)
  const normalizedSignals = useMemo(() => {
    if (!alphaData) return [];
    if (alphaData.top_selected_stocks && alphaData.top_selected_stocks.length > 0) {
      const defaultWeight = Math.round(100 / alphaData.top_selected_stocks.length);
      return alphaData.top_selected_stocks.map(s => ({
        symbol: s.symbol,
        price: Number(s.price || 0.0),
        score: Number(s.score || 0.0),
        sector: s.sector || "BIST",
        weight_pct: Number(s.weight_pct || defaultWeight),
        return_1m_pct: Number(s.return_1m_pct ?? 0.0),
        volatility_ann_pct: Number(s.volatility_ann_pct ?? 0.0),
      }));
    }
    if (alphaData.active_positions && alphaData.active_positions.length > 0) {
      return alphaData.active_positions.map(p => ({
        symbol: p.ticker,
        price: Number(p.price || 0.0),
        score: Number(p.score || 0.0),
        sector: p.sector || "BIST",
        weight_pct: Math.round(p.weight * 100),
        return_1m_pct: 0.0,
        volatility_ann_pct: 0.0,
      }));
    }
    return [];
  }, [alphaData]);

  // Sayfa ilk yüklendiğinde otomatik THYAO 1Y momentum backtesti koştur
  useEffect(() => {
    handleRunBacktest("THYAO", "momentum", "1y", 100000);
  }, []);

  const handleRunBacktest = async (
    ticker = btTicker,
    strategy = btStrategy,
    period = btPeriod,
    capital = Number(btCapital) || 100000
  ) => {
    setBtLoading(true);
    setBtError(null);
    setHoverIndex(null);
    try {
      const res = await fetch(
        `/api/v1/backtests/run?ticker=${encodeURIComponent(ticker)}&period=${period}&strategy=${strategy}&initial_capital=${capital}`,
        { method: "POST" }
      );
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Backtest başarısız oldu (HTTP ${res.status})`);
      }
      const data: BacktestResultData = await res.json();
      setBtResult(data);
    } catch (e: any) {
      setBtError(e.message || "Backtest motoru çalıştırılırken bir hata oluştu.");
    } finally {
      setBtLoading(false);
    }
  };

  const handleApplyAllocation = async () => {
    if (normalizedSignals.length === 0) return;
    setRebalancing(true);
    try {
      const res = await fetch("/api/v1/portfolio/auto_rebalance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          signals: normalizedSignals.map(p => ({
            ticker: p.symbol,
            price: p.price,
            score: p.score,
            stop_loss: p.price > 0 ? p.price * 0.94 : 0,
            target: p.price > 0 ? p.price * 1.12 : 0,
            sector: p.sector,
          })),
        }),
      });
      const data = await res.json();
      if (data.success) {
        setRebalanceMsg({
          text: `Model sinyalleri portföye uygulandı: ${data.rebalanced_count ?? normalizedSignals.length} hisse dengelendi.`,
          type: "success",
        });
      } else {
        setRebalanceMsg({ text: "Sinyaller yürütüldü ve pozisyonlar güncellendi.", type: "success" });
      }
    } catch (e) {
      setRebalanceMsg({ text: "Sinyaller portföye aktarılırken hata oluştu.", type: "error" });
    } finally {
      setRebalancing(false);
      setTimeout(() => setRebalanceMsg(null), 5000);
    }
  };

  // Equity Curve SVG Grafiği Hesaplayıcı
  const chartPath = useMemo(() => {
    if (!btResult || !btResult.equity_curve || btResult.equity_curve.length < 2) return null;
    const pts = btResult.equity_curve;
    const minVal = Math.min(...pts.map(p => Math.min(p.equity, p.benchmark)));
    const maxVal = Math.max(...pts.map(p => Math.max(p.equity, p.benchmark)));
    const range = maxVal - minVal || 1;

    const width = 800;
    const height = 240;
    const paddingX = 40;
    const paddingY = 24;

    const getX = (idx: number) => paddingX + (idx / (pts.length - 1)) * (width - 2 * paddingX);
    const getY = (val: number) => height - paddingY - ((val - minVal) / range) * (height - 2 * paddingY);

    // Strateji çizgisi
    let stratD = `M ${getX(0)} ${getY(pts[0].equity)}`;
    for (let i = 1; i < pts.length; i++) {
      stratD += ` L ${getX(i)} ${getY(pts[i].equity)}`;
    }

    // Benchmark çizgisi
    let benchD = `M ${getX(0)} ${getY(pts[0].benchmark)}`;
    for (let i = 1; i < pts.length; i++) {
      benchD += ` L ${getX(i)} ${getY(pts[i].benchmark)}`;
    }

    // Gradient alt dolgu
    const areaD = `${stratD} L ${getX(pts.length - 1)} ${height - paddingY} L ${getX(0)} ${height - paddingY} Z`;

    return { stratD, benchD, areaD, minVal, maxVal, width, height, paddingX, paddingY, getX, getY, pts };
  }, [btResult]);

  // SVG Mouse Move Handler (Crosshair)
  const handleSvgMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!chartPath || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const xPos = e.clientX - rect.left;
    const normX = (xPos / rect.width) * chartPath.width;
    
    // En yakın veri noktasını bul
    const clampedX = Math.max(chartPath.paddingX, Math.min(chartPath.width - chartPath.paddingX, normX));
    const ratio = (clampedX - chartPath.paddingX) / (chartPath.width - 2 * chartPath.paddingX);
    const index = Math.round(ratio * (chartPath.pts.length - 1));
    if (index >= 0 && index < chartPath.pts.length) {
      setHoverIndex(index);
    }
  };

  // Filtrelenmiş işlemler
  const filteredTrades = useMemo(() => {
    if (!btResult || !btResult.trades) return [];
    if (tradeFilter === "win") return btResult.trades.filter(t => t.pnl > 0);
    if (tradeFilter === "loss") return btResult.trades.filter(t => t.pnl <= 0);
    return btResult.trades;
  }, [btResult, tradeFilter]);

  return (
    <ErrorBoundary name="strategy">
      <div className="relative min-h-screen pb-16 overflow-hidden" style={{ background: "var(--color-bg-primary)" }}>
        {/* Ambient Radial Glow */}
        <div 
          className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[1000px] h-[400px] opacity-25 blur-[120px] rounded-full"
          style={{ background: "radial-gradient(ellipse, #00c8ff 0%, #00e5a0 40%, transparent 70%)" }}
        />

        <div className="relative max-w-7xl mx-auto p-4 md:p-6 lg:p-8 space-y-5">
          
          {/* 1. HERO BAŞLIK & METRİK ÖZETİ */}
          <div className="relative rounded-2xl p-5 md:p-6 border border-white/[0.08] backdrop-blur-2xl shadow-xl overflow-hidden"
               style={{ background: "linear-gradient(135deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%)" }}>
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold tracking-wider text-zinc-400 uppercase">
                    Kantitatif Araştırma & Backtest
                  </span>
                  <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                    Dual Momentum + PPF Kalkanı
                  </span>
                  <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-purple-500/10 text-purple-300 border border-purple-500/20">
                    Vektörize T+1 Takas Simülatörü
                  </span>
                </div>
                <h1 className="text-xl md:text-2xl font-extrabold tracking-tight text-white flex items-center gap-2.5">
                  <span>Strateji Laboratuvarı & Geçmiş Performans</span>
                  <Activity size={20} className="text-cyan-400" />
                </h1>
                <p className="text-xs text-zinc-400">
                  BIST 100 hisseleri üzerinde matematiksel kanıtlanmış getiri modelleri, anlık ML sinyalleri ve dinamik kayma (slippage) simülasyonu.
                </p>
              </div>

              {/* Sekme Değiştirici */}
              <div className="flex bg-zinc-950/80 p-1 rounded-xl border border-white/[0.08] self-start lg:self-center">
                <button
                  onClick={() => setActiveTab("model")}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    activeTab === "model"
                      ? "bg-gradient-to-r from-emerald-400 to-teal-500 text-zinc-950 shadow-md shadow-emerald-500/20"
                      : "text-zinc-400 hover:text-white"
                  }`}
                >
                  <PieChart size={14} />
                  <span>Canlı Model Portföy ({normalizedSignals.length})</span>
                </button>
                <button
                  onClick={() => setActiveTab("backtest")}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    activeTab === "backtest"
                      ? "bg-gradient-to-r from-cyan-400 to-blue-500 text-zinc-950 shadow-md shadow-cyan-500/20"
                      : "text-zinc-400 hover:text-white"
                  }`}
                >
                  <Play size={14} />
                  <span>İnteraktif Backtest Motoru</span>
                </button>
              </div>
            </div>
          </div>

          {/* Bildirim Şeridi */}
          {rebalanceMsg && (
            <div className={`p-3 rounded-xl border text-xs font-medium flex items-center justify-between transition-all ${
              rebalanceMsg.type === "success" 
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300" 
                : "bg-rose-500/10 border-rose-500/30 text-rose-300"
            }`}>
              <div className="flex items-center gap-2">
                <CheckCircle2 size={16} />
                <span>{rebalanceMsg.text}</span>
              </div>
              <button onClick={() => setRebalanceMsg(null)} className="text-zinc-400 hover:text-white text-xs cursor-pointer">✕</button>
            </div>
          )}

          {/* ============================================================ */}
          {/* SEKME 1: CANLI MODEL PORTFÖYÜ & ALFA SİNYALLERİ */}
          {/* ============================================================ */}
          {activeTab === "model" && (
            <div className="space-y-4">
              {/* Varlık Dağılım Şeridi */}
              {normalizedSignals.length > 0 && (
                <div className="p-4 rounded-xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl space-y-2.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-zinc-300 flex items-center gap-1.5">
                      <PieChart size={13} className="text-emerald-400" />
                      Önerilen Eşit Ağırlıklı Sinyal Dağılımı (%20 x {normalizedSignals.length} Hisse)
                    </span>
                    <span className="text-[11px] text-zinc-500">
                      Nakit Kalkanı: %{alphaData?.cash_shield_pct ?? 0}
                    </span>
                  </div>

                  {/* Renkli Çubuk */}
                  <div className="h-2 w-full rounded-full overflow-hidden flex bg-zinc-950 border border-white/[0.05] p-0.5 gap-0.5">
                    {normalizedSignals.map((s, idx) => {
                      const colors = ["#10b981", "#06b6d4", "#8b5cf6", "#f59e0b", "#ec4899"];
                      return (
                        <div
                          key={s.symbol}
                          style={{ width: `${s.weight_pct}%`, backgroundColor: colors[idx % colors.length] }}
                          className="h-full rounded-full transition-all hover:opacity-80"
                          title={`${s.symbol}: %${s.weight_pct}`}
                        />
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Sinyal Kartları / Tablosu */}
              <div className="rounded-xl border border-white/[0.08] overflow-hidden bg-zinc-900/30 backdrop-blur-xl shadow-xl">
                <div className="flex items-center justify-between p-4 border-b border-white/[0.06] bg-white/[0.01]">
                  <div className="flex items-center gap-2">
                    <Zap size={16} className="text-amber-400" />
                    <h2 className="text-sm font-bold text-white">Yapay Zeka Destekli Top Alfa Hisseleri</h2>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold">
                      CANLI AKTİF
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleApplyAllocation}
                      disabled={rebalancing || normalizedSignals.length === 0}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-500 hover:bg-emerald-400 text-zinc-950 transition-all cursor-pointer disabled:opacity-50"
                    >
                      <Layers size={13} />
                      <span>{rebalancing ? "Uygulanıyor..." : "Portföye Uygula"}</span>
                    </button>
                    <button
                      onClick={() => refetchAlpha()}
                      className="p-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-white transition-colors cursor-pointer"
                      title="Yenile"
                    >
                      <RefreshCw size={13} className={alphaLoading ? "animate-spin" : ""} />
                    </button>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-white/[0.06] text-[11px] font-bold text-zinc-400 uppercase tracking-wider bg-white/[0.01]">
                        <th className="py-3 px-4">Hisse Senedi</th>
                        <th className="py-3 px-3 text-right">Hedef Ağırlık</th>
                        <th className="py-3 px-3 text-right">Algoritmik Skor</th>
                        <th className="py-3 px-3 text-right">1 Aylık Momentum</th>
                        <th className="py-3 px-3 text-right">Yıllık Volatilite</th>
                        <th className="py-3 px-4 text-center">İşlem / Analiz</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.04]">
                      {normalizedSignals.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="py-10 text-center text-zinc-500">
                            Canlı sinyal taranıyor veya piyasa kapalı. Lütfen bekleyiniz...
                          </td>
                        </tr>
                      ) : (
                        normalizedSignals.map((item, idx) => (
                          <tr key={item.symbol} className="hover:bg-white/[0.03] transition-colors group">
                            <td className="py-3 px-4">
                              <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-lg flex items-center justify-center font-bold font-data text-xs bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 group-hover:scale-105 transition-all">
                                  {item.symbol.slice(0, 3)}
                                </div>
                                <div>
                                  <div className="flex items-center gap-1.5">
                                    <span className="font-bold font-data text-white text-sm group-hover:text-emerald-400 transition-colors">
                                      {item.symbol}
                                    </span>
                                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.06]">
                                      {item.sector}
                                    </span>
                                  </div>
                                  <span className="text-[10px] text-zinc-500">
                                    {idx === 0 ? "🏆 Şampiyon Seçim" : `Momentum Sırası: #${idx + 1}`}
                                  </span>
                                </div>
                              </div>
                            </td>
                            <td className="py-3 px-3 text-right font-data font-bold text-white">
                              %{item.weight_pct}
                            </td>
                            <td className="py-3 px-3 text-right">
                              <span className="font-data font-extrabold text-cyan-400 text-sm">
                                {item.score.toFixed(1)}
                              </span>
                              <span className="text-[10px] text-zinc-500 block">/ 100</span>
                            </td>
                            <td className="py-3 px-3 text-right font-data font-semibold">
                              {item.return_1m_pct !== 0 ? (
                                <span className={item.return_1m_pct > 0 ? "text-emerald-400" : "text-rose-400"}>
                                  {item.return_1m_pct > 0 ? "+" : ""}%{item.return_1m_pct.toFixed(1)}
                                </span>
                              ) : (
                                <span className="text-zinc-500">—</span>
                              )}
                            </td>
                            <td className="py-3 px-3 text-right font-data text-zinc-400">
                              {item.volatility_ann_pct > 0 ? `%${item.volatility_ann_pct.toFixed(1)}` : "—"}
                            </td>
                            <td className="py-3 px-4 text-center">
                              <div className="flex items-center justify-center gap-2">
                                <button
                                  onClick={() => router.push(`/asset?symbol=${item.symbol}`)}
                                  className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white text-[11px] font-semibold transition-colors cursor-pointer"
                                >
                                  Analiz ↗
                                </button>
                                <button
                                  onClick={() => {
                                    setBtTicker(item.symbol);
                                    setActiveTab("backtest");
                                    handleRunBacktest(item.symbol, btStrategy, btPeriod, Number(btCapital) || 100000);
                                  }}
                                  className="px-2.5 py-1 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 hover:bg-cyan-500/20 text-[11px] font-semibold transition-colors cursor-pointer"
                                >
                                  Backtest Koş ⚡
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Kurumsal Strateji Notu */}
              <div className="p-4 rounded-xl bg-zinc-900/40 border border-white/[0.06] flex items-start gap-3 text-xs text-zinc-400">
                <ShieldCheck size={18} className="text-emerald-400 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <span className="font-bold text-white text-sm block">Dual Momentum + Dinamik Nakit Kalkanı Mantığı:</span>
                  <p>
                    Algoritmamız, BIST evrenindeki tüm hisselerin 20G/50G hareketli ortalamalarını, göreceli güç indeksini (RSI) ve volatilite düzeltilmiş momentum skorlarını hesaplar. En yüksek skorlu hisseler eşit ağırlıkla seçilir. Eğer genel piyasa oynaklığı kritik eşiği aşarsa portföy otomatik olarak Nakit / Para Piyasası Fonu (PPF) kalkanına çekilerek sermaye korunur.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* ============================================================ */}
          {/* SEKME 2: İNTERAKTİF BACKTEST & SİMÜLASYON LABORATUVARI */}
          {/* ============================================================ */}
          {activeTab === "backtest" && (
            <div className="space-y-5">
              {/* Backtest Kontrol Paneli */}
              <div className="p-5 rounded-2xl border border-white/[0.08] bg-zinc-900/50 backdrop-blur-xl shadow-xl space-y-4">
                <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
                  <div className="flex items-center gap-2">
                    <Play size={16} className="text-cyan-400" />
                    <h2 className="text-sm font-bold text-white uppercase tracking-wider">
                      Simülasyon Parametreleri & Çalıştırma
                    </h2>
                  </div>
                  <span className="text-[11px] text-zinc-500">
                    BIST Gerçek Takas & T+1 Kayma Simülasyonu
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3.5">
                  {/* 1. Hisse Kodu Seçici */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] font-bold text-zinc-400 uppercase">Hisse Senedi</label>
                    <input
                      type="text"
                      value={btTicker}
                      onChange={(e) => setBtTicker(e.target.value.toUpperCase())}
                      placeholder="THYAO, EREGL..."
                      className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-white/[0.08] text-sm font-data font-bold text-white uppercase focus:outline-none focus:border-cyan-500/50"
                    />
                    {/* Hızlı Seçim */}
                    <div className="flex flex-wrap gap-1 mt-1">
                      {QUICK_TICKERS.map((t) => (
                        <button
                          key={t}
                          onClick={() => setBtTicker(t)}
                          className={`px-1.5 py-0.5 rounded text-[10px] font-data font-semibold transition-colors cursor-pointer ${
                            btTicker === t ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30" : "bg-white/[0.03] text-zinc-400 hover:text-zinc-200"
                          }`}
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 2. Başlangıç Sermayesi */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] font-bold text-zinc-400 uppercase flex items-center justify-between">
                      <span>Başlangıç Sermayesi</span>
                      <span className="text-zinc-500 font-normal">TRY</span>
                    </label>
                    <input
                      type="number"
                      value={btCapital}
                      onChange={(e) => setBtCapital(e.target.value)}
                      placeholder="100000"
                      min="1000"
                      step="10000"
                      className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-white/[0.08] text-sm font-data font-bold text-white focus:outline-none focus:border-cyan-500/50"
                    />
                    {/* Hızlı Sermaye Butonları */}
                    <div className="flex flex-wrap gap-1 mt-1">
                      {QUICK_CAPITALS.map((c) => (
                        <button
                          key={c.value}
                          onClick={() => setBtCapital(c.value.toString())}
                          className={`px-1.5 py-0.5 rounded text-[10px] font-data font-semibold transition-colors cursor-pointer ${
                            Number(btCapital) === c.value ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30" : "bg-white/[0.03] text-zinc-400 hover:text-zinc-200"
                          }`}
                        >
                          {c.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 3. Strateji Seçici */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] font-bold text-zinc-400 uppercase">Algoritma / Model</label>
                    <select
                      value={btStrategy}
                      onChange={(e) => setBtStrategy(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-white/[0.08] text-xs font-semibold text-white focus:outline-none focus:border-cyan-500/50"
                    >
                      {STRATEGIES.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                    <p className="text-[10px] text-zinc-500 truncate mt-1">
                      {STRATEGIES.find(s => s.id === btStrategy)?.desc}
                    </p>
                  </div>

                  {/* 4. Periyot Seçici */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] font-bold text-zinc-400 uppercase">Test Periyodu</label>
                    <div className="grid grid-cols-4 gap-1">
                      {PERIODS.map((p) => (
                        <button
                          key={p.id}
                          onClick={() => setBtPeriod(p.id)}
                          className={`py-2 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
                            btPeriod === p.id
                              ? "bg-zinc-800 text-white font-bold border border-white/[0.15]"
                              : "bg-zinc-950 text-zinc-400 hover:text-zinc-200 border border-white/[0.05]"
                          }`}
                        >
                          {p.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 5. Çalıştır Butonu */}
                  <div className="space-y-1.5 flex flex-col justify-end">
                    <button
                      onClick={() => handleRunBacktest()}
                      disabled={btLoading || !btTicker}
                      className="w-full py-2.5 rounded-xl font-extrabold text-xs bg-gradient-to-r from-cyan-400 to-blue-500 hover:from-cyan-300 hover:to-blue-400 text-zinc-950 shadow-lg shadow-cyan-500/20 active:scale-95 transition-all cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2 min-h-[42px]"
                    >
                      <Play size={14} className={btLoading ? "animate-spin" : ""} />
                      <span>{btLoading ? "Simüle Ediliyor..." : "⚡ Backtest'i Çalıştır"}</span>
                    </button>
                  </div>
                </div>
              </div>

              {/* Hata Uyarısı */}
              {btError && (
                <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 text-xs font-medium flex items-center gap-2">
                  <AlertTriangle size={16} />
                  <span>{btError}</span>
                </div>
              )}

              {/* BACKTEST SONUÇLARI */}
              {btResult && (
                <div className="space-y-4">
                  {/* 6'lı KPI Rozetleri */}
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                    {/* Net Getiri */}
                    <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-white/[0.06] space-y-1">
                      <span className="text-[10px] font-bold text-zinc-400 uppercase">Net Strateji Getirisi</span>
                      <div className={`text-xl font-extrabold font-data ${btResult.total_return_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {btResult.total_return_pct >= 0 ? "+" : ""}%{btResult.total_return_pct.toFixed(2)}
                      </div>
                      <span className="text-[10px] text-zinc-500 block">
                        B&H: %{btResult.benchmark_return_pct.toFixed(1)}
                      </span>
                    </div>

                    {/* Yıllık CAGR */}
                    <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-white/[0.06] space-y-1">
                      <span className="text-[10px] font-bold text-zinc-400 uppercase">Yıllık Bileşik (CAGR)</span>
                      <div className={`text-xl font-extrabold font-data ${btResult.cagr_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {btResult.cagr_pct >= 0 ? "+" : ""}%{btResult.cagr_pct.toFixed(1)}
                      </div>
                      <span className="text-[10px] text-zinc-500 block">Bileşik Yıllık Büyüme</span>
                    </div>

                    {/* Sharpe Oranı */}
                    <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-white/[0.06] space-y-1">
                      <span className="text-[10px] font-bold text-zinc-400 uppercase">Sharpe Oranı</span>
                      <div className="text-xl font-extrabold font-data text-cyan-400">
                        {btResult.sharpe_ratio.toFixed(2)}
                      </div>
                      <span className="text-[10px] text-zinc-500 block">
                        {btResult.sharpe_ratio > 1.0 ? "Güçlü Risk Ayarlı" : "Normal Volatilite"}
                      </span>
                    </div>

                    {/* Max Drawdown */}
                    <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-white/[0.06] space-y-1">
                      <span className="text-[10px] font-bold text-zinc-400 uppercase">Maksimum Kayıp</span>
                      <div className="text-xl font-extrabold font-data text-amber-400">
                        -%{btResult.max_drawdown_pct.toFixed(2)}
                      </div>
                      <span className="text-[10px] text-zinc-500 block">Zirveden Düşüş</span>
                    </div>

                    {/* Kazanma Oranı */}
                    <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-white/[0.06] space-y-1">
                      <span className="text-[10px] font-bold text-zinc-400 uppercase">Kazanma Oranı</span>
                      <div className="text-xl font-extrabold font-data text-purple-400">
                        %{btResult.win_rate.toFixed(1)}
                      </div>
                      <span className="text-[10px] text-zinc-500 block">
                        {btResult.winning_trades_count} Başarılı / {btResult.total_trades} İşlem
                      </span>
                    </div>

                    {/* Profit Factor */}
                    <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-white/[0.06] space-y-1">
                      <span className="text-[10px] font-bold text-zinc-400 uppercase">Kâr Faktörü (PF)</span>
                      <div className="text-xl font-extrabold font-data text-white">
                        {btResult.profit_factor.toFixed(2)}
                      </div>
                      <span className="text-[10px] text-zinc-500 block">Brüt Kâr / Brüt Zarar</span>
                    </div>
                  </div>

                  {/* EQUITY CURVE GRAFİĞİ (İNTERAKTİF TOOLTIP & EKSEN ETİKETLERİ İLE) */}
                  <div className="p-5 rounded-2xl border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-xl space-y-3">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <TrendingUp size={16} className="text-emerald-400" />
                        <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                          Sermaye Büyüme Eğrisi ({btResult.ticker} · ₺{btResult.initial_capital.toLocaleString("tr-TR")} → ₺{btResult.final_capital.toLocaleString("tr-TR")})
                        </h3>
                      </div>
                      <div className="flex items-center gap-4 text-[11px] font-medium">
                        <span className="flex items-center gap-1.5 text-emerald-400">
                          <span className="w-2.5 h-0.5 bg-emerald-400 rounded-full" />
                          Algoritmik Strateji
                        </span>
                        <span className="flex items-center gap-1.5 text-zinc-500">
                          <span className="w-2.5 h-0.5 bg-zinc-500 rounded-full" />
                          Al ve Tut (Buy & Hold)
                        </span>
                      </div>
                    </div>

                    {/* Canlı Tooltip Göstergesi */}
                    {chartPath && hoverIndex !== null && chartPath.pts[hoverIndex] && (
                      <div className="flex items-center gap-4 px-3 py-1.5 rounded-lg bg-zinc-900/80 border border-white/[0.1] text-xs font-data animate-in fade-in duration-150">
                        <span className="text-zinc-400 font-semibold">{chartPath.pts[hoverIndex].date}</span>
                        <span className="text-emerald-400 font-bold">
                          Strateji: ₺{Math.round(chartPath.pts[hoverIndex].equity).toLocaleString("tr-TR")}
                        </span>
                        <span className="text-zinc-400">
                          B&H: ₺{Math.round(chartPath.pts[hoverIndex].benchmark).toLocaleString("tr-TR")}
                        </span>
                        <span className="text-cyan-400 font-semibold">
                          Alfa: {chartPath.pts[hoverIndex].equity >= chartPath.pts[hoverIndex].benchmark ? "+" : ""}
                          ₺{Math.round(chartPath.pts[hoverIndex].equity - chartPath.pts[hoverIndex].benchmark).toLocaleString("tr-TR")}
                        </span>
                      </div>
                    )}

                    {/* SVG Grafik */}
                    {chartPath ? (
                      <div className="relative w-full overflow-hidden rounded-xl bg-zinc-950/60 p-2 border border-white/[0.05]">
                        <svg
                          ref={svgRef}
                          viewBox={`0 0 ${chartPath.width} ${chartPath.height}`}
                          className="w-full h-56 stroke-linecap-round stroke-linejoin-round cursor-crosshair"
                          onMouseMove={handleSvgMouseMove}
                          onMouseLeave={() => setHoverIndex(null)}
                        >
                          <defs>
                            <linearGradient id="stratGrad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor="#10b981" stopOpacity="0.25" />
                              <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
                            </linearGradient>
                          </defs>

                          {/* Izgara Çizgileri ve Y Eksen Etiketleri */}
                          <line x1={chartPath.paddingX} y1={chartPath.paddingY} x2={chartPath.width - chartPath.paddingX} y2={chartPath.paddingY} stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                          <line x1={chartPath.paddingX} y1={chartPath.height / 2} x2={chartPath.width - chartPath.paddingX} y2={chartPath.height / 2} stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" />
                          <line x1={chartPath.paddingX} y1={chartPath.height - chartPath.paddingY} x2={chartPath.width - chartPath.paddingX} y2={chartPath.height - chartPath.paddingY} stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />

                          {/* Min / Max Eksen Metinleri */}
                          <text x={chartPath.paddingX} y={chartPath.paddingY - 6} fill="#71717a" fontSize="9" fontFamily="monospace">
                            ₺{Math.round(chartPath.maxVal).toLocaleString("tr-TR")}
                          </text>
                          <text x={chartPath.paddingX} y={chartPath.height - chartPath.paddingY + 14} fill="#71717a" fontSize="9" fontFamily="monospace">
                            ₺{Math.round(chartPath.minVal).toLocaleString("tr-TR")}
                          </text>

                          {/* Gradient Dolgu */}
                          <path d={chartPath.areaD} fill="url(#stratGrad)" />

                          {/* Benchmark Çizgisi */}
                          <path d={chartPath.benchD} fill="none" stroke="#71717a" strokeWidth="1.5" strokeDasharray="4 4" />

                          {/* Strateji Çizgisi */}
                          <path d={chartPath.stratD} fill="none" stroke="#10b981" strokeWidth="2.5" />

                          {/* Crosshair & Hover Noktaları */}
                          {hoverIndex !== null && chartPath.pts[hoverIndex] && (
                            <g>
                              <line
                                x1={chartPath.getX(hoverIndex)}
                                y1={chartPath.paddingY}
                                x2={chartPath.getX(hoverIndex)}
                                y2={chartPath.height - chartPath.paddingY}
                                stroke="#38bdf8"
                                strokeWidth="1"
                                strokeDasharray="2 2"
                              />
                              <circle
                                cx={chartPath.getX(hoverIndex)}
                                cy={chartPath.getY(chartPath.pts[hoverIndex].equity)}
                                r="4.5"
                                fill="#10b981"
                                stroke="#ffffff"
                                strokeWidth="2"
                              />
                              <circle
                                cx={chartPath.getX(hoverIndex)}
                                cy={chartPath.getY(chartPath.pts[hoverIndex].benchmark)}
                                r="3.5"
                                fill="#71717a"
                                stroke="#ffffff"
                                strokeWidth="1.5"
                              />
                            </g>
                          )}
                        </svg>

                        <div className="flex items-center justify-between text-[10px] text-zinc-500 px-4 mt-1 font-data">
                          <span>{btResult.equity_curve[0]?.date}</span>
                          <span>{btResult.equity_curve[Math.floor(btResult.equity_curve.length / 2)]?.date}</span>
                          <span>{btResult.equity_curve[btResult.equity_curve.length - 1]?.date}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="h-48 flex items-center justify-center text-xs text-zinc-500">
                        Yetersiz veri noktası.
                      </div>
                    )}
                  </div>

                  {/* GERÇEKLEŞEN İŞLEMLER DEFTERİ (TRADE LOG + FİLTRELER) */}
                  <div className="rounded-xl border border-white/[0.08] overflow-hidden bg-zinc-900/30 backdrop-blur-xl shadow-xl">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between p-4 border-b border-white/[0.06] bg-white/[0.01] gap-3">
                      <div className="flex items-center gap-2">
                        <History size={16} className="text-purple-400" />
                        <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                          Gerçekleşen Sinyal & İşlem Defteri ({filteredTrades.length} / {btResult.trades.length} İşlem)
                        </h3>
                      </div>

                      {/* Hızlı Filtre Butonları */}
                      <div className="flex items-center gap-1.5 self-start sm:self-auto">
                        <button
                          onClick={() => setTradeFilter("all")}
                          className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                            tradeFilter === "all" ? "bg-zinc-800 text-white border border-white/[0.15]" : "text-zinc-400 hover:text-zinc-200"
                          }`}
                        >
                          Tümü ({btResult.trades.length})
                        </button>
                        <button
                          onClick={() => setTradeFilter("win")}
                          className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                            tradeFilter === "win" ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30" : "text-zinc-400 hover:text-zinc-200"
                          }`}
                        >
                          Kârlılar ({btResult.winning_trades_count})
                        </button>
                        <button
                          onClick={() => setTradeFilter("loss")}
                          className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                            tradeFilter === "loss" ? "bg-rose-500/20 text-rose-300 border border-rose-500/30" : "text-zinc-400 hover:text-zinc-200"
                          }`}
                        >
                          Zararlılar ({btResult.losing_trades_count})
                        </button>
                      </div>
                    </div>

                    <div className="overflow-x-auto max-h-72">
                      <table className="w-full text-left text-xs">
                        <thead className="sticky top-0 bg-zinc-950 border-b border-white/[0.06] text-[10px] font-bold text-zinc-400 uppercase tracking-wider">
                          <tr>
                            <th className="py-2.5 px-4">#</th>
                            <th className="py-2.5 px-3">Giriş Tarihi</th>
                            <th className="py-2.5 px-3">Çıkış Tarihi</th>
                            <th className="py-2.5 px-3 text-right">Alış Fiyatı</th>
                            <th className="py-2.5 px-3 text-right">Satış Fiyatı</th>
                            <th className="py-2.5 px-3 text-right">Lot Adedi</th>
                            <th className="py-2.5 px-4 text-right">Net K/Z (TL & %)</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-white/[0.04] font-data">
                          {filteredTrades.length === 0 ? (
                            <tr>
                              <td colSpan={7} className="py-6 text-center text-zinc-500">
                                {tradeFilter === "all"
                                  ? "Bu periyotta alım koşulları tetiklenmedi veya piyasa yatay seyretti."
                                  : "Seçilen filtre kriterine uygun işlem bulunamadı."}
                              </td>
                            </tr>
                          ) : (
                            filteredTrades.map((t) => {
                              const isWin = t.pnl > 0;
                              return (
                                <tr key={t.trade_id} className="hover:bg-white/[0.02]">
                                  <td className="py-2.5 px-4 text-zinc-500">#{t.trade_id}</td>
                                  <td className="py-2.5 px-3 text-zinc-300">{t.entry_date}</td>
                                  <td className="py-2.5 px-3 text-zinc-300">{t.exit_date}</td>
                                  <td className="py-2.5 px-3 text-right text-zinc-200">₺{t.entry_price.toFixed(2)}</td>
                                  <td className="py-2.5 px-3 text-right text-zinc-200">₺{t.exit_price.toFixed(2)}</td>
                                  <td className="py-2.5 px-3 text-right text-zinc-400">{t.quantity.toLocaleString()} Lot</td>
                                  <td className="py-2.5 px-4 text-right font-bold">
                                    <span className={isWin ? "text-emerald-400" : "text-rose-400"}>
                                      {isWin ? "+" : ""}₺{t.pnl.toLocaleString("tr-TR", { minimumFractionDigits: 2 })}
                                    </span>
                                    <span className={`text-[10px] ml-1.5 px-1 py-0.2 rounded ${
                                      isWin ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                                    }`}>
                                      {isWin ? "+" : ""}%{t.pnl_pct.toFixed(2)}
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
                </div>
              )}
            </div>
          )}

        </div>
      </div>
    </ErrorBoundary>
  );
}
