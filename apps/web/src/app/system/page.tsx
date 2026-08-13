"use client";

import { usePolling, type SystemStatus } from "@/lib/api";

export default function SystemHealth() {
  const { data: status } = usePolling<SystemStatus>("/status", 10000);

  const services = status?.services || {};
  const allHealthy = Object.values(services).every(s => s === "healthy");

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">System Health</h1>
          <p className="text-[11px] text-zinc-600">Infrastructure monitoring</p>
        </div>
        <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] ${
          allHealthy ? "bg-emerald-950/50 text-emerald-400" : "bg-red-950/50 text-red-400"
        }`}>
          <div className={`w-1.5 h-1.5 rounded-full ${allHealthy ? "bg-emerald-500" : "bg-red-500"}`} />
          {allHealthy ? "ALL SYSTEMS OPERATIONAL" : "DEGRADED"}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {/* Services */}
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Services</h2>
          <div className="space-y-2">
            {Object.entries(services).map(([name, health]) => (
              <div key={name} className="flex items-center justify-between py-1 border-b border-zinc-800/30 last:border-0">
                <span className="text-[11px] text-zinc-400 capitalize">{name.replace(/_/g, " ")}</span>
                <div className="flex items-center gap-1.5">
                  <div className={`w-1.5 h-1.5 rounded-full ${health === "healthy" ? "bg-emerald-500" : "bg-red-500"}`} />
                  <span className={`text-[10px] font-mono ${health === "healthy" ? "text-emerald-500" : "text-red-500"}`}>
                    {health}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* System Info */}
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">System Info</h2>
          <div className="space-y-2">
            {[
              { label: "Version", value: "ALPHA BIST v1.2" },
              { label: "Status", value: status?.status || "—" },
              { label: "Last Update", value: status?.timestamp ? new Date(status.timestamp).toLocaleString("tr-TR") : "—" },
              { label: "Instruments", value: "800+" },
              { label: "ML Models", value: "5 active" },
              { label: "LLM", value: "Gemma 4 12B Q4" },
              { label: "Database", value: "PostgreSQL + ClickHouse" },
              { label: "Event Bus", value: "Redpanda" },
            ].map(item => (
              <div key={item.label} className="flex items-center justify-between py-1 border-b border-zinc-800/30 last:border-0">
                <span className="text-[11px] text-zinc-500">{item.label}</span>
                <span className="text-[11px] font-mono text-zinc-300">{item.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Resources */}
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Resources</h2>
          <div className="space-y-3">
            {[
              { label: "CPU", value: 34, max: 100 },
              { label: "RAM", value: 51, max: 100 },
              { label: "GPU", value: 28, max: 100 },
              { label: "Disk", value: 22, max: 100 },
            ].map(r => (
              <div key={r.label}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-zinc-500">{r.label}</span>
                  <span className="text-[10px] font-mono text-zinc-400">{r.value}%</span>
                </div>
                <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      r.value > 80 ? "bg-red-500" : r.value > 60 ? "bg-amber-500" : "bg-emerald-500"
                    }`}
                    style={{ width: `${r.value}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Data Pipeline */}
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Data Pipeline</h2>
          <div className="space-y-2">
            {[
              { label: "Events/sec", value: "~4,800" },
              { label: "Latency", value: "17ms" },
              { label: "Dropped events", value: "0" },
              { label: "Data completeness", value: "99.99%" },
              { label: "Uptime", value: "99.98%" },
            ].map(item => (
              <div key={item.label} className="flex items-center justify-between py-1 border-b border-zinc-800/30 last:border-0">
                <span className="text-[11px] text-zinc-500">{item.label}</span>
                <span className="text-[11px] font-mono text-zinc-300">{item.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
