"use client";

import { useState, useEffect } from "react";

interface Discovery {
  id: string;
  timestamp: string;
  type: string;
  ticker: string;
  title: string;
  description: string;
  confidence: number;
  status: "NEW" | "INVESTIGATING" | "CONFIRMED" | "DISMISSED";
  evidence: string[];
}

export default function AIResearch() {
  const [discoveries, setDiscoveries] = useState<Discovery[]>([]);
  const [filter, setFilter] = useState("ALL");

  useEffect(() => {
    // Gerçek veri çek
    async function fetchData() {
      try {
        const res = await fetch("/api/events?limit=50");
        if (res.ok) {
          const events = await res.json();
          // Event'leri discovery formatına çevir
          const disc: Discovery[] = events.map((e: any, i: number) => ({
            id: String(i + 1),
            timestamp: e.created_at || new Date().toISOString(),
            type: e.event_type || "OTHER",
            ticker: e.data?.ticker || "",
            title: e.data?.title || e.message || "Event detected",
            description: e.data?.summary || "",
            confidence: Math.round((e.data?.importance || 0.5) * 100),
            status: "NEW" as const,
            evidence: [],
          }));
          setDiscoveries(disc);
        }
      } catch {}
    }
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  const filtered = filter === "ALL" ? discoveries : discoveries.filter(d => d.type === filter);

  const types = ["ALL", ...new Set(discoveries.map(d => d.type))];

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">AI Research</h1>
          <p className="text-[11px] text-zinc-600">Discovery log • pattern detection • evidence analysis</p>
        </div>
      </div>

      <div className="flex gap-1.5">
        {types.map(t => (
          <button key={t} onClick={() => setFilter(t)}
            className={`px-2.5 py-1 text-[10px] rounded transition-colors ${
              filter === t ? "bg-zinc-800 text-zinc-200 border border-zinc-700" : "bg-zinc-900 text-zinc-600 border border-zinc-800"
            }`}>
            {t}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        {filtered.length === 0 ? (
          <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-8 text-center">
            <p className="text-zinc-600">No discoveries yet</p>
            <p className="text-[10px] text-zinc-700 mt-1">AI will log findings as it monitors the market</p>
          </div>
        ) : (
          filtered.map(d => (
            <div key={d.id} className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3 hover:border-zinc-700/60 transition-colors cursor-pointer">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] font-mono text-zinc-600">#{d.id}</span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">{d.type}</span>
                    {d.ticker && <span className="text-[9px] font-mono text-zinc-400">{d.ticker}</span>}
                  </div>
                  <h3 className="text-[12px] text-zinc-200 mt-1">{d.title}</h3>
                  {d.description && <p className="text-[11px] text-zinc-500 mt-0.5">{d.description}</p>}
                </div>
                <div className="text-right">
                  <p className="text-[9px] text-zinc-600">Confidence</p>
                  <p className={`text-sm font-mono font-semibold ${
                    d.confidence >= 80 ? "text-emerald-400" : d.confidence >= 60 ? "text-amber-400" : "text-zinc-400"
                  }`}>{d.confidence}%</p>
                </div>
              </div>
              <div className="flex items-center gap-2 mt-2">
                <span className="text-[9px] text-zinc-600">{new Date(d.timestamp).toLocaleString("tr-TR")}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
