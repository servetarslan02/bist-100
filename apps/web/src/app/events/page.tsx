"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Zap, Filter, Clock, ExternalLink, Radio, CheckCircle2,
  TrendingUp, TrendingDown, AlertCircle
} from "lucide-react";

interface EventItem {
  id: string;
  timestamp: string;
  type: "KAP" | "NEWS" | "MACRO" | "SOCIAL";
  source: string;
  title: string;
  ticker?: string;
  sentiment: number;
  importance: number;
}

const EVENT_TYPES = [
  { id: "ALL", label: "Tüm Olaylar" },
  { id: "KAP", label: "KAP Bildirimleri" },
  { id: "NEWS", label: "Haber Akışı (AA/Reuters)" },
  { id: "MACRO", label: "Makro & TCMB" },
  { id: "SOCIAL", label: "Sosyal Medya Radarı" },
];

const MOCK_EVENTS: EventItem[] = [
  { id: "1", timestamp: "14:32:17", type: "KAP", source: "kap.org.tr", title: "THYAO - Yeni uçak alım ve filo genişletme kararı açıklandı", ticker: "THYAO", sentiment: 0.64, importance: 0.88 },
  { id: "2", timestamp: "14:28:05", type: "NEWS", source: "AA Finans", title: "TCMB Para Politikası Kurulu faiz karar metnini yayımladı", sentiment: -0.1, importance: 0.95 },
  { id: "3", timestamp: "14:25:42", type: "MACRO", source: "TÜİK", title: "Tüketici Fiyat Endeksi (TÜFE) aylık %2.4 artış kaydetti", sentiment: -0.3, importance: 0.90 },
  { id: "4", timestamp: "14:21:18", type: "KAP", source: "kap.org.tr", title: "ASELS - Savunma Sanayii Başkanlığı ile 140M $ sözleşme imzalandı", ticker: "ASELS", sentiment: 0.82, importance: 0.85 },
  { id: "5", timestamp: "14:18:33", type: "NEWS", source: "Reuters", title: "BIST Bankacılık Endeksi (XBANK) yabancı alımlarıyla %2 yükseldi", sentiment: 0.55, importance: 0.70 },
  { id: "6", timestamp: "14:15:07", type: "SOCIAL", source: "X Finans", title: "TUPRS rafineri bakım ve marjları hakkında artan sosyal medya ilgisi", ticker: "TUPRS", sentiment: 0.28, importance: 0.45 },
  { id: "7", timestamp: "14:12:44", type: "KAP", source: "kap.org.tr", title: "EREGL - 2. Çeyrek finansal sonuçları ve kâr dağıtım kararı", ticker: "EREGL", sentiment: 0.15, importance: 0.80 },
];

export default function EventCenterPage() {
  const router = useRouter();
  const [filter, setFilter] = useState<string>("ALL");
  const [events] = useState<EventItem[]>(MOCK_EVENTS);

  const filtered = filter === "ALL" ? events : events.filter(e => e.type === filter);

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Olay Merkezi & Anlık Haber Akışı</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            KAP Bildirimleri · AA / Reuters Finans Akışı · TCMB & Makro Veriler · Yapay Zeka Duygu (Sentiment) Analizi
          </p>
        </div>
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold">
          <div className="w-1.5 h-1.5 rounded-full live-dot" />
          CANLI AKIŞ
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-2 select-none">
        {EVENT_TYPES.map((t) => {
          const active = filter === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setFilter(t.id)}
              className="px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all duration-150 cursor-pointer"
              style={{
                background: active ? "rgba(0,229,160,0.12)" : "var(--color-bg-card)",
                border: `1px solid ${active ? "rgba(0,229,160,0.4)" : "var(--color-border-subtle)"}`,
                color: active ? "#00e5a0" : "var(--color-text-secondary)",
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Events List */}
      <div className="space-y-3">
        {filtered.map((ev) => {
          const isKAP = ev.type === "KAP";
          const isPos = ev.sentiment >= 0;
          const badgeClr = isKAP ? "#00e5a0" : ev.type === "MACRO" ? "#ffaa00" : "#00c8ff";

          return (
            <div
              key={ev.id}
              onClick={() => ev.ticker && router.push(`/asset?ticker=${ev.ticker}`)}
              className={`rounded-xl p-4 transition-all duration-150 select-none flex items-start gap-4 ${ev.ticker ? "cursor-pointer hover:bg-white/[0.04] hover:scale-[1.005]" : ""}`}
              style={{
                background: "var(--color-bg-card)",
                border: "1px solid var(--color-border-subtle)",
                borderLeft: `3px solid ${badgeClr}`,
              }}
            >
              <div className="flex-1">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    <span
                      className="text-[9px] font-bold px-2 py-0.5 rounded"
                      style={{ background: `${badgeClr}15`, color: badgeClr }}
                    >
                      {ev.type}
                    </span>
                    {ev.ticker && (
                      <span className="text-[10px] font-bold font-data px-2 py-0.5 rounded bg-zinc-800 text-zinc-200">
                        {ev.ticker}
                      </span>
                    )}
                    <span className="text-[10px] text-zinc-500">{ev.source}</span>
                  </div>
                  <div className="flex items-center gap-3 text-[10px] font-data">
                    <span className="text-zinc-500">{ev.timestamp}</span>
                    <span className="font-bold" style={{ color: isPos ? "#00e5a0" : "#ff4466" }}>
                      Duygu: {isPos ? "+" : ""}%{(ev.sentiment * 100).toFixed(0)}
                    </span>
                  </div>
                </div>

                <h3 className="text-xs font-semibold text-zinc-200 leading-relaxed">{ev.title}</h3>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
