"use client";

import { useEffect, useState } from "react";

interface Alert {
  id: number;
  alert_type: string;
  severity: string;
  title: string;
  message: string;
  acknowledged: boolean;
  created_at: string;
}

export default function AlertCenter() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 15000);
    return () => clearInterval(interval);
  }, []);

  async function fetchAlerts() {
    try {
      const res = await fetch("/api/alerts?limit=50");
      if (res.ok) {
        setAlerts(await res.json());
      }
    } catch (e) {
      console.error("Failed to fetch alerts:", e);
    } finally {
      setLoading(false);
    }
  }

  const severityColor: Record<string, string> = {
    CRITICAL: "border-l-red-500 bg-red-500/5",
    HIGH: "border-l-orange-500 bg-orange-500/5",
    MEDIUM: "border-l-yellow-500 bg-yellow-500/5",
    LOW: "border-l-blue-500 bg-blue-500/5",
  };

  const severityIcon: Record<string, string> = {
    CRITICAL: "🔴",
    HIGH: "🟠",
    MEDIUM: "🟡",
    LOW: "🔵",
  };

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Alert Center</h1>

      {loading ? (
        <div className="text-alpha-muted text-center py-8">Loading...</div>
      ) : alerts.length === 0 ? (
        <div className="bg-alpha-surface border border-alpha-border rounded-lg p-8 text-center">
          <p className="text-alpha-muted">No alerts</p>
        </div>
      ) : (
        <div className="space-y-2">
          {alerts.map(alert => (
            <div
              key={alert.id}
              className={`bg-alpha-surface border-l-4 ${severityColor[alert.severity] || severityColor.LOW} rounded-r-lg p-4`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3">
                  <span className="text-lg">{severityIcon[alert.severity] || "⚪"}</span>
                  <div>
                    <h3 className="font-semibold text-sm">{alert.title}</h3>
                    <p className="text-sm text-alpha-muted mt-1">{alert.message}</p>
                    <div className="flex items-center gap-3 mt-2">
                      <span className="text-xs text-alpha-muted">{alert.alert_type}</span>
                      <span className="text-xs text-alpha-muted">
                        {new Date(alert.created_at).toLocaleString("tr-TR")}
                      </span>
                    </div>
                  </div>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded ${
                  alert.severity === "CRITICAL" ? "bg-red-900/30 text-red-400" :
                  alert.severity === "HIGH" ? "bg-orange-900/30 text-orange-400" :
                  alert.severity === "MEDIUM" ? "bg-yellow-900/30 text-yellow-400" :
                  "bg-blue-900/30 text-blue-400"
                }`}>
                  {alert.severity}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
