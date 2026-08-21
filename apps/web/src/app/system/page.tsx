"use client";

import { usePolling, type SystemStatus } from "@/lib/api";
import { Activity, Cpu, HardDrive, MemoryStick, Server, Zap, Database, Radio, CheckCircle2, XCircle } from "lucide-react";

const RESOURCES = [
  { label: "CPU", value: 34, icon: Cpu },
  { label: "RAM", value: 51, icon: MemoryStick },
  { label: "GPU", value: 28, icon: Zap },
  { label: "Disk", value: 22, icon: HardDrive },
];

const SYSTEM_INFO = [
  { label: "Version", value: "ALPHA BIST v1.2" },
  { label: "Database", value: "PostgreSQL + ClickHouse" },
  { label: "Event Bus", value: "Redpanda" },
  { label: "ML Models", value: "5 active" },
  { label: "LLM", value: "Gemma 4 12B Q4" },
  { label: "Instruments", value: "800+" },
];

const PIPELINE_STATS = [
  { label: "Events/sec", value: "~4,800" },
  { label: "Latency", value: "17ms" },
  { label: "Dropped", value: "0" },
  { label: "Completeness", value: "99.99%" },
  { label: "Uptime", value: "99.98%" },
];

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
      <span className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>{label}</span>
      <span className="text-[11px] font-data font-medium" style={{ color: "var(--color-text-primary)" }}>{value}</span>
    </div>
  );
}

function ResourceBar({ label, value, icon: Icon }: { label: string; value: number; icon: React.ElementType }) {
  const color = value > 80 ? "#ff4466" : value > 60 ? "#ffaa00" : "#00e5a0";
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Icon size={11} style={{ color: "var(--color-text-muted)" }} />
          <span className="text-[11px]" style={{ color: "var(--color-text-secondary)" }}>{label}</span>
        </div>
        <span className="text-[11px] font-data font-semibold" style={{ color }}>{value}%</span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${value}%`, background: `linear-gradient(90deg, ${color}80, ${color})` }}
        />
      </div>
    </div>
  );
}

export default function SystemHealth() {
  const { data: status } = usePolling<SystemStatus>("/status", 10000);
  const services = status?.services || {};
  const allHealthy = Object.values(services).every(s => s === "healthy");
  const healthyCount = Object.values(services).filter(s => s === "healthy").length;
  const totalCount = Object.keys(services).length;

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">System Health</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>Infrastructure monitoring</p>
        </div>
        <div
          className="flex items-center gap-2 px-4 py-2 rounded-xl"
          style={{
            background: allHealthy ? "rgba(0,229,160,0.08)" : "rgba(255,68,102,0.08)",
            border: `1px solid ${allHealthy ? "rgba(0,229,160,0.2)" : "rgba(255,68,102,0.2)"}`,
          }}
        >
          {allHealthy
            ? <CheckCircle2 size={14} style={{ color: "#00e5a0" }} />
            : <XCircle size={14} style={{ color: "#ff4466" }} />
          }
          <span className="text-sm font-semibold" style={{ color: allHealthy ? "#00e5a0" : "#ff4466" }}>
            {allHealthy ? "All Systems Operational" : "Degraded"}
          </span>
          <span className="text-xs font-data" style={{ color: "var(--color-text-secondary)" }}>
            {healthyCount}/{totalCount}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Services */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5 px-5 py-3" style={{ borderBottom: "1px solid var(--color-border-subtle)" }}>
            <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(0,229,160,0.12)" }}>
              <Server size={13} style={{ color: "#00e5a0" }} />
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>Services</h2>
          </div>
          <div className="px-5 py-2">
            {Object.entries(services).length === 0 ? (
              <p className="py-6 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>Loading...</p>
            ) : (
              Object.entries(services).map(([name, health]) => {
                const ok = health === "healthy";
                return (
                  <div key={name} className="flex items-center justify-between py-2.5" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <div className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 rounded-full" style={{ background: ok ? "#00e5a0" : "#ff4466", boxShadow: ok ? "0 0 6px #00e5a0" : "0 0 6px #ff4466" }} />
                      <span className="text-[11px] capitalize" style={{ color: "var(--color-text-secondary)" }}>
                        {name.replace(/_/g, " ")}
                      </span>
                    </div>
                    <span
                      className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                      style={{ background: ok ? "rgba(0,229,160,0.1)" : "rgba(255,68,102,0.1)", color: ok ? "#00e5a0" : "#ff4466" }}
                    >
                      {health as string}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Resources */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5 px-5 py-3" style={{ borderBottom: "1px solid var(--color-border-subtle)" }}>
            <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(0,200,255,0.12)" }}>
              <Activity size={13} style={{ color: "#00c8ff" }} />
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>Resources</h2>
          </div>
          <div className="px-5 py-4 space-y-4">
            {RESOURCES.map(r => <ResourceBar key={r.label} {...r} />)}
          </div>
        </div>

        {/* System Info */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5 px-5 py-3" style={{ borderBottom: "1px solid var(--color-border-subtle)" }}>
            <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(153,102,255,0.12)" }}>
              <Database size={13} style={{ color: "#9966ff" }} />
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>System Info</h2>
          </div>
          <div className="px-5 py-2">
            {SYSTEM_INFO.map(item => <InfoRow key={item.label} {...item} />)}
            <InfoRow label="Last Update" value={status?.timestamp ? new Date(status.timestamp).toLocaleString("tr-TR") : "—"} />
          </div>
        </div>

        {/* Data Pipeline */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5 px-5 py-3" style={{ borderBottom: "1px solid var(--color-border-subtle)" }}>
            <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(255,170,0,0.12)" }}>
              <Radio size={13} style={{ color: "#ffaa00" }} />
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>Data Pipeline</h2>
          </div>
          <div className="px-5 py-2">
            {PIPELINE_STATS.map(item => <InfoRow key={item.label} {...item} />)}
          </div>
        </div>
      </div>
    </div>
  );
}
