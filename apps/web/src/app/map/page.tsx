"use client";

import { useState, useEffect } from "react";

export default function Page() {
  const [status, setStatus] = useState<any>(null);

  useEffect(() => {
    fetch("/api/status").then(r => r.json()).then(setStatus).catch(() => {});
  }, []);

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">ALPHA Module</h1>
        <p className="text-[11px] text-zinc-600">BIST Intelligence Platform</p>
      </div>
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-4">
          <div className={`w-2 h-2 rounded-full ${status?.status === "ok" ? "bg-emerald-500" : "bg-zinc-600"}`} />
          <span className="text-[11px] text-zinc-400">System: {status?.status || "connecting..."}</span>
        </div>
        <div className="text-[12px] text-zinc-500 leading-relaxed">
          <p>Core capabilities: Real-time market scanning, Event-driven analysis, ML predictions, Risk management</p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <p className="text-[9px] text-zinc-600 uppercase">Status</p>
          <p className="text-sm font-mono text-zinc-300 mt-1">{status?.status || "—"}</p>
        </div>
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <p className="text-[9px] text-zinc-600 uppercase">Services</p>
          <p className="text-sm font-mono text-zinc-300 mt-1">{status?.services ? Object.keys(status.services).length : "—"} active</p>
        </div>
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <p className="text-[9px] text-zinc-600 uppercase">Last Update</p>
          <p className="text-sm font-mono text-zinc-300 mt-1">{status?.timestamp ? new Date(status.timestamp).toLocaleTimeString("tr-TR") : "—"}</p>
        </div>
      </div>
    </div>
  );
}
