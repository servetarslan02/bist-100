"use client";

import { useState, useMemo } from "react";
import { usePolling } from "@/lib/api";
import {
  Database, Server, HardDrive, Radio, RefreshCw, Layers, CheckCircle2, Zap,
  Activity, ShieldCheck, Cpu, ArrowUpRight, Clock, Wifi, Globe, FileText,
  TrendingUp, BarChart3, AlertCircle
} from "lucide-react";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

interface TableInfo {
  name: string;
  rows: string;
  size: string;
}

interface DatabaseInfo {
  name: string;
  type: string;
  role: string;
  size: string;
  rows_count: string;
  status: "ONLINE" | "OPTIMIZING" | string;
  latency_ms: number;
  tables: TableInfo[];
}

interface DataSourceInfo {
  id: string;
  name: string;
  category: string;
  type: string;
  description: string;
  status: "ONLINE" | "STANDBY" | string;
  frequency: string;
  protocol: string;
  coverage: string;
  latency_ms: number;
  last_sync: string;
  records_count: string;
  reliability_pct: number;
}

interface DatabasesResponse {
  databases?: DatabaseInfo[];
  data_sources?: DataSourceInfo[];
  [key: string]: unknown;
}

interface OptResult {
  message?: string;
  details?: Record<string, string>;
  [key: string]: unknown;
}

export default function DataCenterPage() {
  const { data, loading, refetch } = usePolling<DatabasesResponse | null>("/system/databases", 5000);
  const databases: DatabaseInfo[] = useMemo(() => data?.databases ?? [], [data]);
  const dataSources: DataSourceInfo[] = useMemo(() => data?.data_sources ?? [], [data]);

  const [activeTab, setActiveTab] = useState<"sources" | "storage">("sources");
  const [optimizing, setOptimizing] = useState(false);
  const [optResult, setOptResult] = useState<OptResult | null>(null);

  const handleOptimize = async () => {
    setOptimizing(true);
    setOptResult(null);
    try {
      const res = await fetch("/api/v1/system/optimize_storage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const resData = await res.json();
      setOptResult(resData);
      refetch();
    } catch (e: unknown) {
      console.error(e instanceof Error ? e.message : e);
    } finally {
      setOptimizing(false);
      setTimeout(() => setOptResult(null), 6000);
    }
  };

  const avgLatency = useMemo(() => {
    if (databases.length === 0) return "1.1";
    const sum = databases.reduce((acc, curr) => acc + (curr.latency_ms || 0), 0);
    return (sum / databases.length).toFixed(1);
  }, [databases]);

  return (
    <ErrorBoundary name="data">
      <div className="relative min-h-screen pb-12 overflow-hidden" style={{ background: "var(--color-bg-primary)" }}>
        {/* Ambient Radial Glow */}
        <div 
          className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[900px] h-[300px] opacity-15 blur-[120px] rounded-full"
          style={{ background: "radial-gradient(ellipse, #00c8ff 0%, #00e5a0 40%, transparent 70%)" }}
        />

        <div className="relative max-w-7xl mx-auto p-3.5 md:p-5 lg:p-6 space-y-3.5">
          
          {/* 1. ULTRA KOMPAKT HEADER & KONTROL ŞERİDİ (~45px) */}
          <div className="rounded-xl px-4 py-2.5 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-3">
            
            {/* Sol: Başlık ve Canlı Çip Rozetler */}
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="flex items-center gap-2">
                <Radio size={18} className="text-cyan-400 shrink-0 animate-pulse" />
                <h1 className="text-lg font-extrabold text-white tracking-tight">
                  Veri Kaynakları & Akış Hattı
                </h1>
              </div>

              <div className="h-3.5 w-px bg-white/[0.1] hidden sm:block" />

              {/* Kompakt Çipler */}
              <div className="flex flex-wrap items-center gap-1.5 text-xs font-data">
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-semibold">
                  <Activity size={11} />
                  <span>{dataSources.length || 6} Veri Akışı Aktif</span>
                </span>

                <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 font-semibold">
                  {databases.length || 6} Depolama ONLINE
                </span>

                <span className="px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20 font-semibold hidden md:inline-block">
                  Ort. Gecikme: {avgLatency} ms
                </span>

                <span className="px-2 py-0.5 rounded-md bg-purple-500/10 text-purple-300 border border-purple-500/20 font-semibold hidden lg:inline-block">
                  NATS JetStream: Canlı
                </span>
              </div>
            </div>

            {/* Sağ: Sekme Butonları ve Optimize Et Eylemi */}
            <div className="flex items-center gap-2">
              <div className="flex items-center rounded-lg bg-zinc-800/80 p-0.5 border border-white/[0.06] text-xs">
                <button
                  onClick={() => setActiveTab("sources")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-semibold transition-all ${
                    activeTab === "sources"
                      ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  <Wifi size={13} />
                  <span>Veri Akış Hatları ({dataSources.length || 6})</span>
                </button>
                <button
                  onClick={() => setActiveTab("storage")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-semibold transition-all ${
                    activeTab === "storage"
                      ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-sm"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  <Database size={13} />
                  <span>Depolama Katmanı ({databases.length || 6})</span>
                </button>
              </div>

              <button
                onClick={handleOptimize}
                disabled={optimizing}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20 cursor-pointer disabled:opacity-50"
              >
                <RefreshCw size={12} className={optimizing ? "animate-spin" : ""} />
                <span>{optimizing ? "Optimize Ediliyor..." : "Optimize Et"}</span>
              </button>
            </div>
          </div>

          {/* Optimizasyon Başarı Bildirimi */}
          {optResult && (
            <div className="rounded-xl p-3 bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center justify-between animate-fade">
              <div className="flex items-center gap-2">
                <CheckCircle2 size={15} className="text-emerald-400 shrink-0" />
                <span>{optResult.message || "Dağıtık depolama ve indeksler başarıyla optimize edildi."}</span>
              </div>
              <span className="font-data font-bold text-xs text-emerald-400">Durum: Tamamlandı</span>
            </div>
          )}

          {/* Yükleniyor Durumu */}
          {loading && databases.length === 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
              <SkeletonCard /><SkeletonCard /><SkeletonCard />
            </div>
          )}

          {/* 2. SEKME 1: CANLI VERİ AKIŞ HATLARI & SAĞLAYICILAR */}
          {activeTab === "sources" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between px-1">
                <span className="text-xs font-bold tracking-wider uppercase text-zinc-400 font-data">
                  Aktif Veri Besleme Sağlayıcıları (Data Ingestion Providers)
                </span>
                <span className="text-xs text-zinc-500 font-data">
                  Protokol: WebSocket / REST / NATS · Yüksek Güvenilirlik
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
                {dataSources.map((src) => {
                  const isMarket = src.category === "MARKET_DATA";
                  const isKap = src.category === "DISCLOSURES";
                  const isMacro = src.category === "MACRO";
                  const isDeriv = src.category === "DERIVATIVES";
                  const isFund = src.category === "FUNDAMENTAL";

                  const tagClr = isMarket 
                    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" 
                    : isKap 
                    ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                    : isMacro 
                    ? "bg-cyan-500/10 text-cyan-400 border-cyan-500/20"
                    : isDeriv 
                    ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
                    : isFund 
                    ? "bg-blue-500/10 text-blue-400 border-blue-500/20"
                    : "bg-rose-500/10 text-rose-400 border-rose-500/20";

                  const iconClr = isMarket ? "#00e5a0" : isKap ? "#f59e0b" : isMacro ? "#00c8ff" : isDeriv ? "#a855f7" : "#38bdf8";

                  return (
                    <div
                      key={src.id}
                      className="rounded-xl p-4 space-y-3.5 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg hover:border-white/[0.15] transition-all"
                      style={{ borderTop: `3px solid ${iconClr}` }}
                    >
                      {/* Üst Başlık & Durum */}
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2.5">
                          <div
                            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                            style={{ background: `${iconClr}15`, color: iconClr }}
                          >
                            {isMarket ? <TrendingUp size={16} /> : isKap ? <FileText size={16} /> : isMacro ? <Globe size={16} /> : isDeriv ? <Zap size={16} /> : <BarChart3 size={16} />}
                          </div>
                          <div>
                            <h3 className="text-sm font-bold text-white leading-tight">{src.name}</h3>
                            <span className={`inline-block mt-0.5 text-xs font-semibold px-1.5 py-0.2 rounded border ${tagClr}`}>
                              {src.type}
                            </span>
                          </div>
                        </div>

                        <span className="flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-data">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                          <span>{src.status}</span>
                        </span>
                      </div>

                      {/* Açıklama */}
                      <p className="text-xs text-zinc-300 leading-relaxed bg-zinc-950/40 p-2.5 rounded-lg border border-white/[0.04]">
                        {src.description}
                      </p>

                      {/* İstatistik Tablosu */}
                      <div className="grid grid-cols-2 gap-2 text-xs font-data">
                        <div className="p-2 rounded-lg bg-zinc-950/50 border border-white/[0.04]">
                          <div className="text-xs text-zinc-400 uppercase font-semibold">Frekans</div>
                          <div className="font-bold text-zinc-100 mt-0.5 truncate">{src.frequency}</div>
                        </div>
                        <div className="p-2 rounded-lg bg-zinc-950/50 border border-white/[0.04]">
                          <div className="text-xs text-zinc-400 uppercase font-semibold">Protokol</div>
                          <div className="font-bold text-zinc-100 mt-0.5 truncate">{src.protocol}</div>
                        </div>
                        <div className="p-2 rounded-lg bg-zinc-950/50 border border-white/[0.04]">
                          <div className="text-xs text-zinc-400 uppercase font-semibold">Kapsam</div>
                          <div className="font-bold text-zinc-100 mt-0.5 truncate">{src.coverage}</div>
                        </div>
                        <div className="p-2 rounded-lg bg-zinc-950/50 border border-white/[0.04]">
                          <div className="text-xs text-zinc-400 uppercase font-semibold">Hacim / Kayıt</div>
                          <div className="font-bold text-emerald-300 mt-0.5 truncate">{src.records_count}</div>
                        </div>
                      </div>

                      {/* Alt Güvenilirlik & Gecikme Çubuğu */}
                      <div className="pt-2 border-t border-white/[0.05] flex items-center justify-between text-xs font-data text-zinc-400">
                        <div className="flex items-center gap-1.5">
                          <ShieldCheck size={13} className="text-emerald-400" />
                          <span>Güvenilirlik: <strong className="text-zinc-200">%{src.reliability_pct.toFixed(1)}</strong></span>
                        </div>
                        <div className="flex items-center gap-1">
                          <Clock size={12} className="text-cyan-400" />
                          <span>Gecikme: <strong className="text-zinc-200">{src.latency_ms} ms</strong></span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 3. SEKME 2: DAĞITIK DEPOLAMA KATMANI (STORAGE TOPOLOGY) */}
          {activeTab === "storage" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between px-1">
                <span className="text-xs font-bold tracking-wider uppercase text-zinc-400 font-data">
                  Veritabanı Kümesi & Depolama Topolojisi (6 Storage Engines)
                </span>
                <span className="text-xs text-zinc-500 font-data">
                  PostgreSQL + TimescaleDB · ClickHouse · QuestDB · DuckDB · Redis · NATS
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
                {databases.map((db, idx) => {
                  const isCh = db.type.includes("Columnar");
                  const isPg = db.type.includes("Relational");
                  const isRedis = db.type.includes("In-Memory");
                  const isDuck = db.name.includes("DuckDB");
                  const isQuest = db.name.includes("QuestDB");

                  const accentClr = isCh 
                    ? "#00e5a0" 
                    : isPg 
                    ? "#00c8ff" 
                    : isRedis 
                    ? "#ff4466" 
                    : isDuck 
                    ? "#eab308" 
                    : isQuest 
                    ? "#f59e0b" 
                    : "#a855f7";

                  return (
                    <div
                      key={idx}
                      className="rounded-xl p-4 space-y-3.5 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg hover:border-white/[0.15] transition-all"
                      style={{ borderTop: `3px solid ${accentClr}` }}
                    >
                      {/* Üst Bilgi */}
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2.5">
                          <div
                            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                            style={{ background: `${accentClr}15`, color: accentClr }}
                          >
                            {isCh ? <Database size={16} /> : isPg ? <Server size={16} /> : isRedis ? <Zap size={16} /> : isDuck ? <Cpu size={16} /> : <HardDrive size={16} />}
                          </div>
                          <div>
                            <h3 className="text-sm font-bold text-white leading-tight">{db.name}</h3>
                            <p className="text-xs text-zinc-400 font-data">{db.type}</p>
                          </div>
                        </div>

                        <span
                          className="text-xs font-bold px-2 py-0.5 rounded-full font-data shrink-0"
                          style={{ background: `${accentClr}15`, color: accentClr, border: `1px solid ${accentClr}30` }}
                        >
                          {db.status} ({db.latency_ms} ms)
                        </span>
                      </div>

                      {/* Rol */}
                      <p className="text-xs text-zinc-300 leading-relaxed bg-zinc-950/40 p-2.5 rounded-lg border border-white/[0.04]">
                        {db.role}
                      </p>

                      {/* İstatistikler */}
                      <div className="grid grid-cols-2 gap-2 text-xs font-data">
                        <div className="p-2.5 rounded-lg bg-zinc-950/50 border border-white/[0.04]">
                          <div className="text-xs text-zinc-400 uppercase font-semibold">Disk / RAM Boyutu</div>
                          <div className="font-bold text-zinc-100 mt-0.5">{db.size}</div>
                        </div>
                        <div className="p-2.5 rounded-lg bg-zinc-950/50 border border-white/[0.04]">
                          <div className="text-xs text-zinc-400 uppercase font-semibold">Toplam Kayıt / Dosya</div>
                          <div className="font-bold text-emerald-300 mt-0.5">{db.rows_count}</div>
                        </div>
                      </div>

                      {/* Önemli Tablolar */}
                      {db.tables && db.tables.length > 0 && (
                        <div className="space-y-1.5 pt-1">
                          <div className="text-xs font-bold uppercase tracking-wider text-zinc-400 font-data">
                            Aktif Tablolar & Başlıklar
                          </div>
                          <div className="space-y-1">
                            {db.tables.map((tbl, tIdx) => (
                              <div
                                key={tIdx}
                                className="flex items-center justify-between p-1.5 rounded bg-zinc-950/40 border border-white/[0.03] text-xs font-data"
                              >
                                <span className="text-zinc-300 font-medium truncate max-w-[170px]">{tbl.name}</span>
                                <div className="flex items-center gap-2 text-zinc-400 text-xs shrink-0">
                                  <span>{tbl.rows}</span>
                                  <span className="text-zinc-500 font-semibold">{tbl.size}</span>
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
          )}

        </div>
      </div>
    </ErrorBoundary>
  );
}
