"use client";

import { useState, useMemo } from "react";
import { usePolling } from "@/lib/api";
import {
  Database, Server, HardDrive, Radio, RefreshCw, Layers, CheckCircle2, Zap, Loader2
} from "lucide-react";
import { SkeletonList, SkeletonCard, SkeletonTable, SkeletonChart } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

interface DatabaseInfo {
  name: string;
  type: string;
  role: string;
  size: string;
  rows_count: string;
  status: "ONLINE" | "OPTIMIZING";
  latency_ms: number;
  tables: Array<{ name: string; rows: string; size: string }>;
}

export default function DataCenterPage() {
  const { data: dbData, loading, refetch } = usePolling<any>("/system/databases", 5000);
  const databases: DatabaseInfo[] = useMemo(() => dbData?.databases ?? [], [dbData]);
  const [optimizing, setOptimizing] = useState(false);
  const [optResult, setOptResult] = useState<any>(null);

  const handleOptimize = async () => {
    setOptimizing(true);
    setOptResult(null);
    try {
      const res = await fetch("/api/v1/system/optimize_storage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      setOptResult(data);
      refetch();
    } catch (e: any) {
      console.error(e);
    } finally {
      setOptimizing(false);
    }
  };

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Veri Merkezi & Dağıtık Depolama Katmanı</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            ClickHouse (OLAP) · PostgreSQL 17 (OLTP) · Redis 8.0 (In-Memory) · Redpanda (Kafka) Canlı Telemetrisi
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleOptimize}
            disabled={optimizing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition-all bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20 cursor-pointer"
          >
            <RefreshCw size={13} className={optimizing ? "animate-spin" : ""} />
            {optimizing ? "Optimize Ediliyor..." : "Depolamayı Optimize Et"}
          </button>
        </div>
      </div>

      {optResult && (
        <div className="rounded-xl p-3.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs flex items-center justify-between animate-fade">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={15} />
            <span>{optResult.message || "Depolama optimizasyonu başarıyla tamamlandı."}</span>
          </div>
          <span className="font-data font-bold">Kazanç: {optResult.reclaimed_space || "1.2 MB"}</span>
        </div>
      )}

      {loading && databases.length === 0 && (
        <div className="flex items-center justify-center p-12 text-zinc-500 gap-2">
          <Loader2 className="animate-spin" size={16} />
          <span>Veritabanı telemetrisi okunuyor...</span>
        </div>
      )}

      {/* Database Cluster Grid */}
      <div className="grid grid-cols-2 gap-4">
        {databases.map((db, idx) => {
          const isCh = db.type.includes("Columnar");
          const isPg = db.type.includes("Relational");
          const isRedis = db.type.includes("In-Memory");
          const accentClr = isCh ? "#00e5a0" : isPg ? "#00c8ff" : isRedis ? "#ff4466" : "#a855f7";

          return (
            <div
              key={idx}
              className="rounded-xl p-5 space-y-4 select-none"
              style={{
                background: "var(--color-bg-card)",
                border: "1px solid var(--color-border-subtle)",
                borderTop: `3px solid ${accentClr}`,
              }}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className="w-9 h-9 rounded-xl flex items-center justify-center"
                    style={{ background: `${accentClr}15`, color: accentClr }}
                  >
                    {isCh ? <Database size={18} /> : isPg ? <Server size={18} /> : isRedis ? <Zap size={18} /> : <HardDrive size={18} />}
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-zinc-100">{db.name}</h3>
                    <p className="text-[10px] text-zinc-400 font-data">{db.type}</p>
                  </div>
                </div>
                <span
                  className="text-[9px] font-bold px-2 py-0.5 rounded-full"
                  style={{ background: "rgba(0,229,160,0.12)", color: "#00e5a0" }}
                >
                  {db.status} ({db.latency_ms} ms)
                </span>
              </div>

              <p className="text-xs text-zinc-300 leading-relaxed bg-zinc-900/40 p-2.5 rounded-lg border border-zinc-800/60">
                {db.role}
              </p>

              {/* Stats Row */}
              <div className="grid grid-cols-2 gap-2 text-[11px] font-data">
                <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800">
                  <div className="text-zinc-400 text-[10px]">Disk / RAM Boyutu</div>
                  <div className="font-bold text-zinc-100 mt-0.5">{db.size}</div>
                </div>
                <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800">
                  <div className="text-zinc-400 text-[10px]">Toplam Kayıt / Mesaj</div>
                  <div className="font-bold text-zinc-100 mt-0.5">{db.rows_count}</div>
                </div>
              </div>

              {/* Tables Preview */}
              {db.tables && db.tables.length > 0 && (
                <div className="space-y-1.5 pt-1">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                    Önemli Tablolar & Başlıklar
                  </div>
                  <div className="space-y-1 text-xs">
                    {db.tables.map((tbl, tIdx) => (
                      <div
                        key={tIdx}
                        className="flex items-center justify-between p-2 rounded bg-zinc-900/30 border border-zinc-800/40 text-[11px] font-data"
                      >
                        <span className="text-zinc-300 font-semibold">{tbl.name}</span>
                        <div className="flex items-center gap-3 text-zinc-400">
                          <span>{tbl.rows}</span>
                          <span className="text-zinc-400 font-semibold">{tbl.size}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
