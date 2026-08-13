"use client";

import { useEffect, useState } from "react";

interface SystemStatus {
  status: string;
  services: Record<string, string>;
  timestamp: string;
}

export default function SystemHealth() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  async function fetchStatus() {
    try {
      const res = await fetch("/api/status");
      if (res.ok) {
        setStatus(await res.json());
      }
    } catch (e) {
      console.error("Failed to fetch status:", e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">System Health</h1>

      <div className="grid grid-cols-2 gap-6">
        {/* Services */}
        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <h2 className="text-sm font-semibold mb-4">Services</h2>
          {loading ? (
            <p className="text-alpha-muted text-sm">Loading...</p>
          ) : (
            <div className="space-y-3">
              {status?.services && Object.entries(status.services).map(([name, health]) => (
                <div key={name} className="flex items-center justify-between">
                  <span className="text-sm capitalize">{name.replace("_", " ")}</span>
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${health === "healthy" ? "bg-alpha-accent" : "bg-alpha-danger"}`} />
                    <span className={`text-sm ${health === "healthy" ? "text-alpha-accent" : "text-alpha-danger"}`}>
                      {health}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* System Info */}
        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <h2 className="text-sm font-semibold mb-4">System Info</h2>
          <div className="space-y-3 text-sm">
            <InfoRow label="Version" value="ALPHA BIST v1.0" />
            <InfoRow label="Status" value={status?.status || "—"} />
            <InfoRow label="Last Update" value={status?.timestamp ? new Date(status.timestamp).toLocaleString("tr-TR") : "—"} />
            <InfoRow label="Instruments" value="800+" />
            <InfoRow label="ML Models" value="5 active" />
            <InfoRow label="LLM" value="Gemma 4 12B Q4" />
          </div>
        </div>

        {/* Resource Usage */}
        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <h2 className="text-sm font-semibold mb-4">Resources</h2>
          <div className="space-y-4">
            <ResourceBar label="CPU" value={34} />
            <ResourceBar label="RAM" value={51} />
            <ResourceBar label="GPU" value={28} />
            <ResourceBar label="Disk" value={22} />
          </div>
        </div>

        {/* Data Pipeline */}
        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
          <h2 className="text-sm font-semibold mb-4">Data Pipeline</h2>
          <div className="space-y-3 text-sm">
            <InfoRow label="Events/sec" value="~4,800" />
            <InfoRow label="Latency" value="17ms" />
            <InfoRow label="Dropped" value="0" />
            <InfoRow label="Completeness" value="99.99%" />
            <InfoRow label="Uptime" value="99.98%" />
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-alpha-muted">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}

function ResourceBar({ label, value }: { label: string; value: number }) {
  const color = value > 80 ? "bg-alpha-danger" : value > 60 ? "bg-alpha-warning" : "bg-alpha-accent";

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-alpha-muted text-sm">{label}</span>
        <span className="text-sm font-mono">{value}%</span>
      </div>
      <div className="w-full bg-alpha-border rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}
