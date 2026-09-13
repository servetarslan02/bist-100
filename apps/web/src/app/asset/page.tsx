"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { api, getCachedData } from "@/lib/api";
import {
  Search, TrendingUp, TrendingDown, Sparkles,
  BarChart3, Activity, ShieldCheck, Zap, Layers,
  Compass, ArrowUpRight, ArrowDownRight, RefreshCw,
  Cpu, Target, CheckCircle2, Copy, Check, Flame
} from "lucide-react";
import { SkeletonList, SkeletonCard, SkeletonTable, SkeletonChart } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

const TradingViewChart = dynamic(
  () => import("@/components/charts/TradingViewChart").then((mod) => mod.TradingViewChart),
  { ssr: false, loading: () => <div className="h-[300px] flex items-center justify-center text-xs text-zinc-500">Grafik Yükleniyor...</div> }
);

const TradingViewWidget = dynamic(
  () => import("@/components/charts/TradingViewWidget").then((mod) => mod.TradingViewWidget),
  { ssr: false, loading: () => <div className="h-[480px] flex items-center justify-center text-xs text-zinc-500">TradingView Pro Grafik Yükleniyor...</div> }
);

interface LiveAssetData {
  symbol: string;
  name: string;
  sector: string;
  price: number;
  prev_price: number;
  change_pct: number;
  market_cap: string;
  pe_ratio: number;
  pb_ratio: number;
  rsi_14: number;
  sma_20: number;
  sma_50: number;
  support: number;
  resistance: number;
  atr_14: number;
  macd_val: number;
  macd_sig_val: number;
  macd_signal: string;
  recommendation: "STRONG_BUY" | "BUY" | "HOLD" | "SELL";
  recommendation_text: string;
  recommendation_score: number;
  candles: Array<{ time: string; open: number; high: number; low: number; close: number; volume: number }>;
  candle_patterns?: string[];
  primary_pattern?: string;
  buyer_pressure_pct?: number;
  seller_pressure_pct?: number;
  has_fvg?: boolean;
  fvg_type?: string;
  fvg_gap_range?: number[];
  candle_evidence?: string[];
  is_real_data: boolean;
}

const POPULAR_TICKERS = [
  "THYAO", "ASELS", "GARAN", "AKBNK", "KCHOL",
  "TUPRS", "EREGL", "BIMAS", "FROTO", "PGSUS",
  "SISE", "ASTOR", "TCELL", "ISCTR", "CEMZY"
];

const BIST_QUICK_SEARCH = [
  { symbol: "THYAO", name: "Türk Hava Yolları" },
  { symbol: "ASELS", name: "Aselsan Elektronik" },
  { symbol: "GARAN", name: "Garanti BBVA" },
  { symbol: "AKBNK", name: "Akbank" },
  { symbol: "ISCTR", name: "İş Bankası (C)" },
  { symbol: "YKBNK", name: "Yapı ve Kredi Bankası" },
  { symbol: "KCHOL", name: "Koç Holding" },
  { symbol: "SAHOL", name: "Sabancı Holding" },
  { symbol: "TUPRS", name: "Tüpraş Türkiye Petrol" },
  { symbol: "EREGL", name: "Ereğli Demir Çelik" },
  { symbol: "BIMAS", name: "BİM Birleşik Mağazalar" },
  { symbol: "FROTO", name: "Ford Otosan" },
  { symbol: "PGSUS", name: "Pegasus Hava Taşımacılığı" },
  { symbol: "SISE", name: "Şişecam" },
  { symbol: "ASTOR", name: "Astor Enerji" },
  { symbol: "TCELL", name: "Turkcell İletişim" },
  { symbol: "CEMZY", name: "Çimbeton Hazır Beton" },
  { symbol: "KOPOL", name: "Koza Polyester" },
  { symbol: "SANEL", name: "San-El Mühendislik" },
  { symbol: "MERKO", name: "Merko Gıda" },
  { symbol: "ULKER", name: "Ülker Bisküvi" },
  { symbol: "IHLAS", name: "İhlas Holding" },
  { symbol: "SARKY", name: "Sarkuysan Bakır" },
  { symbol: "CITAS", name: "Çitlekçi Gıda" },
  { symbol: "AKFGY", name: "Akfen GYO" },
  { symbol: "SASA", name: "Sasa Polyester" },
  { symbol: "HEKTS", name: "Hektaş Ticaret" },
  { symbol: "PETKM", name: "Petkim Petrokimya" },
  { symbol: "TTKOM", name: "Türk Telekom" },
  { symbol: "KOZAL", name: "Koza Altın İşletmeleri" },
  { symbol: "EKGYO", name: "Emlak Konut GYO" },
  { symbol: "ALARK", name: "Alarko Holding" },
  { symbol: "ENKAI", name: "Enka İnşaat" },
  { symbol: "MGROS", name: "Migros Ticaret" },
  { symbol: "SOKM", name: "Şok Marketler" },
  { symbol: "TOASO", name: "Tofaş Türk Otomobil" },
  { symbol: "VESTL", name: "Vestel Elektronik" },
  { symbol: "ARCLK", name: "Arçelik" },
  { symbol: "KONTR", name: "Kontrolmatik Teknoloji" },
  { symbol: "MIATK", name: "Mia Teknoloji" },
  { symbol: "REEDR", name: "Reeder Teknoloji" },
  { symbol: "TABGD", name: "TAB Gıda" },
];

type TimeframeType = "1D" | "1W" | "1M";

const TIMEFRAME_CONFIG: Record<TimeframeType, { label: string; period: string; interval: string }> = {
  "1D": { label: "GÜNLÜK (1G)", period: "6mo", interval: "1d" },
  "1W": { label: "HAFTALIK (1H)", period: "2y", interval: "1wk" },
  "1M": { label: "AYLIK (1A)", period: "5y", interval: "1mo" },
};

function AssetIntelContent() {
  const searchParams = useSearchParams();
  const initialTicker = (searchParams.get("symbol") || searchParams.get("ticker"))?.toUpperCase() || "THYAO";

  const [tickerInput, setTickerInput] = useState(initialTicker);
  const [activeTicker, setActiveTicker] = useState(initialTicker);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [timeframe, setTimeframe] = useState<TimeframeType>("1D");
  const [chartMode, setChartMode] = useState<"tradingview" | "local">("local");
  // Cache'ten aninda hidrasyon (0ms) — sayfa/ticker degisiminde "Yukleniyor..." ekranina
  // dusmeden onceki veriyi gosterip arka planda tazeler.
  const [asset, setAsset] = useState<LiveAssetData | null>(() =>
    getCachedData<LiveAssetData>(
      `/market/instruments/${initialTicker}/live_intel?period=${TIMEFRAME_CONFIG["1D"].period}&interval=${TIMEFRAME_CONFIG["1D"].interval}`
    )
  );
  const [loading, setLoading] = useState(() => !asset);
  const [chartLoading, setChartLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiReport, setAiReport] = useState<string | null>(null);
  const [loadingAi, setLoadingAi] = useState(false);
  const [copied, setCopied] = useState(false);
  const [priceFlash, setPriceFlash] = useState<"flash-up" | "flash-down" | "">("");
  const prevPriceRef = useState<{ val: number | null }>({ val: null })[0];

  useEffect(() => {
    const qTicker = (searchParams.get("symbol") || searchParams.get("ticker"))?.toUpperCase();
    if (qTicker && qTicker !== activeTicker) {
      setActiveTicker(qTicker);
      setTickerInput(qTicker);
    }
  }, [searchParams]);

  // Fetch real live intelligence data from backend with continuous 1.5s live stream
  useEffect(() => {
    let isMounted = true;
    let isInitial = true;

    async function fetchAssetData() {
      const tf = TIMEFRAME_CONFIG[timeframe];
      const cacheKey = `/market/instruments/${activeTicker}/live_intel?period=${tf.period}&interval=${tf.interval}`;

      const cached = getCachedData<LiveAssetData>(cacheKey);
      if (isInitial) {
        if (cached) {
          setAsset(cached);
          setLoading(false);
        } else if (!asset) {
          setLoading(true);
        }
      }
      setError(null);

      try {
        const data = await api<LiveAssetData>(cacheKey);
        if (isMounted) {
          setAsset(data);
          if (data && data.price != null) {
            const p = Number(data.price);
            if (prevPriceRef.val !== null) {
              if (p > prevPriceRef.val) {
                setPriceFlash("flash-up");
                setTimeout(() => setPriceFlash(""), 1300);
              } else if (p < prevPriceRef.val) {
                setPriceFlash("flash-down");
                setTimeout(() => setPriceFlash(""), 1300);
              }
            }
            prevPriceRef.val = p;
          }
        }
      } catch (err: unknown) {
        if (isMounted && !cached && !asset) {
          setError(err instanceof Error ? err.message : "Veri çekme hatası");
        }
      } finally {
        if (isMounted && isInitial) {
          setLoading(false);
          isInitial = false;
        }
      }
    }

    fetchAssetData();
    const intervalTimer = setInterval(fetchAssetData, 5000); // SSD write reduction: 1.5s → 5s

    return () => {
      isMounted = false;
      clearInterval(intervalTimer);
    };
  }, [activeTicker, timeframe]);

  const filteredSuggestions = tickerInput.trim()
    ? BIST_QUICK_SEARCH.filter(
        (s) =>
          s.symbol.includes(tickerInput.trim().toUpperCase()) ||
          s.name.toLowerCase().includes(tickerInput.trim().toLowerCase())
      ).slice(0, 8)
    : [];

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (tickerInput.trim()) {
      const sym = tickerInput.trim().toUpperCase();
      setShowSuggestions(false);
      if (sym !== activeTicker) {
        setAsset(null);
        setLoading(true);
        setActiveTicker(sym);
        setAiReport(null);
      }
    }
  };

  const handleSelectTicker = (sym: string) => {
    setShowSuggestions(false);
    if (sym !== activeTicker) {
      setAsset(null);
      setLoading(true);
      setTickerInput(sym);
      setActiveTicker(sym);
      setAiReport(null);
    }
  };

  const handleAskGemini = async () => {
    if (!asset) return;
    setLoadingAi(true);
    try {
      const queryParams = new URLSearchParams({
        price: String(asset.price),
        sector: asset.sector || "BIST",
        rsi: String(asset.rsi_14 ?? 50),
        pe: String(asset.pe_ratio ?? 7.5),
        pb: String(asset.pb_ratio ?? 1.8),
        support: String(asset.support ?? (asset.price * 0.95)),
        resistance: String(asset.resistance ?? (asset.price * 1.05)),
      });
      const data = await api<{ report?: string; model?: string }>(
        `/intelligence/gemini_report/${asset.symbol}?${queryParams.toString()}`
      );
      setAiReport(data?.report || "Rapor oluşturuldu.");
    } catch (err) {
      // Fallback direct fetch if needed
      try {
        const queryParams = new URLSearchParams({
          price: String(asset.price),
          sector: asset.sector || "BIST",
        });
        const res = await fetch(`/api/v1/intelligence/gemini_report/${asset.symbol}?${queryParams.toString()}`);
        const data = await res.json();
        setAiReport(data?.report || "Rapor oluşturuldu.");
      } catch {
        setAiReport("Gemini analizi şu anda yoğunluk nedeniyle yanıt veremedi. Lütfen tekrar deneyiniz.");
      }
    } finally {
      setLoadingAi(false);
    }
  };

  const handleCopyReport = () => {
    if (aiReport) {
      navigator.clipboard.writeText(aiReport);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const isPos = (asset?.change_pct ?? 0) >= 0;

  return (
    <ErrorBoundary name="asset">
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header & Quick Ticker Selector */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold gradient-text">Canlı Varlık İstihbarat Laboratuvarı</h1>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              %100 Gerçek BİST Verisi
            </span>
          </div>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            BIST Şirket Değerleme Göstergeleri · TradingView Mum Grafiği · Gemini 3.7 Canlı İstihbaratı
          </p>
        </div>

        <div className="relative">
          <form onSubmit={handleSearch} className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 focus-within:border-emerald-500/60 transition-colors">
              <Search size={12} className="text-zinc-500" />
              <input
                type="text"
                value={tickerInput}
                onChange={(e) => {
                  setTickerInput(e.target.value.toUpperCase());
                  setShowSuggestions(true);
                }}
                onFocus={() => setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                placeholder="Hisse Kodu (THYAO)..."
                className="bg-transparent text-xs text-zinc-200 focus:outline-none w-36 font-data uppercase"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500 text-zinc-950 hover:bg-emerald-400 cursor-pointer transition-all disabled:opacity-60"
            >
              {loading ? <RefreshCw size={11} className="animate-spin" /> : null}
              <span>{loading ? "Aranıyor..." : "İncele"}</span>
            </button>
          </form>

          {/* Anlık Autocomplete Öneri Menüsü (0 ms tepki) */}
          {showSuggestions && (
            <div className="absolute top-full left-0 right-16 mt-1.5 bg-zinc-900/95 backdrop-blur-md border border-zinc-700/80 rounded-xl shadow-2xl overflow-hidden z-50 py-1 max-h-64 overflow-y-auto">
              {tickerInput.trim().length > 0 && (
                <div
                  onMouseDown={() => handleSelectTicker(tickerInput.trim().toUpperCase())}
                  className="px-3 py-2 bg-emerald-500/10 hover:bg-emerald-500/20 border-b border-emerald-500/20 flex items-center justify-between cursor-pointer transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Zap size={13} className="text-emerald-400" />
                    <span className="text-xs font-bold font-data text-emerald-300">BIST:{tickerInput.trim().toUpperCase()}</span>
                  </div>
                  <span className="text-[10px] text-emerald-400 font-medium">TradingView'da Doğrudan Aç →</span>
                </div>
              )}
              {filteredSuggestions.map((item) => (
                <div
                  key={item.symbol}
                  onMouseDown={() => handleSelectTicker(item.symbol)}
                  className="px-3 py-2 hover:bg-zinc-800/80 flex items-center justify-between cursor-pointer transition-colors"
                >
                  <span className="text-xs font-semibold font-data text-emerald-400">{item.symbol}</span>
                  <span className="text-[11px] text-zinc-400 truncate max-w-[140px]">{item.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Quick Select Tickers */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1 select-none">
        <span className="text-[10px] text-zinc-500 font-medium uppercase tracking-wider mr-1">Popüler:</span>
        {POPULAR_TICKERS.map((sym) => (
          <button
            key={sym}
            onClick={() => handleSelectTicker(sym)}
            className={`px-2.5 py-1 rounded-lg text-[11px] font-data font-medium transition-all cursor-pointer ${
              activeTicker === sym
                ? "bg-emerald-500 text-zinc-950 font-semibold shadow-md shadow-emerald-500/20"
                : "bg-zinc-900/80 text-zinc-400 border border-zinc-800 hover:text-zinc-200 hover:border-zinc-700"
            }`}
          >
            {sym}
          </button>
        ))}
      </div>

      {loading && !asset && (
        <div className="rounded-xl p-12 text-center bg-zinc-900/40 border border-zinc-800/60">
          <RefreshCw size={24} className="mx-auto mb-3 text-emerald-400 animate-spin" />
          <p className="text-xs text-zinc-400">{activeTicker} için gerçek piyasa verileri ve indikatörler hesaplanıyor...</p>
        </div>
      )}

      {error && (
        <div className="rounded-xl p-6 bg-red-950/20 border border-red-500/30 text-center">
          <p className="text-xs text-red-400 font-medium">{error}</p>
          <button
            onClick={() => setActiveTicker("THYAO")}
            className="mt-3 px-3 py-1.5 rounded bg-zinc-800 text-xs text-zinc-200 hover:bg-zinc-700 cursor-pointer"
          >
            THYAO ile Devam Et
          </button>
        </div>
      )}

      {asset && (
        <>
          {/* Asset Hero Card */}
          <div
            className="rounded-xl p-5 select-none"
            style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-xl flex items-center justify-center bg-emerald-500/10 border border-emerald-500/20">
                  <span className="text-sm font-semibold font-data text-emerald-400">{asset.symbol}</span>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold text-zinc-100">{asset.name}</h2>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 font-medium">
                      {asset.sector}
                    </span>
                  </div>
                  <p className="text-[11px] text-zinc-500 mt-0.5">
                    Piyasa Değeri: {asset.market_cap} · Son Güncelleme: Canlı BİST
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-4">
                <button
                  onClick={handleAskGemini}
                  disabled={loadingAi}
                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30 hover:bg-purple-500/30 cursor-pointer transition-all shadow-md active:scale-95"
                >
                  <Sparkles size={13} className={loadingAi ? "animate-spin" : ""} />
                  {loadingAi ? "Gemini 3.7 Analiz Ediyor..." : "Gemini 3.7 Canlı Raporu"}
                </button>
                <div className="text-right">
                  <span className={`text-xl font-semibold font-data block text-zinc-100 rounded px-1 transition-colors ${priceFlash}`}>
                    ₺{asset.price != null ? Number(asset.price).toFixed(2) : "—"}
                  </span>
                  <div className="flex items-center justify-end gap-1">
                    {isPos ? <ArrowUpRight size={12} className="text-emerald-400" /> : <ArrowDownRight size={12} className="text-red-400" />}
                    <span className={`text-xs font-semibold font-data ${isPos ? "text-emerald-400" : "text-red-400"}`}>
                      {isPos ? "+" : ""}%{asset.change_pct != null ? Number(asset.change_pct).toFixed(2) : "0.00"} (Bugün)
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Interactive TradingView Candlestick Chart */}
          <div
            className="rounded-xl p-5 select-none space-y-3"
            style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-zinc-800/60 pb-3">
              <div className="flex items-center gap-2">
                <BarChart3 size={15} className="text-emerald-400" />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-200">
                  {activeTicker} — {chartMode === "tradingview" ? "TradingView Resmi Canlı Pro Grafik" : `Yerel AI Grafiği (${TIMEFRAME_CONFIG[timeframe].label})`}
                </h3>
                {chartLoading && <RefreshCw size={11} className="text-zinc-500 animate-spin ml-1" />}
              </div>

              <div className="flex items-center gap-2">
                {/* Engine Selector: Local Canvas vs TradingView Pro */}
                <div className="flex bg-zinc-900 border border-zinc-800 rounded-lg p-0.5 text-[10px] font-semibold">
                  <button
                    onClick={() => setChartMode("local")}
                    className={`px-2.5 py-1 rounded-md transition-all cursor-pointer ${
                      chartMode === "local"
                        ? "bg-emerald-500 text-zinc-950 font-bold shadow-sm"
                        : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    📊 BIST Canlı Mum Grafiği (Yerel)
                  </button>
                  <button
                    onClick={() => setChartMode("tradingview")}
                    className={`px-2.5 py-1 rounded-md transition-all cursor-pointer ${
                      chartMode === "tradingview"
                        ? "bg-emerald-500 text-zinc-950 font-bold shadow-sm"
                        : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    ⚡ TradingView Gömülü
                  </button>
                </div>

                {/* Working Interactive Timeframe Switcher (Yerel Modda Aktif) */}
                {chartMode === "local" && (
                  <div className="flex gap-1 text-[10px] font-semibold">
                    {(["1D", "1W", "1M"] as TimeframeType[]).map((tf) => (
                      <button
                        key={tf}
                        onClick={() => setTimeframe(tf)}
                        className={`px-2 py-1 rounded transition-all cursor-pointer ${
                          timeframe === tf
                            ? "bg-emerald-500 text-zinc-950 font-bold shadow-sm"
                            : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
                        }`}
                      >
                        {TIMEFRAME_CONFIG[tf].label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {chartMode === "tradingview" ? (
              <div className="w-full h-[540px] rounded-lg overflow-hidden bg-black/40">
                <TradingViewWidget symbol={activeTicker} height={540} onFallbackToLocal={() => setChartMode("local")} />
              </div>
            ) : (
              <div className="w-full h-[460px] rounded-lg overflow-hidden bg-black/20 p-2">
                <TradingViewChart data={asset?.candles || []} height={440} />
              </div>
            )}

            {/* 10/10 Gelişmiş Mum ve Price Action Zekası Paneli */}
            <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-3">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-2 border-b border-zinc-800/50 pb-2.5">
                <div className="flex items-center gap-2">
                  <Flame size={14} className="text-amber-400" />
                  <span className="text-xs font-bold text-zinc-200 tracking-wide uppercase">
                    Price Action & Mum Formasyon Zekası
                  </span>
                  <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    10/10 AKTİF ANALİZ
                  </span>
                </div>

                {/* Buyer / Seller Pressure Bar */}
                <div className="flex items-center gap-2 text-[10px] font-data">
                  <span className="text-emerald-400 font-bold">Alıcı %{asset.buyer_pressure_pct ?? 50}</span>
                  <div className="w-24 h-1.5 rounded-full bg-red-500/30 overflow-hidden flex">
                    <div
                      className="bg-emerald-400 h-full transition-all duration-500"
                      style={{ width: `${asset.buyer_pressure_pct ?? 50}%` }}
                    />
                  </div>
                  <span className="text-red-400 font-bold">Satıcı %{asset.seller_pressure_pct ?? 50}</span>
                </div>
              </div>

              {/* Formations Badges & Insights */}
              <div className="flex flex-wrap items-center gap-2">
                {(asset.candle_patterns && asset.candle_patterns.length > 0) ? (
                  asset.candle_patterns.map((pat) => (
                    <span
                      key={pat}
                      className="px-2.5 py-1 rounded-lg text-[11px] font-bold font-data bg-amber-500/10 text-amber-300 border border-amber-500/20 flex items-center gap-1.5"
                    >
                      <Zap size={10} className="text-amber-400" />
                      {pat.replace(/_/g, " ")}
                    </span>
                  ))
                ) : (
                  <span className="px-2.5 py-1 rounded-lg text-[11px] font-medium bg-zinc-800/50 text-zinc-400">
                    Normal Dengeli Mum Formasyonu
                  </span>
                )}

                {asset.has_fvg && (
                  <span className="px-2.5 py-1 rounded-lg text-[11px] font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 flex items-center gap-1">
                    <Target size={10} />
                    {asset.fvg_type === "BULLISH_FVG" ? "Boğa FVG (Kurumsal Boşluk)" : "Ayı FVG"}
                  </span>
                )}
              </div>

              {/* Evidence / Reason Text */}
              {asset.candle_evidence && asset.candle_evidence.length > 0 && (
                <p className="text-[11px] text-zinc-400 bg-black/20 p-2.5 rounded-lg border border-white/5">
                  💡 <strong>Mum Okuma İpucu:</strong> {asset.candle_evidence.join(" · ")}
                </p>
              )}
            </div>
          </div>

          {/* Multi-Indicator Cards (Real Calculated Metrics) */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div
              className="rounded-xl p-4 space-y-1.5"
              style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
            >
              <span className="text-[10px] uppercase tracking-widest font-medium text-zinc-500 block">Fiyat / Kazanç (F/K)</span>
              <span className="text-base font-semibold font-data text-emerald-400">{asset.pe_ratio != null ? Number(asset.pe_ratio).toFixed(2) : "—"}x</span>
              <span className="text-[10px] text-zinc-500 block">Sektörel Çarpan</span>
            </div>

            <div
              className="rounded-xl p-4 space-y-1.5"
              style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
            >
              <span className="text-[10px] uppercase tracking-widest font-medium text-zinc-500 block">Piyasa / Defter (PD/DD)</span>
              <span className="text-base font-semibold font-data text-cyan-400">{asset.pb_ratio != null ? Number(asset.pb_ratio).toFixed(2) : "—"}x</span>
              <span className="text-[10px] text-zinc-500 block">Özkaynak Çarpanı</span>
            </div>

            <div
              className="rounded-xl p-4 space-y-1.5"
              style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
            >
              <span className="text-[10px] uppercase tracking-widest font-medium text-zinc-500 block">14 Günlük RSI</span>
              <span className={`text-base font-semibold font-data ${(asset.rsi_14 ?? 50) > 70 ? "text-red-400" : (asset.rsi_14 ?? 50) < 35 ? "text-emerald-400" : "text-zinc-200"}`}>
                {asset.rsi_14 != null ? Number(asset.rsi_14).toFixed(2) : "—"}
              </span>
              <span className="text-[10px] text-zinc-500 block">
                {(asset.rsi_14 ?? 50) > 70 ? "Aşırı Alım Bölgesi" : (asset.rsi_14 ?? 50) < 35 ? "Aşırı Satım (Fırsat)" : "Nötr Momentum"}
              </span>
            </div>

            <div
              className="rounded-xl p-4 space-y-1.5"
              style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
            >
              <span className="text-[10px] uppercase tracking-widest font-medium text-zinc-500 block">Karar Motoru</span>
              <span className="text-base font-semibold font-data text-emerald-400">{asset.recommendation_text || "—"}</span>
              <span className="text-[10px] text-zinc-500 block">Skor: {asset.recommendation_score ?? 0} / 100</span>
            </div>
          </div>

          {/* Technical Moving Averages & Levels */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div
              className="rounded-xl p-4 space-y-2"
              style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
            >
              <span className="text-[10px] uppercase tracking-widest font-medium text-zinc-500 block">Hareketli Ortalamalar</span>
              <div className="space-y-1 text-xs font-data">
                <div className="flex justify-between">
                  <span className="text-zinc-400">20 Günlük SMA:</span>
                  <span className="font-semibold text-zinc-200">₺{asset.sma_20 != null ? Number(asset.sma_20).toFixed(2) : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">50 Günlük SMA:</span>
                  <span className="font-semibold text-zinc-200">₺{asset.sma_50 != null ? Number(asset.sma_50).toFixed(2) : "—"}</span>
                </div>
              </div>
            </div>

            <div
              className="rounded-xl p-4 space-y-2"
              style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
            >
              <span className="text-[10px] uppercase tracking-widest font-medium text-zinc-500 block">Oynaklık & MACD</span>
              <div className="space-y-1 text-xs font-data">
                <div className="flex justify-between">
                  <span className="text-zinc-400">14 Günlük ATR:</span>
                  <span className="font-semibold text-cyan-400">₺{asset.atr_14 != null ? Number(asset.atr_14).toFixed(2) : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">MACD Sinyali:</span>
                  <span className={`font-semibold ${(asset.macd_signal || "AL").includes("AL") ? "text-emerald-400" : "text-amber-400"}`}>
                    {asset.macd_signal || "—"}
                  </span>
                </div>
              </div>
            </div>

            <div
              className="rounded-xl p-4 space-y-2"
              style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
            >
              <span className="text-[10px] uppercase tracking-widest font-medium text-zinc-500 block">Destek / Direnç Kanalı</span>
              <div className="space-y-1 text-xs font-data">
                <div className="flex justify-between">
                  <span className="text-red-400 font-medium">Destek (S1):</span>
                  <span className="font-semibold text-red-400">₺{asset.support != null ? Number(asset.support).toFixed(2) : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-emerald-400 font-medium">Direnç (R1):</span>
                  <span className="font-semibold text-emerald-400">₺{asset.resistance != null ? Number(asset.resistance).toFixed(2) : "—"}</span>
                </div>
              </div>
            </div>
          </div>

          {/* AI Intelligence Live Report Box if generated - Full Height & Rich Typography */}
          {aiReport && (
            <div className="rounded-xl p-5 border border-purple-500/30 bg-purple-950/20 space-y-4 shadow-xl">
              <div className="flex items-center justify-between border-b border-purple-500/20 pb-3">
                <div className="flex items-center gap-2 text-purple-300 text-xs font-bold uppercase tracking-wider">
                  <Sparkles size={16} className="text-purple-400" />
                  Google Gemini 3.7 Flash — {asset.symbol} Canlı İstihbarat Raporu
                </div>
                <button
                  onClick={handleCopyReport}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-purple-500/20 text-purple-200 text-[11px] font-medium border border-purple-500/30 hover:bg-purple-500/30 cursor-pointer transition-all"
                >
                  {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                  {copied ? "Kopyalandı" : "Raporu Kopyala"}
                </button>
              </div>

              <div className="text-xs text-zinc-200 leading-relaxed font-sans bg-black/40 p-5 rounded-lg border border-purple-500/20 whitespace-pre-wrap selection:bg-purple-500/30">
                {aiReport}
              </div>
            </div>
          )}
        </>
      )}
    </div>
    </ErrorBoundary>
  );
}

export default function AssetIntelPage() {
  return (
    <Suspense fallback={<SkeletonChart height={400} />}>
      <AssetIntelContent />
    </Suspense>
  );
}
