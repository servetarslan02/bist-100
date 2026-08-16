"use client";

import { useState } from "react";

interface EventItem {
  id: string;
  timestamp: string;
  type: string;
  source: string;
  title: string;
  ticker?: string;
  sentiment?: number;
  importance?: number;
}

const EVENT_TYPES = ["ALL", "KAP", "NEWS", "MACRO", "SOCIAL"] as const;

const MOCK_EVENTS: EventItem[] = [
  { id: "1", timestamp: "2026-08-14T10:32:17", type: "KAP", source: "kap.org.tr", title: "THYAO - Yeni yatırım kararı açıklandı", ticker: "THYAO", sentiment: 0.64, importance: 0.88 },
  { id: "2", timestamp: "2026-08-14T10:28:05", type: "NEWS", source: "AA", title: "TCMB faiz kararı açıklandı", sentiment: -0.2, importance: 0.95 },
  { id: "3", timestamp: "2026-08-14T10:25:42", type: "MACRO", source: "TCMB", title: "CPI verisi: %58.2 (beklenti: %55.0)", sentiment: -0.4, importance: 0.9 },
  { id: "4", timestamp: "2026-08-14T10:21:18", type: "KAP", source: "kap.org.tr", title: "ASELS - Savunma sanayii sözleşmesi imzalandı", ticker: "ASELS", sentiment: 0.8, importance: 0.75 },
  { id: "5", timestamp: "2026-08-14T10:18:33", type: "NEWS", source: "Reuters", title: "BIST bankacılık endeksi pozitif ayrışıyor", sentiment: 0.5, importance: 0.6 },
  { id: "6", timestamp: "2026-08-14T10:15:07", type: "SOCIAL", source: "X", title: "TUPRS hakkında artan sosyal medya ilgisi", ticker: "TUPRS", sentiment: 0.3, importance: 0.4 },
  { id: "7", timestamp: "2026-08-14T10:12:44", type: "KAP", source: "kap.org.tr", title: "EREGL - Çeyreklik finansal sonuçlar açıklandı", ticker: "EREGL", sentiment: 0.1, importance: 0.85 },
  { id: "8", timestamp: "2026-08-14T10:08:21", type: "MACRO", source: "EVDS", title: "USD/TRY: 34.25 (+%0.8)", sentiment: -0.3, importance: 0.7 },
];

const TYPE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  KAP: { bg: "bg-emerald-950/30", text: "text-emerald-400", border: "border-emerald-800/50" },
  NEWS: { bg: "bg-blue-950/30", text: "text-blue-400", border: "border-blue-800/50" },
  MACRO: { bg: "bg-amber-950/30", text: "text-amber-400", border: "border-amber-800/50" },
  SOCIAL: { bg: "bg-purple-950/30", text: "text-purple-400", border: "border-purple-800/50" },
};

export default function EventCenter() {
  const [filter, setFilter] = useState<string>("ALL");
  const [events] = useState<EventItem[]>(MOCK_EVENTS);

  const filtered = filter === "ALL" ? events : events.filter(e => e.type === filter);

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Event Center</h1>
          <p className="text-[11px] text-zinc-600">KAP • News • Macro • Social — real-time stream</p>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 pulse-dot" />
          <span className="text-[10px] text-zinc-600">LIVE</span>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-1.5">
        {EVENT_TYPES.map(t => (
          <button
            key={t}
            onClick={() => setFilter(t)}
            className={`px-2.5 py-1 text-[10px] rounded transition-colors ${
              filter === t
                ? "bg-zinc-800 text-zinc-200 border border-zinc-700"
                : "bg-zinc-900 text-zinc-600 border border-zinc-800 hover:text-zinc-400"
            }`}
          >
            {t}
            <span className="ml-1 text-zinc-600">
              ({t === "ALL" ? events.length : events.filter(e => e.type === t).length})
            </span>
          </button>
        ))}
      </div>

      {/* Event Stream */}
      <div className="space-y-1.5">
        {filtered.map(event => {
          const config = TYPE_COLORS[event.type] || TYPE_COLORS.NEWS;
          return (
            <div
              key={event.id}
              className={`${config.bg} border ${config.border} rounded-lg p-3 hover:brightness-110 transition-all cursor-pointer`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5">
                    <span className={`text-[9px] px-1.5 py-0.5 rounded ${config.bg} ${config.text} border ${config.border}`}>
                      {event.type}
                    </span>
                  </div>
                  <div>
                    <h3 className="text-[12px] text-zinc-200">{event.title}</h3>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-[9px] text-zinc-600">{event.source}</span>
                      {event.ticker && (
                        <>
                          <span className="text-[9px] text-zinc-700">•</span>
                          <span className="text-[9px] font-mono text-zinc-500">{event.ticker}</span>
                        </>
                      )}
                      <span className="text-[9px] text-zinc-700">•</span>
                      <span className="text-[9px] text-zinc-600">
                        {new Date(event.timestamp).toLocaleTimeString("tr-TR")}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {event.sentiment !== undefined && (
                    <span className={`text-[9px] font-mono ${event.sentiment > 0 ? "text-emerald-400" : event.sentiment < 0 ? "text-red-400" : "text-zinc-500"}`}>
                      {event.sentiment > 0 ? "+" : ""}{(event.sentiment * 100).toFixed(0)}%
                    </span>
                  )}
                  {event.importance !== undefined && (
                    <div className="flex items-center gap-0.5">
                      {[1, 2, 3, 4, 5].map(i => (
                        <div
                          key={i}
                          className={`w-1 h-3 rounded-sm ${
                            i <= event.importance! * 5 ? "bg-zinc-400" : "bg-zinc-800"
                          }`}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
