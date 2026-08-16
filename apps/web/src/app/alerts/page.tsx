"use client";

import { usePolling, type Alert } from "@/lib/api";

const SEVERITY_CONFIG: Record<string, { color: string; bg: string; icon: string }> = {
  CRITICAL: { color: "text-red-400", bg: "bg-red-950/50", icon: "🔴" },
  HIGH: { color: "text-orange-400", bg: "bg-orange-950/50", icon: "🟠" },
  MEDIUM: { color: "text-amber-400", bg: "bg-amber-950/50", icon: "🟡" },
  LOW: { color: "text-zinc-400", bg: "bg-zinc-800/50", icon: "🔵" },
};

export default function AlertCenter() {
  const { data: alerts, loading } = usePolling<Alert[]>("/alerts?limit=50", 15000);

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Alert Center</h1>
        <p className="text-[11px] text-zinc-600">Risk alerts • system warnings • opportunities</p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-5 h-5 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
        </div>
      ) : !alerts || alerts.length === 0 ? (
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-8 text-center">
          <p className="text-zinc-500 text-sm">No active alerts</p>
          <p className="text-zinc-700 text-[10px] mt-1">System is operating normally</p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {alerts.map(alert => {
            const config = SEVERITY_CONFIG[alert.severity] || SEVERITY_CONFIG.LOW;
            return (
              <div
                key={alert.id}
                className={`${config.bg} border-l-2 ${
                  alert.severity === "CRITICAL" ? "border-l-red-500" :
                  alert.severity === "HIGH" ? "border-l-orange-500" :
                  alert.severity === "MEDIUM" ? "border-l-amber-500" :
                  "border-l-zinc-600"
                } rounded-r-lg p-3 hover:brightness-110 transition-all cursor-pointer`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-2">
                    <span className="text-sm">{config.icon}</span>
                    <div>
                      <h3 className="text-[12px] font-medium text-zinc-200">{alert.title}</h3>
                      <p className="text-[11px] text-zinc-500 mt-0.5">{alert.message}</p>
                      <div className="flex items-center gap-3 mt-1.5">
                        <span className="text-[9px] text-zinc-600">{alert.alert_type}</span>
                        <span className="text-[9px] text-zinc-700">•</span>
                        <span className="text-[9px] text-zinc-600">
                          {new Date(alert.created_at).toLocaleString("tr-TR")}
                        </span>
                      </div>
                    </div>
                  </div>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded ${config.bg} ${config.color} border border-zinc-800`}>
                    {alert.severity}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
