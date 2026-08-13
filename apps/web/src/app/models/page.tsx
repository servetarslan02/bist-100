"use client";

import { usePolling, type ModelInfo } from "@/lib/api";

export default function ModelCenter() {
  const { data: models, loading } = usePolling<ModelInfo[]>("/models", 30000);

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Model Center</h1>
        <p className="text-[11px] text-zinc-600">ML/AI model registry • champion/challenger</p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-5 h-5 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
        </div>
      ) : !models || models.length === 0 ? (
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-8 text-center">
          <p className="text-zinc-600 text-sm">No models registered yet</p>
          <p className="text-zinc-700 text-[10px] mt-1">Models will appear after first training cycle</p>
        </div>
      ) : (
        <div className="space-y-2">
          {models.map(model => (
            <div key={model.id} className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3 hover:border-zinc-700/60 transition-colors">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-zinc-200">{model.name}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">{model.model_type}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                    model.latest_status === "CHAMPION" ? "bg-emerald-950 text-emerald-400" :
                    model.latest_status === "CANDIDATE" ? "bg-amber-950 text-amber-400" :
                    "bg-zinc-800 text-zinc-500"
                  }`}>
                    {model.latest_status || "DRAFT"}
                  </span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                    model.status === "ACTIVE" ? "bg-emerald-950 text-emerald-400" : "bg-zinc-800 text-zinc-500"
                  }`}>
                    {model.status}
                  </span>
                </div>
              </div>

              <p className="text-[11px] text-zinc-600 mb-2">{model.description}</p>

              <div className="flex items-center gap-4 text-[10px]">
                <span className="text-zinc-600">Framework: <span className="text-zinc-400">{model.model_type}</span></span>
                <span className="text-zinc-600">Version: <span className="text-zinc-400">{model.latest_version || "—"}</span></span>
              </div>

              {model.metrics && Object.keys(model.metrics).length > 0 && (
                <div className="mt-2 pt-2 border-t border-zinc-800/60 flex gap-4">
                  {Object.entries(model.metrics).map(([key, value]) => (
                    <div key={key}>
                      <p className="text-[9px] text-zinc-600 uppercase">{key.replace(/_/g, " ")}</p>
                      <p className="text-[11px] font-mono text-zinc-300">
                        {typeof value === "number" ? value.toFixed(4) : String(value)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
