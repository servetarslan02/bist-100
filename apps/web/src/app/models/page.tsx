"use client";

import { useState, useMemo } from "react";
import { usePolling } from "@/lib/api";
import {
  Cpu, Activity, CheckCircle2, TrendingUp, BarChart2, ShieldCheck,
  ExternalLink, Layers, Award
} from "lucide-react";
import { SkeletonList, SkeletonCard, SkeletonTable, SkeletonChart } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

interface ModelRegistryItem {
  id: string;
  name: string;
  type: string;
  role: string;
  version: string;
  status: "CHAMPION" | "CHALLENGER" | "EVALUATION";
  metrics: {
    ic: number;
    r2: number;
    sharpe: number;
    latency_ms: number;
  };
  features_count: number;
  last_trained: string;
}



export default function ModelCenterPage() {
  const { data: modelsData } = usePolling<any>("/models/list", 10000);

  const models: ModelRegistryItem[] = useMemo(() => modelsData?.models || [], [modelsData]);
  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Model Merkezi & ML Kayıt Defteri</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Champion / Challenger Modeller · Bilgi Katsayısı (IC) · R² & Sharpe Metrikleri · MLflow Entegrasyonu
          </p>
        </div>
        <div className="flex items-center gap-2">
          <a
            href="http://localhost:5000"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-bold transition-all bg-zinc-900 border border-zinc-800 text-zinc-300 hover:text-white"
          >
            <ExternalLink size={13} />
            MLflow Panelini Aç (:5000)
          </a>
        </div>
      </div>

      {/* Model Cards Grid */}
      <div className="space-y-4">
        {models.map((model) => {
          const isChamp = model.status === "CHAMPION";
          return (
            <div
              key={model.id}
              className="rounded-xl p-5 select-none"
              style={{
                background: "var(--color-bg-card)",
                border: "1px solid var(--color-border-subtle)",
                borderLeft: `3px solid ${isChamp ? "#00e5a0" : "#00c8ff"}`,
              }}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center"
                    style={{ background: isChamp ? "rgba(0,229,160,0.12)" : "rgba(0,200,255,0.12)" }}
                  >
                    {isChamp ? <Award size={16} style={{ color: "#00e5a0" }} /> : <Cpu size={16} style={{ color: "#00c8ff" }} />}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-bold text-zinc-100">{model.name}</h3>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">
                        {model.version}
                      </span>
                    </div>
                    <p className="text-[11px] text-zinc-500">{model.role} · {model.type}</p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span
                    className="text-[10px] font-bold px-2.5 py-1 rounded-full"
                    style={{
                      background: isChamp ? "rgba(0,229,160,0.12)" : "rgba(0,200,255,0.12)",
                      color: isChamp ? "#00e5a0" : "#00c8ff",
                    }}
                  >
                    {model.status === "CHAMPION" ? "ŞAMPİYON MODEL (CANLI)" : "MEYDAN OKUYAN (CHALLENGER)"}
                  </span>
                </div>
              </div>

              {/* Metrics Row */}
              <div className="grid grid-cols-5 gap-3 pt-3 border-t border-zinc-800/40 text-xs font-data">
                <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800/40">
                  <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Bilgi Katsayısı (IC)</span>
                  <span className="text-sm font-bold text-emerald-400">+{model.metrics.ic.toFixed(3)}</span>
                </div>
                <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800/40">
                  <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Açıklama Oranı (R²)</span>
                  <span className="text-sm font-bold text-cyan-400">%{(model.metrics.r2 * 100).toFixed(1)}</span>
                </div>
                <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800/40">
                  <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Model Sharpe</span>
                  <span className="text-sm font-bold text-zinc-200">{model.metrics.sharpe.toFixed(2)}</span>
                </div>
                <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800/40">
                  <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Gecikme (Latency)</span>
                  <span className="text-sm font-bold text-amber-400">{model.metrics.latency_ms} ms</span>
                </div>
                <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800/40">
                  <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Öznitelik Sayısı</span>
                  <span className="text-sm font-bold text-zinc-300">{model.features_count} Özellik</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


