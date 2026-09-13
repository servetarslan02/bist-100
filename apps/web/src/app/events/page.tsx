"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling } from "@/lib/api";
import {
  Zap, Filter, Clock, ExternalLink, Radio, CheckCircle2,
  TrendingUp, TrendingDown, AlertCircle, Loader2, Search, RefreshCw
} from "lucide-react";
import { SkeletonList, SkeletonCard, SkeletonTable, SkeletonChart } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { formatIstanbulTime } from "@/lib/time";

interface EventItem {
  id: string;
  timestamp: string;
  type: "KAP" | "NEWS" | "MACRO" | "SOCIAL";
  source: string;
  title: string;
  ticker?: string;
  sentiment: number;
  importance: number;
  link?: string;
}

const EVENT_TYPES = [
  { id: "ALL", label: "Tüm Olaylar", icon: Zap },
  { id: "KAP", label: "KAP Bildirimleri", icon: AlertCircle, color: "#00e5a0" },
  { id: "NEWS", label: "Haber Akışı", icon: Radio, color: "#00c8ff" },
  { id: "MACRO", label: "Makro & TCMB", icon: TrendingUp, color: "#ffaa00" },
];

export default function EventCenterPage() {
  const router = useRouter();
  const [filter, setFilter] = useState<string>("ALL");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const { data: eventsData, loading, lastUpdated, refetch } = usePolling<{ events: EventItem[]; count: number }>("/event-study/events", 4000);

  const events = useMemo(() => eventsData?.events ?? [], [eventsData]);

  // Sayaçlar & İstatistikler
  const counts = useMemo(() => {
    const c = { ALL: events.length, KAP: 0, NEWS: 0, MACRO: 0 };
    let positiveCount = 0;
    let negativeCount = 0;

    for (const ev of events) {
      if (ev.type === "KAP") c.KAP++;
      else if (ev.type === "MACRO") c.MACRO++;
      else c.NEWS++;

      if (ev.sentiment > 0.1) positiveCount++;
      else if (ev.sentiment < -0.1) negativeCount++;
    }

    const netSentiment = events.length > 0
      ? Math.round(((positiveCount - negativeCount) / events.length) * 100)
      : 0;

    return { ...c, positiveCount, negativeCount, netSentiment };
  }, [events]);

  const filtered = useMemo(() => {
    let list = filter === "ALL" ? events : events.filter(e => e.type === filter);
    if (searchTerm) {
      const q = searchTerm.toLowerCase().trim();
      list = list.filter(e =>
        e.title.toLowerCase().includes(q) ||
        (e.ticker && e.ticker.toLowerCase().includes(q)) ||
        e.source.toLowerCase().includes(q)
      );
    }
    return list;
  }, [filter, events, searchTerm]);

  return (
    <ErrorBoundary name="events">
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold gradient-text">Olay Merkezi & Canlı Haber Akışı</h1>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              CANLI RSS & KAP
            </span>
          </div>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Kamuyu Aydınlatma Platformu (KAP) · BloombergHT · Investing.com · Dünya Gazetesi · TCMB Takvimi
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-xs">
            <Search size={12} className="text-zinc-500" />
            <input
              type="text"
              placeholder="Haber veya hisse ara..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-transparent text-zinc-200 focus:outline-none w-36 text-xs"
            />
          </div>

          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-emerald-400 text-xs font-semibold">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
            <span>4s Canlı</span>
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
            <span>Toplam Akış</span>
            <Zap size={14} className="text-cyan-400" />
          </div>
          <div className="text-xl font-bold font-data text-zinc-100">{counts.ALL} Olay</div>
          <p className="text-[10px] text-zinc-500">Son 24 saat içinde toplanan</p>
        </div>

        <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
          <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
            <span>KAP Bildirimleri</span>
            <AlertCircle size={14} className="text-emerald-400" />
          </div>
          <div className="text-xl font-bold font-data text-emerald-400">{counts.KAP} Bildirim</div>
          <p className="text-[10px] text-zinc-500">Şirket & BIST açıklamaları</p>
        </div>

        <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
          <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
            <span>Makro & Finans</span>
            <Radio size={14} className="text-amber-400" />
          </div>
          <div className="text-xl font-bold font-data text-amber-400">{counts.MACRO + counts.NEWS} Haber</div>
          <p className="text-[10px] text-zinc-500">TCMB, faiz ve piyasa analizi</p>
        </div>

        <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 space-y-1">
          <div className="flex items-center justify-between text-zinc-400 text-xs font-medium">
            <span>Net Piyasa Duygusu</span>
            <TrendingUp size={14} className={counts.netSentiment >= 0 ? "text-emerald-400" : "text-red-400"} />
          </div>
          <div className={`text-xl font-bold font-data ${counts.netSentiment >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {counts.netSentiment >= 0 ? `+${counts.netSentiment}%` : `${counts.netSentiment}%`}
          </div>
          <p className="text-[10px] text-zinc-500">Pozitif: {counts.positiveCount} · Negatif: {counts.negativeCount}</p>
        </div>
      </div>

      {/* Filter Tabs with Dynamic Counters */}
      <div className="flex gap-2 overflow-x-auto pb-1 custom-scrollbar">
        {EVENT_TYPES.map((t) => {
          const active = filter === t.id;
          const count = counts[t.id as keyof typeof counts] ?? 0;
          return (
            <button
              key={t.id}
              onClick={() => setFilter(t.id)}
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
      {loading && events.length === 0 && (
        <SkeletonList count={6} />
      )}

      {/* Events List */}
      {filtered.length === 0 && !loading ? (
        <div className="text-center py-16 text-zinc-500 text-xs rounded-xl bg-zinc-900/30 border border-zinc-800/50">
          Bu filtreye uygun güncel haber veya KAP bildirimi bulunamadı.
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((ev) => {
            const isKAP = ev.type === "KAP";
            const isPos = ev.sentiment > 0.05;
            const isNeg = ev.sentiment < -0.05;
            const badgeClr = isKAP ? "#00e5a0" : ev.type === "MACRO" ? "#ffaa00" : "#00c8ff";

            return (
              <div
                key={ev.id}
                className="rounded-xl p-4 transition-all duration-150 flex items-start gap-4 group bg-zinc-900/50 hover:bg-zinc-900/80 border border-zinc-800/80 hover:border-zinc-700"
                style={{
                  borderLeft: `3px solid ${badgeClr}`,
                }}
              >
                <div className="flex-1 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span
                        className="text-[9px] font-bold px-2 py-0.5 rounded uppercase tracking-wider"
                        style={{ background: `${badgeClr}15`, color: badgeClr }}
                      >
                        {ev.type}
                      </span>
                      {ev.ticker && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            router.push(`/asset?symbol=${ev.ticker}`);
                          }}
                          className="text-[10px] font-bold font-data px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-cyan-400 transition-colors flex items-center gap-1"
                        >
                          <span>{ev.ticker}</span>
                        </button>
                      )}
                      <span className="text-[11px] text-zinc-400 font-medium">{ev.source}</span>
                    </div>

                    <div className="flex items-center gap-3 text-[10px] font-data">
                      <span className="text-zinc-500">{ev.timestamp}</span>
                      <span
                        className={`font-bold px-2 py-0.5 rounded ${
                          isPos
                            ? "bg-emerald-500/10 text-emerald-400"
                            : isNeg
                            ? "bg-red-500/10 text-red-400"
                            : "bg-zinc-800 text-zinc-400"
                        }`}
                      >
                        {isPos ? `+${(ev.sentiment * 100).toFixed(0)}%` : isNeg ? `${(ev.sentiment * 100).toFixed(0)}%` : "Nötr"}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-start justify-between gap-4">
                    <h3 className="text-xs font-semibold text-zinc-200 leading-relaxed group-hover:text-zinc-100">
                      {ev.title}
                    </h3>
                    {ev.link && (
                      <a
                        href={ev.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 rounded-lg bg-zinc-950/40 hover:bg-zinc-800 border border-zinc-800/60 text-zinc-400 hover:text-cyan-400 transition-colors flex-shrink-0"
                        title="Orijinal Haberi Aç"
                      >
                        <ExternalLink size={12} />
                      </a>
                    )}
                  </div>
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
