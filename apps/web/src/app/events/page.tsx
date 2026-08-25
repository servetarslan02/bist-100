"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling } from "@/lib/api";
import {
  Zap, Filter, Clock, ExternalLink, Radio, CheckCircle2,
  TrendingUp, TrendingDown, AlertCircle, Loader2
} from "lucide-react";
import { SkeletonList, SkeletonCard, SkeletonTable, SkeletonChart } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

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
  { id: "NEWS", label: "Haber Akışı (Canlı RSS)" },
  { id: "MACRO", label: "Makro & TCMB" },
];

export default function EventCenterPage() {
  const router = useRouter();
  const [filter, setFilter] = useState<string>("ALL");
  const { data: eventsData, loading, lastUpdated } = usePolling<{ events: EventItem[]; count: number }>("/event-study/events", 4000);

  const events = useMemo(() => eventsData?.events ?? [], [eventsData]);
  const filtered = useMemo(() => filter === "ALL" ? events : events.filter(e => e.type === filter), [filter, events]);

  return (
    <ErrorBoundary name="events">
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Olay Merkezi & Canlı Haber Akışı</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Canlı KAP Bildirimleri · BloombergHT / Bigpara / TRT Finans Akışı · TCMB & Makro Olay Analizi
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-zinc-400">
            Son Güncelleme: <span className="text-zinc-200 font-mono">{lastUpdated?.toLocaleTimeString()}</span>
          </span>
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold">
            <div className="w-1.5 h-1.5 rounded-full live-dot animate-ping" />
            OTOMATİK CANLI AKIŞ (4sn)
          </div>
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

      {/* Loading state */}
      {loading && events.length === 0 && (
        <SkeletonList count={6} />
      )}

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
    </ErrorBoundary>
  );
}
