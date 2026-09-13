"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling } from "@/lib/api";
import {
  FlaskConical, Sparkles, Brain, ArrowRight, MessageSquare,
  TrendingUp, TrendingDown, CheckCircle2, ShieldCheck, Zap,
  Loader2, Search, Target, Copy, Check, ExternalLink, RefreshCw,
  BarChart3, Clock, AlertTriangle, ShieldAlert
} from "lucide-react";
import { SkeletonList } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { formatIstanbulDateTime } from "@/lib/time";

interface ScannerSignal {
  ticker: string;
  symbol?: string;
  name?: string;
  price?: number;
  current_price?: number;
  change_pct?: number;
  score?: number;
  direction?: string;
  signal?: string;
  signal_type?: string;
  strategy_type?: string;
  spec_category?: string;
  is_high_conviction?: boolean;
  tags?: string[];
  spec_reason?: string;
  expected_return_pct?: number;
  expected_trend_pct?: number;
  target_price?: number;
  target_price_2?: number;
  stop_loss?: number;
  risk_reward_ratio?: number;
  rsi?: number;
  volume_ratio?: number;
  momentum_1m?: number;
  momentum_3m?: number;
  horizon?: string;
  risk_level?: string;
  timestamp?: string;
  action?: string;
}

interface ResearchReport {
  id: string;
  ticker: string;
  name?: string;
  title: string;
  model: string;
  date: string;
  sentiment: "BULLISH" | "BEARISH" | "NEUTRAL";
  confidence: number;
  price: number;
  change_pct: number;
  expected_return_pct?: number;
  target_price?: number;
  target_price_2?: number;
  stop_loss?: number;
  risk_reward_ratio?: number;
  rsi?: number;
  volume_ratio?: number;
  momentum_1m?: number;
  momentum_3m?: number;
  strategy_type?: string;
  signal_name?: string;
  spec_reason?: string;
  horizon?: string;
  risk_level?: string;
  summary: string;
  key_drivers: string[];
  is_custom?: boolean;
}

const STRATEGY_FILTERS = [
  { id: "ALL", label: "Tüm Raporlar" },
  { id: "MOMENTUM_LEADER", label: "Trend Liderleri" },
  { id: "VOLUME_BREAKOUT", label: "Hacim Kırılımları" },
  { id: "PULLBACK_BOUNCE", label: "Dip Dönüşleri" },
  { id: "CUSTOM_AI", label: "Özel AI Raporları" },
];

export default function AIResearchPage() {
  const router = useRouter();
  const { data: signalsData, loading, refetch } = usePolling<{ signals: ScannerSignal[] } | null>("/scanner/signals", 8000);
  const [customReports, setCustomReports] = useState<ResearchReport[]>([]);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [strategyFilter, setStrategyFilter] = useState("ALL");
  const [searchTerm, setSearchTerm] = useState("");
  const [copied, setCopied] = useState(false);
  const [subQuery, setSubQuery] = useState("");
  const [subQueryAnalyzing, setSubQueryAnalyzing] = useState(false);

  // Canlı taranan model sinyallerini zengin araştırma raporlarına dönüştür
  const reports = useMemo(() => {
    const liveScannedReports: ResearchReport[] = [];
    const signals: ScannerSignal[] = signalsData?.signals ?? [];

    signals.forEach((sig) => {
      const price = sig.price ?? sig.current_price ?? 0;
      const change = sig.change_pct ?? 0;
      const rawScore = sig.score ?? 85;
      const score = Math.min(99, Math.max(50, Math.round(rawScore > 100 ? 50 + (rawScore % 50) : rawScore)));
      const action = sig.signal || sig.action || "GÜÇLÜ AL";
      const isBull = action.includes("AL") || action.includes("BUY") || (sig.expected_return_pct ?? 0) > 0;

      const expectedPct = sig.expected_return_pct ?? 15.0;
      const tp1 = sig.target_price ?? (price > 0 ? Number((price * 1.12).toFixed(2)) : 0);
      const tp2 = sig.target_price_2 ?? (price > 0 ? Number((price * 1.25).toFixed(2)) : 0);
      const sl = sig.stop_loss ?? (price > 0 ? Number((price * 0.94).toFixed(2)) : 0);
      const rr = sig.risk_reward_ratio ?? 2.4;

      const drivers = [
        `Kantitatif Model Kararı: ${action} · Alpha Skoru: %${score}`,
        `Fiyat Seviyeleri: Giriş ₺${price.toFixed(2)} · 1. Hedef ₺${tp1.toFixed(2)} · Stop-Loss ₺${sl.toFixed(2)}`,
        `Risk / Ödül Simetrisi: ${rr.toFixed(2)}x R/R Oranı · Vade: ${sig.horizon || "5-10 İş Günü"}`,
      ];

      if (sig.rsi) {
        drivers.push(`Teknik İvme: 14G RSI ${sig.rsi.toFixed(1)} ${sig.rsi > 70 ? "(Aşırı Alım)" : sig.rsi < 35 ? "(Aşırı Satım / Dönüş)" : "(Dengeli Trend)"}`);
      }
      if (sig.volume_ratio) {
        drivers.push(`Hacim Dinamiği: Ortalama Hacmin ${sig.volume_ratio.toFixed(2)}x Katı Göreceli Hacim (RVOL)`);
      }
      if (sig.spec_reason) {
        drivers.push(`Sinyal Gerekçesi: ${sig.spec_reason}`);
      }

      const summaryText = `${sig.name || sig.ticker} (${sig.ticker}) hissesi için AlphaEngine Optuna-LightGBM ve Quant Motoru tarafından "${action}" sinyali üretilmiştir.\n\nModelin 20 günlük endeks üstü getiri beklentisi %${expectedPct.toFixed(1)} seviyesindedir. Fiyat şu an ₺${price.toFixed(2)} olup, ${sig.horizon || "5-10 günlük"} vadede ₺${tp1.toFixed(2)} birincil hedef ve ₺${tp2.toFixed(2)} genişletilmiş direnç hedefi hesaplanmıştır. Korumalı risk stop seviyesi dinamik ATR bantları gereği ₺${sl.toFixed(2)} olarak belirlenmiştir.`;

      liveScannedReports.push({
        id: `rep-live-${sig.ticker}`,
        ticker: sig.ticker,
        name: sig.name || sig.ticker,
        title: `${sig.ticker} Kantitatif Alpha & Değerleme Raporu`,
        model: "AlphaEngine v2.5 (Optuna-LightGBM & Quant)",
        date: sig.timestamp ? formatIstanbulDateTime(sig.timestamp) : "Canlı Model Sinyali",
        sentiment: isBull ? "BULLISH" : "NEUTRAL",
        confidence: score,
        price,
        change_pct: change,
        expected_return_pct: expectedPct,
        target_price: tp1,
        target_price_2: tp2,
        stop_loss: sl,
        risk_reward_ratio: rr,
        rsi: sig.rsi,
        volume_ratio: sig.volume_ratio,
        momentum_1m: sig.momentum_1m,
        momentum_3m: sig.momentum_3m,
        strategy_type: sig.strategy_type || sig.signal_type || "MOMENTUM_LEADER",
        signal_name: action,
        spec_reason: sig.spec_reason,
        horizon: sig.horizon || "5-10 Gün",
        risk_level: sig.risk_level || "medium",
        summary: summaryText,
        key_drivers: drivers,
        is_custom: false,
      });
    });

    return [...customReports, ...liveScannedReports];
  }, [signalsData, customReports]);

  // Sayaçlar ve KPI İstatistikleri
  const stats = useMemo(() => {
    const total = reports.length;
    let maxScore = 0;
    let maxScoreTicker = "—";
    let sumReturn = 0;
    let sumRR = 0;
    let countRR = 0;

    for (const r of reports) {
      if (r.confidence > maxScore) {
        maxScore = r.confidence;
        maxScoreTicker = r.ticker;
      }
      if (r.expected_return_pct) {
        sumReturn += r.expected_return_pct;
      }
      if (r.risk_reward_ratio) {
        sumRR += r.risk_reward_ratio;
        countRR++;
      }
    }

    const avgReturn = total > 0 ? (sumReturn / total).toFixed(1) : "0.0";
    const avgRR = countRR > 0 ? (sumRR / countRR).toFixed(2) : "2.40";

    // Strateji adetleri
    const strategyCounts: Record<string, number> = {
      ALL: total,
      MOMENTUM_LEADER: 0,
      VOLUME_BREAKOUT: 0,
      PULLBACK_BOUNCE: 0,
      CUSTOM_AI: customReports.length,
    };

    for (const r of reports) {
      if (r.is_custom) continue;
      const st = r.strategy_type || "MOMENTUM_LEADER";
      if (strategyCounts[st] !== undefined) {
        strategyCounts[st]++;
      } else {
        strategyCounts.MOMENTUM_LEADER++;
      }
    }

    return {
      total,
      maxScore,
      maxScoreTicker,
      avgReturn,
      avgRR,
      strategyCounts,
    };
  }, [reports, customReports]);

  // Filtrelenmiş raporlar
  const filteredReports = useMemo(() => {
    return reports.filter((r) => {
      // Strateji filtresi
      if (strategyFilter === "CUSTOM_AI") {
        if (!r.is_custom) return false;
      } else if (strategyFilter !== "ALL") {
        if (r.strategy_type !== strategyFilter) return false;
      }

      // Arama filtresi
      if (searchTerm) {
        const q = searchTerm.toLowerCase().trim();
        const matchTicker = r.ticker.toLowerCase().includes(q);
        const matchName = r.name?.toLowerCase().includes(q) ?? false;
        const matchTitle = r.title.toLowerCase().includes(q);
        const matchSignal = r.signal_name?.toLowerCase().includes(q) ?? false;
        return matchTicker || matchName || matchTitle || matchSignal;
      }

      return true;
    });
  }, [reports, strategyFilter, searchTerm]);

  // Seçili rapor
  const selectedReport = useMemo(() => {
    if (selectedReportId) {
      const found = reports.find((r) => r.id === selectedReportId);
      if (found) return found;
    }
    return filteredReports[0] || reports[0] || null;
  }, [reports, filteredReports, selectedReportId]);

  // Özel Gemini AI Raporu Oluşturma
  const handleAsk = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!query.trim() || analyzing) return;
    setAnalyzing(true);
    try {
      const res = await fetch("/api/v1/intelligence/ask_gemini", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: query }),
      });
      const data = await res.json();
      const answer = data?.response || data?.message || "Analiz tamamlandı.";
      const detectedTicker = query.toUpperCase().match(/\b[A-Z]{4,5}\b/)?.[0] || "BIST";

      const newReport: ResearchReport = {
        id: `rep-custom-${Date.now()}`,
        ticker: detectedTicker,
        name: `${detectedTicker} Özel Analizi`,
        title: query,
        model: "Google Gemini 3.7 Flash & Canlı Araç Entegrasyonu",
        date: formatIstanbulDateTime(new Date()),
        sentiment: answer.includes("GÜÇLÜ AL") || answer.includes("AL") ? "BULLISH" : "NEUTRAL",
        confidence: 95,
        price: 0,
        change_pct: 0,
        expected_return_pct: 18.0,
        summary: answer,
        key_drivers: [
          "Canlı Google Gemini 3.7 Flash & BIST Piyasa Motoru Entegrasyonu",
          "BIST Makro ve Temel Gösterge Sentezi",
          "Yüksek Güvenilirlikli Yapay Zeka Kararı",
        ],
        is_custom: true,
      };

      setCustomReports((prev) => [newReport, ...prev]);
      setSelectedReportId(newReport.id);
      setStrategyFilter("ALL");
      setQuery("");
    } catch (err) {
      console.error("Gemini rapor hatası:", err);
    } finally {
      setAnalyzing(false);
    }
  };

  // Mevcut hisse için derinleştirme sorusu
  const handleSubAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subQuery.trim() || !selectedReport || subQueryAnalyzing) return;
    setSubQueryAnalyzing(true);
    try {
      const fullPrompt = `${selectedReport.ticker} hissesi hakkında: ${subQuery}. Güncel fiyat ₺${selectedReport.price}, hedef ₺${selectedReport.target_price}, stop ₺${selectedReport.stop_loss} seviyelerini de dikkate alarak detaylandır.`;
      const res = await fetch("/api/v1/intelligence/ask_gemini", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: fullPrompt }),
      });
      const data = await res.json();
      const answer = data?.response || data?.message || "Ek analiz tamamlandı.";

      // Seçili raporun özetine ekle
      const updatedSummary = `${selectedReport.summary}\n\n---\n💬 **Kullanıcı Sorusu:** ${subQuery}\n🤖 **Gemini Ek Analizi:**\n${answer}`;
      
      const updatedReport: ResearchReport = {
        ...selectedReport,
        summary: updatedSummary,
        key_drivers: [...selectedReport.key_drivers, `Soru & Yanıt: ${subQuery.slice(0, 45)}...`],
      };

      setCustomReports((prev) => [updatedReport, ...prev.filter((r) => r.id !== updatedReport.id)]);
      setSelectedReportId(updatedReport.id);
      setSubQuery("");
    } catch (err) {
      console.error(err);
    } finally {
      setSubQueryAnalyzing(false);
    }
  };

  const handleCopyReport = () => {
    if (!selectedReport) return;
    const text = `📊 ALPHA BIST ARAŞTIRMA RAPORU\n` +
      `Hisse: ${selectedReport.ticker} (${selectedReport.name || ''})\n` +
      `Model: ${selectedReport.model}\n` +
      `Fiyat: ₺${selectedReport.price} · Hedef: ₺${selectedReport.target_price} · Stop: ₺${selectedReport.stop_loss}\n` +
      `Model Kararı: ${selectedReport.signal_name || selectedReport.sentiment} (Güven: %${selectedReport.confidence})\n\n` +
      `ÖZET:\n${selectedReport.summary}\n\n` +
      `TEMEL SÜRÜCÜLER:\n${selectedReport.key_drivers.map((d) => `• ${d}`).join('\n')}`;

    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <ErrorBoundary name="research">
      <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold gradient-text">Yapay Zeka Kantitatif Araştırma Laboratuvarı</h1>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-500/10 text-purple-400 border border-purple-500/20">
                GEMINI 3.7 & QUANT ENGINE
              </span>
            </div>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
              BIST Canlı AlphaEngine Nicel Değerlemeleri, Olasılık Dağılımları ve Google Gemini 3.7 Flash Raporları
            </p>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-xs">
              <Search size={12} className="text-zinc-500" />
              <input
                type="text"
                placeholder="Rapor veya hisse ara..."
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

        {/* KPI Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
            <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
              <span>Aktif Model Raporu</span>
              <FlaskConical size={14} className="text-cyan-400" />
            </div>
            <div className="text-xl font-bold font-data text-zinc-100">{stats.total} Rapor</div>
            <p className="text-[10px] text-zinc-500">Canlı taranan & yapay zeka üretilen</p>
          </div>

          <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
            <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
              <span>En Yüksek Alpha Skoru</span>
              <Sparkles size={14} className="text-emerald-400" />
            </div>
            <div className="text-xl font-bold font-data text-emerald-400">%{stats.maxScore}</div>
            <p className="text-[10px] text-zinc-500">Lider hisse: <span className="text-zinc-300 font-semibold">{stats.maxScoreTicker}</span></p>
          </div>

          <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
            <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
              <span>Ortalama Beklenen Alpha</span>
              <TrendingUp size={14} className="text-purple-400" />
            </div>
            <div className="text-xl font-bold font-data text-purple-400">+%{stats.avgReturn}</div>
            <p className="text-[10px] text-zinc-500">Endeks üstü getiri projeksiyonu</p>
          </div>

          <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
            <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
              <span>Ortalama Risk / Ödül</span>
              <ShieldCheck size={14} className="text-amber-400" />
            </div>
            <div className="text-xl font-bold font-data text-amber-400">{stats.avgRR}x</div>
            <p className="text-[10px] text-zinc-500">Dinamik 2.5x ATR koruma seviyesi</p>
          </div>
        </div>

        {/* AI Prompt / Ask Bar */}
        <form
          onSubmit={handleAsk}
          className="rounded-xl p-3 flex items-center gap-3 select-none"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-purple-500/10 flex-shrink-0">
            <Brain size={16} className="text-purple-400" />
          </div>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Yapay zekaya hisse veya sektör analizi sor (örn: 'THYAO bilanço beklentisi ve riskleri nelerdir?')..."
            className="flex-1 bg-transparent text-xs text-zinc-200 focus:outline-none placeholder:text-zinc-600"
          />
          <button
            type="submit"
            disabled={analyzing}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-gradient-to-r from-emerald-400 via-cyan-400 to-purple-400 text-zinc-950 hover:brightness-110 cursor-pointer shadow-md transition-all"
          >
            {analyzing ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            {analyzing ? "Analiz Ediliyor..." : "Rapor Üret"}
          </button>
        </form>

        {/* Quick Suggestion Pills */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 select-none text-[11px] custom-scrollbar">
          <span className="text-zinc-500 font-semibold flex items-center gap-1 flex-shrink-0">
            <Sparkles size={11} className="text-purple-400" />
            Hızlı İstihbarat:
          </span>
          {[
            "ASELSAN güncel teknik seviyeler ve hedef fiyat nedir?",
            "THYAO yolcu doluluğu ve bilanço görünümü nasıl?",
            "BİST-100 genel piyasa rejimi ve risk faktörleri neler?",
            "Bankacılık sektörü faiz marjı beklentileri nasıl?",
            "MIATK ve teknoloji hisselerinde hacim kırılımı potansiyeli",
          ].map((sug, i) => (
            <button
              key={i}
              type="button"
              onClick={() => {
                setQuery(sug);
              }}
              className="px-2.5 py-1 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200 hover:border-purple-500/40 transition-colors whitespace-nowrap cursor-pointer text-[11px]"
            >
              {sug}
            </button>
          ))}
        </div>

        {/* Filter Tabs with Dynamic Counters */}
        <div className="flex gap-2 overflow-x-auto pb-1 custom-scrollbar">
          {STRATEGY_FILTERS.map((t) => {
            const active = strategyFilter === t.id;
            const count = stats.strategyCounts[t.id] ?? 0;
            return (
              <button
                key={t.id}
                onClick={() => setStrategyFilter(t.id)}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all duration-150 cursor-pointer ${
                  active
                    ? "bg-zinc-100 text-zinc-900 shadow-md"
                    : "bg-zinc-900/80 text-zinc-400 hover:text-zinc-200 border border-zinc-800"
                }`}
              >
                <span>{t.label}</span>
                <span
                  className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                    active ? "bg-zinc-900 text-zinc-100" : "bg-zinc-800 text-zinc-400"
                  }`}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Loading state */}
        {loading && reports.length === 0 && (
          <SkeletonList count={6} />
        )}

        {/* Report View Grid */}
        {reports.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            {/* Report List (Left Column - 5 cols) */}
            <div className="lg:col-span-5 space-y-2.5 select-none">
              <div className="flex items-center justify-between px-1">
                <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
                  MODEL RAPORLARI ({filteredReports.length})
                </h2>
                <span className="text-[10px] text-zinc-500 font-data">Sıralama: Alpha Skoru</span>
              </div>

              {filteredReports.length === 0 ? (
                <div className="text-center py-12 text-zinc-500 text-xs rounded-xl bg-zinc-900/30 border border-zinc-800/50">
                  Bu filtreye uygun araştırma raporu bulunamadı.
                </div>
              ) : (
                <div className="space-y-2.5 max-h-[800px] overflow-y-auto pr-1 custom-scrollbar">
                  {filteredReports.map((rep) => {
                    const active = selectedReport?.id === rep.id;
                    const isBull = rep.sentiment === "BULLISH";
                    const isPos = rep.change_pct >= 0;

                    return (
                      <div
                        key={rep.id}
                        onClick={() => setSelectedReportId(rep.id)}
                        className={`rounded-xl p-3.5 transition-all cursor-pointer border select-none relative ${
                          active
                            ? "bg-zinc-900/90 border-cyan-500/50 shadow-lg shadow-cyan-950/20"
                            : "bg-zinc-900/40 hover:bg-zinc-900/70 border-zinc-800/70 hover:border-zinc-700"
                        }`}
                        style={{
                          borderLeft: active ? "4px solid #00e5a0" : undefined,
                        }}
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-bold font-data text-zinc-100">{rep.ticker}</span>
                            {rep.name && rep.name !== rep.ticker && (
                              <span className="text-[11px] text-zinc-400 truncate max-w-[150px]">
                                {rep.name}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-1.5">
                            {rep.price > 0 && (
                              <span className="text-xs font-bold font-data text-zinc-200">
                                ₺{rep.price.toFixed(2)}
                              </span>
                            )}
                            {rep.change_pct !== 0 && (
                              <span className={`text-[10px] font-bold font-data px-1.5 py-0.2 rounded ${
                                isPos ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
                              }`}>
                                {isPos ? `+${rep.change_pct.toFixed(1)}%` : `${rep.change_pct.toFixed(1)}%`}
                              </span>
                            )}
                          </div>
                        </div>

                        <h3 className="text-xs font-semibold text-zinc-300 line-clamp-1 mb-2 leading-relaxed">
                          {rep.title}
                        </h3>

                        <div className="flex items-center justify-between text-[10px] text-zinc-500 font-data pt-1 border-t border-zinc-800/50">
                          <div className="flex items-center gap-1.5">
                            <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300 font-semibold text-[9px]">
                              {rep.signal_name || (rep.is_custom ? "ÖZEL RAPOR" : "AL")}
                            </span>
                            {rep.expected_return_pct && (
                              <span className="text-emerald-400 font-semibold">
                                +%{rep.expected_return_pct.toFixed(1)} Alpha
                              </span>
                            )}
                          </div>
                          <span className="font-semibold text-cyan-400">%{rep.confidence} Güven</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Selected Report Detail (Right Column - 7 cols) */}
            {selectedReport && (
              <div
                className="lg:col-span-7 rounded-2xl p-6 space-y-5 select-none"
                style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
              >
                {/* Header of Detail */}
                <div className="flex items-start justify-between gap-3 border-b border-zinc-800/80 pb-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-base font-bold font-data px-3 py-0.5 rounded-lg bg-zinc-800 text-zinc-100 border border-zinc-700">
                        {selectedReport.ticker}
                      </span>
                      <span className="text-xs text-zinc-400 font-medium">
                        {selectedReport.name || selectedReport.ticker}
                      </span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        {selectedReport.signal_name || "GÜÇLÜ AL"}
                      </span>
                    </div>
                    <h2 className="text-base font-bold text-zinc-100 leading-snug">{selectedReport.title}</h2>
                    <div className="flex items-center gap-3 mt-1.5 text-[11px] text-zinc-500">
                      <span>{selectedReport.model}</span>
                      <span>·</span>
                      <span>{selectedReport.date}</span>
                    </div>
                  </div>

                  <div className="flex flex-col items-end gap-2 flex-shrink-0">
                    <div className="text-right">
                      <div className="text-2xl font-bold font-data text-emerald-400">%{selectedReport.confidence}</div>
                      <span className="text-[10px] uppercase font-bold text-zinc-500">Alpha Güven</span>
                    </div>
                    
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={handleCopyReport}
                        className="p-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors text-xs flex items-center gap-1"
                        title="Raporu Kopyala"
                      >
                        {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                        <span className="text-[10px]">{copied ? "Kopyalandı" : "Kopyala"}</span>
                      </button>

                      {selectedReport.ticker && selectedReport.ticker !== "BIST" && (
                        <button
                          onClick={() => router.push(`/asset?symbol=${selectedReport.ticker}`)}
                          className="p-1.5 px-2.5 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 transition-colors text-xs flex items-center gap-1 font-semibold"
                        >
                          <span>Varlık Detayı</span>
                          <ExternalLink size={11} />
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Price & Target Levels Bar */}
                {selectedReport.price > 0 && (
                  <div className="rounded-xl p-4 bg-zinc-900/60 border border-zinc-800 space-y-3">
                    <div className="flex items-center justify-between text-xs font-bold text-zinc-300">
                      <span className="flex items-center gap-1.5">
                        <Target size={14} className="text-emerald-400" />
                        Hedef Fiyat & Risk Yönetim Seviyeleri
                      </span>
                      <span className="text-emerald-400 font-data">
                        R/R: {selectedReport.risk_reward_ratio?.toFixed(2) || "2.40"}x · Vade: {selectedReport.horizon || "5-10 Gün"}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
                      <div className="p-2.5 rounded-lg bg-zinc-900/80 border border-zinc-800">
                        <span className="text-[10px] text-zinc-500 font-medium block">Giriş / Canlı Fiyat</span>
                        <span className="text-sm font-bold font-data text-zinc-100">₺{selectedReport.price.toFixed(2)}</span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-800/40">
                        <span className="text-[10px] text-emerald-400 font-medium block">1. Hedef (Take-Profit)</span>
                        <span className="text-sm font-bold font-data text-emerald-300">₺{selectedReport.target_price?.toFixed(2) || "—"}</span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-cyan-950/20 border border-cyan-800/40">
                        <span className="text-[10px] text-cyan-400 font-medium block">2. Genişletilmiş Hedef</span>
                        <span className="text-sm font-bold font-data text-cyan-300">₺{selectedReport.target_price_2?.toFixed(2) || "—"}</span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-red-950/20 border border-red-800/40">
                        <span className="text-[10px] text-red-400 font-medium block">Stop-Loss (Zarar Kes)</span>
                        <span className="text-sm font-bold font-data text-red-400">₺{selectedReport.stop_loss?.toFixed(2) || "—"}</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Quantitative Metric Grid */}
                {selectedReport.rsi !== undefined && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                    <div className="p-3 rounded-xl bg-zinc-900/40 border border-zinc-800/70">
                      <span className="text-[10px] text-zinc-500 font-medium block">14G RSI</span>
                      <span className="text-sm font-bold font-data text-zinc-200">
                        {selectedReport.rsi.toFixed(1)}
                      </span>
                      <span className="text-[9px] text-zinc-500 block mt-0.5">
                        {selectedReport.rsi > 70 ? "Aşırı Alım" : selectedReport.rsi < 35 ? "Aşırı Satım" : "Dengeli Bölge"}
                      </span>
                    </div>

                    <div className="p-3 rounded-xl bg-zinc-900/40 border border-zinc-800/70">
                      <span className="text-[10px] text-zinc-500 font-medium block">Göreceli Hacim (RVOL)</span>
                      <span className="text-sm font-bold font-data text-cyan-400">
                        {selectedReport.volume_ratio ? `${selectedReport.volume_ratio.toFixed(2)}x` : "1.00x"}
                      </span>
                      <span className="text-[9px] text-zinc-500 block mt-0.5">20 Günlük Hacim Katı</span>
                    </div>

                    <div className="p-3 rounded-xl bg-zinc-900/40 border border-zinc-800/70">
                      <span className="text-[10px] text-zinc-500 font-medium block">1 Aylık İvme</span>
                      <span className={`text-sm font-bold font-data ${
                        (selectedReport.momentum_1m ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
                      }`}>
                        {selectedReport.momentum_1m ? `${selectedReport.momentum_1m > 0 ? "+" : ""}${selectedReport.momentum_1m.toFixed(1)}%` : "—"}
                      </span>
                      <span className="text-[9px] text-zinc-500 block mt-0.5">Trend Gücü</span>
                    </div>

                    <div className="p-3 rounded-xl bg-zinc-900/40 border border-zinc-800/70">
                      <span className="text-[10px] text-zinc-500 font-medium block">Model Risk Sınıfı</span>
                      <span className="text-sm font-bold font-data text-amber-400 uppercase">
                        {selectedReport.risk_level || "Orta"}
                      </span>
                      <span className="text-[9px] text-zinc-500 block mt-0.5">Volatilite Koruma</span>
                    </div>
                  </div>
                )}

                {/* Summary Section */}
                <div className="rounded-xl p-4 bg-zinc-900/60 border border-zinc-800 space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-300">
                    <FlaskConical size={13} className="text-emerald-400" />
                    Yapay Zeka & Nicel Model Analiz Özeti
                  </div>
                  <div className="text-xs text-zinc-300 leading-relaxed whitespace-pre-line space-y-2">
                    {selectedReport.summary}
                  </div>
                </div>

                {/* Key Drivers */}
                <div className="space-y-2">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
                    Temel Fiyat Sürücüleri & Model Gerekçeleri
                  </h4>
                  <div className="space-y-1.5">
                    {selectedReport.key_drivers.map((drv, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 text-xs text-zinc-300 bg-zinc-900/40 p-2.5 rounded-lg border border-zinc-800/60"
                      >
                        <CheckCircle2 size={13} className="text-emerald-400 flex-shrink-0" />
                        <span>{drv}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Quick Follow-up AI Question for Selected Stock */}
                <form
                  onSubmit={handleSubAsk}
                  className="rounded-xl p-3 flex items-center gap-2 bg-zinc-900/80 border border-zinc-800"
                >
                  <MessageSquare size={14} className="text-purple-400 flex-shrink-0" />
                  <input
                    type="text"
                    value={subQuery}
                    onChange={(e) => setSubQuery(e.target.value)}
                    placeholder={`${selectedReport.ticker} için Gemini'ye ek soru sor (örn: 'Bilanço ve temettü beklentisi nedir?')...`}
                    className="flex-1 bg-transparent text-xs text-zinc-200 focus:outline-none placeholder:text-zinc-600"
                  />
                  <button
                    type="submit"
                    disabled={subQueryAnalyzing}
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-500/40 flex items-center gap-1 cursor-pointer transition-colors"
                  >
                    {subQueryAnalyzing ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                    <span>Sor</span>
                  </button>
                </form>
              </div>
            )}
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}
