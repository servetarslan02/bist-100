"use client";

import { useEffect, useState } from "react";

interface Model {
  id: number;
  name: string;
  description: string;
  model_type: string;
  framework: string;
  target_variable: string;
  status: string;
  latest_version: string;
  latest_status: string;
  metrics: Record<string, number>;
  backtest_metrics: Record<string, number>;
}

export default function ModelCenter() {
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchModels();
  }, []);

  async function fetchModels() {
    try {
      const res = await fetch("/api/models");
      if (res.ok) {
        setModels(await res.json());
      }
    } catch (e) {
      console.error("Failed to fetch models:", e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Model Center</h1>

      <div className="grid grid-cols-1 gap-4">
        {loading ? (
          <div className="text-alpha-muted text-center py-8">Loading...</div>
        ) : models.length === 0 ? (
          <div className="bg-alpha-surface border border-alpha-border rounded-lg p-8 text-center">
            <p className="text-alpha-muted">No models registered yet</p>
            <p className="text-xs text-alpha-muted mt-2">Models will appear after first training cycle</p>
          </div>
        ) : (
          models.map(model => (
            <div key={model.id} className="bg-alpha-surface border border-alpha-border rounded-lg p-4">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="font-semibold">{model.name}</h3>
                  <p className="text-sm text-alpha-muted">{model.description}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs px-2 py-0.5 rounded bg-alpha-bg">{model.model_type}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    model.latest_status === "CHAMPION" ? "bg-green-900/30 text-green-400" :
                    model.latest_status === "CANDIDATE" ? "bg-yellow-900/30 text-yellow-400" :
                    "bg-alpha-bg text-alpha-muted"
                  }`}>
                    {model.latest_status || "DRAFT"}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-4 text-sm">
                <div>
                  <p className="text-alpha-muted text-xs">Framework</p>
                  <p>{model.framework}</p>
                </div>
                <div>
                  <p className="text-alpha-muted text-xs">Target</p>
                  <p>{model.target_variable}</p>
                </div>
                <div>
                  <p className="text-alpha-muted text-xs">Version</p>
                  <p>{model.latest_version || "—"}</p>
                </div>
                <div>
                  <p className="text-alpha-muted text-xs">Status</p>
                  <p>{model.status}</p>
                </div>
              </div>

              {model.metrics && Object.keys(model.metrics).length > 0 && (
                <div className="mt-3 pt-3 border-t border-alpha-border">
                  <p className="text-xs text-alpha-muted mb-2">Metrics</p>
                  <div className="flex gap-4">
                    {Object.entries(model.metrics).map(([key, value]) => (
                      <div key={key}>
                        <p className="text-xs text-alpha-muted">{key}</p>
                        <p className="font-mono text-sm">{typeof value === "number" ? value.toFixed(4) : String(value)}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
