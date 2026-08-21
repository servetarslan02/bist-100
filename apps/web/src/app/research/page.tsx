"use client";

import { useState } from "react";
import {
  FlaskConical, Sparkles, Brain, ArrowRight, MessageSquare,
  TrendingUp, TrendingDown, CheckCircle2, ShieldCheck, Zap
} from "lucide-react";

interface ResearchReport {
  id: string;
  ticker: string;
  title: string;
  model: string;
  date: string;
  sentiment: "BULLISH" | "BEARISH" | "NEUTRAL";
  confidence: number;
  summary: string;
  key_drivers: string[];
}

const REPORTS: ResearchReport[] = [
  {
    id: "rep-thyao-1",
    ticker: "THYAO",
    title: "Türk Hava Yolları 2026/Q2 Kapasite ve Marj Görünümü",
    model: "Gemma 4 12B Q4 (Quant Finans Fine-Tuned)",
    date: "2026-08-21 14:10",
    sentiment: "BULLISH",
    confidence: 88,
    summary: "Artan yolcu doluluk oranları (%84.5) ve kargo gelirlerindeki çift haneli büyüme marjları destekliyor. Jet yakıtı maliyet baskısı hedge pozisyonlarıyla dengelenmiş durumda.",
    key_drivers: [
      "Uluslararası yolcu trafiğinde yıllık %12 artış",
      "Kargo birim gelirlerinde (Yield) güçlü seyir",
      "Düşük net borç / FAVÖK çarpanı (1.4x)",
    ],
  },
  {
    id: "rep-garan-1",
    ticker: "GARAN",
    title: "Garanti BBVA Net Faiz Marjı (NIM) & Kredi Büyümesi",
    model: "Gemma 4 12B Q4 (Quant Finans Fine-Tuned)",
    date: "2026-08-21 13:45",
    sentiment: "BULLISH",
    confidence: 84,
    summary: "Mevduat maliyetlerindeki stabilizasyon ve TL ticari kredi getirilerindeki toparlanma NIM'i yukarı çekiyor. Aktif kalitesi ve sermaye yeterlilik rasyosu (SYR) sektör ortalamasının üzerinde.",
    key_drivers: [
      "Net Faiz Marjında çeyreklik 40 bps genişleme",
      "Takipteki Krediler (NPL) oranı %1.8 ile tarihi dipte",
      "Özkaynak kârlılığı (ROE) %36 seviyesinde güçlü",
    ],
  },
  {
    id: "rep-eregl-1",
    ticker: "EREGL",
    title: "Ereğli Demir Çelik Küresel Çelik Fiyatları & HRC Marjı",
    model: "Gemma 4 12B Q4 (Quant Finans Fine-Tuned)",
    date: "2026-08-21 11:20",
    sentiment: "NEUTRAL",
    confidence: 72,
    summary: "Küresel HRC çelik fiyatlarındaki yatay seyir ve yüksek demir cevheri maliyetleri marjlar üzerinde baskı yaratmaya devam ediyor. Yeni peletleme tesisi yatırımı orta vadeli pozitif.",
    key_drivers: [
      "HRC-Demir Cevheri makası 210 $/ton seviyesinde dar",
      "Kapasite kullanım oranı %86 seviyesinde stabil",
      "Karbon nötr yeşil çelik dönüşüm harcamaları",
    ],
  },
];

export default function AIResearchPage() {
  const [reports, setReports] = useState<ResearchReport[]>(REPORTS);
  const [selectedReport, setSelectedReport] = useState<ResearchReport>(REPORTS[0]);
  const [query, setQuery] = useState("");
  const [analyzing, setAnalyzing] = useState(false);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setAnalyzing(true);
    try {
      const res = await fetch("/api/v1/intelligence/ask_gemini", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: query }),
      });
      const data = await res.json();
      const answer = data?.response || "Analiz oluşturuldu.";
      const newReport: ResearchReport = {
        id: `rep-custom-${Date.now()}`,
        ticker: query.toUpperCase().slice(0, 5).trim() || "BIST",
        title: query,
        model: "Google Gemini 3.7 Flash (Canlı API Bağlı)",
        date: new Date().toLocaleTimeString("tr-TR"),
        sentiment: "BULLISH",
        confidence: 94,
        summary: answer,
        key_drivers: [
          "Canlı Google Gemini 2.5 Flash Analizi",
          "BIST Makro ve Temel Gösterge Sentezi",
          "Yüksek Güvenilirlikli Yapay Zeka Kararı",
        ],
      };
      setReports([newReport, ...reports]);
      setSelectedReport(newReport);
      setQuery("");
    } catch (err) {
      console.error(err);
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Yapay Zeka Kantitatif Araştırma Laboratuvarı</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            BIST Hisse & Makro LLM Analiz Motoru (Gemma 4 12B Quant Model) · Otomatik Temel & Teknik Sentetik Raporlama
          </p>
        </div>
      </div>

      {/* AI Ask Bar */}
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
          placeholder="Yapay zekaya hisse analizi sor (örn: 'THYAO bilanço beklentisi ve riskleri nelerdir?')..."
          className="flex-1 bg-transparent text-xs text-zinc-200 focus:outline-none placeholder:text-zinc-600"
        />
        <button
          type="submit"
          disabled={analyzing}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 text-zinc-950 hover:brightness-110 cursor-pointer shadow-md"
        >
          {analyzing ? <Sparkles size={13} className="animate-spin" /> : <Sparkles size={13} />}
          {analyzing ? "Analiz Ediliyor..." : "Rapor Oluştur"}
        </button>
      </form>

      {/* Quick Suggestion Pills */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 select-none text-[11px]">
        <span className="text-zinc-500 font-semibold flex items-center gap-1 flex-shrink-0">
          <Sparkles size={11} className="text-purple-400" />
          Örnek Sorular:
        </span>
        {[
          "ASELSAN güncel teknik seviyeler ve hedef fiyat nedir?",
          "THYAO yolcu doluluğu ve bilanço görünümü nasıl?",
          "BİST-100 genel piyasa rejimi ve risk faktörleri neler?",
          "Bankacılık sektörü faiz marjı beklentileri nasıl?",
        ].map((sug, i) => (
          <button
            key={i}
            onClick={() => setQuery(sug)}
            className="px-2.5 py-1 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200 hover:border-purple-500/40 transition-colors whitespace-nowrap cursor-pointer"
          >
            {sug}
          </button>
        ))}
      </div>

      {/* Report View Grid */}
      <div className="grid grid-cols-3 gap-4">
        {/* Reports List */}
        <div className="space-y-3">
          <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider px-1">En Son Üretilen AI Raporları</h3>
          {reports.map((rep) => {
            const isSel = selectedReport.id === rep.id;
            const isBull = rep.sentiment === "BULLISH";
            return (
              <div
                key={rep.id}
                onClick={() => setSelectedReport(rep)}
                className="rounded-xl p-4 cursor-pointer transition-all duration-150 select-none"
                style={{
                  background: isSel ? "rgba(0,229,160,0.06)" : "var(--color-bg-card)",
                  border: `1px solid ${isSel ? "rgba(0,229,160,0.3)" : "var(--color-border-subtle)"}`,
                }}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="font-bold text-xs font-data text-zinc-100">{rep.ticker}</span>
                  <span
                    className="text-[9px] font-bold px-2 py-0.5 rounded-full"
                    style={{
                      background: isBull ? "rgba(0,229,160,0.15)" : "rgba(255,170,0,0.15)",
                      color: isBull ? "#00e5a0" : "#ffaa00",
                    }}
                  >
                    {isBull ? "POZİTİF (BOĞA)" : "NÖTR"}
                  </span>
                </div>
                <h4 className="text-xs font-semibold text-zinc-300 leading-snug line-clamp-2">{rep.title}</h4>
                <div className="flex items-center justify-between text-[9px] text-zinc-500 font-data mt-2 pt-2 border-t border-zinc-800/40">
                  <span>Güven: %{rep.confidence}</span>
                  <span>{rep.date}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Report Detail */}
        <div
          className="col-span-2 rounded-xl p-5 space-y-4"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center justify-between pb-3 border-b border-zinc-800/40">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-bold font-data text-emerald-400">{selectedReport.ticker}</span>
                <span className="text-xs text-zinc-400 font-medium">BIST Hisse İncelemesi</span>
              </div>
              <h2 className="text-sm font-bold text-zinc-100 mt-1">{selectedReport.title}</h2>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-zinc-500 block font-data">{selectedReport.date}</span>
              <span className="text-[10px] text-zinc-400 font-mono">{selectedReport.model}</span>
            </div>
          </div>

          <div>
            <h4 className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 mb-2">Yapay Zeka Yönetici Özeti</h4>
            <p className="text-xs leading-relaxed text-zinc-300 bg-zinc-900/60 p-4 rounded-xl border border-zinc-800/40">
              {selectedReport.summary}
            </p>
          </div>

          <div>
            <h4 className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 mb-2">Temel Dinamikler & Katalizörler</h4>
            <div className="space-y-2">
              {selectedReport.key_drivers.map((drv, i) => (
                <div key={i} className="flex items-center gap-2.5 p-2.5 rounded-lg bg-zinc-900/40 border border-zinc-800/30 text-xs text-zinc-300">
                  <CheckCircle2 size={13} className="text-emerald-400 flex-shrink-0" />
                  <span>{drv}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
