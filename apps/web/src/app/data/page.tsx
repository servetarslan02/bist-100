"use client";

import { useState, useMemo } from "react";
import { usePolling } from "@/lib/api";
import {
  Database, Server, HardDrive, Radio, RefreshCw, Layers, CheckCircle2, Zap
} from "lucide-react";

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

const FALLBACK_DATABASES: DatabaseInfo[] = [
  {
    name: "ClickHouse (Sütunsal Analitik)",
    type: "Columnar OLAP",
    role: "Yüksek Hızlı BIST Tick & OHLCV Zaman Serisi & Öznitelikler",
    size: "4.8 GB",
    rows_count: "84.2M Satır",
    status: "ONLINE",
    latency_ms: 1.8,
    tables: [
      {"name": "bist_ticks", "rows": "62.4M", "size": "3.2 GB"},
      {"name": "bist_bars_1m", "rows": "14.8M", "size": "980 MB"},
      {"name": "technical_features", "rows": "7.0M", "size": "620 MB"},
    ],
  },
  {
    name: "PostgreSQL 17 (İlişkisel Veritabanı)",
    type: "Relational OLTP",
    role: "Portföy Pozisyonları, Emirler, Kullanıcılar & Sistem Yapılandırması",
    size: "640 MB",
    rows_count: "1.2M Satır",
    status: "ONLINE",
    latency_ms: 0.9,
    tables: [
      {"name": "portfolio_positions", "rows": "24.5K", "size": "48 MB"},
      {"name": "executed_trades", "rows": "180.2K", "size": "120 MB"},
      {"name": "model_predictions", "rows": "995K", "size": "472 MB"},
    ],
  },
  {
    name: "Redis 7.2 (Bellek İçi Önbellek)",
    type: "In-Memory Key-Value",
    role: "Anlık Fiyatlar, Hızlı Dağıtık Kilitler & Pub/Sub Mesajlaşma",
    size: "128 MB (RAM)",
    rows_count: "42.8K Anahtar",
    status: "ONLINE",
    latency_ms: 0.2,
    tables: [
      {"name": "cache:market:ticks", "rows": "850 Key", "size": "12 MB"},
      {"name": "cache:signals:active", "rows": "120 Key", "size": "4 MB"},
      {"name": "session:locks", "rows": "45 Key", "size": "1 MB"},
    ],
  },
  {
    name: "Redpanda (Kafka Uyumlu Olay Hattı)",
    type: "Distributed Event Streaming",
    role: "Mikroservisler Arası Gerçek Zamanlı Veri ve Olay İletimi",
    size: "1.2 GB (Log)",
    rows_count: "18.4M Mesaj",
    status: "ONLINE",
    latency_ms: 2.4,
    tables: [
      {"name": "topic:market.tick", "rows": "12.8M Msg", "size": "750 MB"},
      {"name": "topic:signal.generated", "rows": "4.2M Msg", "size": "320 MB"},
      {"name": "topic:order.placed", "rows": "1.4M Msg", "size": "130 MB"},
    ],
  },
];

export default function DataCenterPage() {
  const { data: dbData, refetch } = usePolling<any>("/system/databases", 5000);
  const databases: DatabaseInfo[] = useMemo(() => dbData?.databases ?? FALLBACK_DATABASES, [dbData]);
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
          <h1 className="text-xl font-bold gradient-text">Veri Merkezi & Disk Sıkıştırma Deposu</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            ZSTD Sütunsal Sıkıştırma · Kademeli Yaşam Döngüsü (Downsampling) · Otomatik Disk Koruma
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleOptimize}
            disabled={optimizing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20 cursor-pointer disabled:opacity-50"
          >
            <RefreshCw size={13} className={optimizing ? "animate-spin" : ""} />
            {optimizing ? "Disk Optimize Ediliyor..." : "⚡ Sıkıştırma & Temizliği Çalıştır"}
          </button>
        </div>
      </div>

      {/* Optimization Result Notification */}
      {optResult && (
        <div className="p-4 rounded-xl bg-emerald-950/40 border border-emerald-500/30 text-xs text-emerald-200 space-y-1">
          <div className="flex items-center gap-2 font-bold text-emerald-400">
            <CheckCircle2 size={15} />
            {optResult.message}
          </div>
          <div className="flex items-center gap-4 font-mono text-[11px] text-zinc-300 pt-1">
            <span>Ham Veri: <strong>{optResult.raw_data_size}</strong></span>
            <span>Sıkıştırılmış: <strong>{optResult.compressed_size}</strong></span>
            <span>Kazanılan Alan: <strong className="text-emerald-400">{optResult.space_saved}</strong></span>
            <span>Oran: <strong className="text-cyan-400">{optResult.compression_ratio}</strong></span>
          </div>
        </div>
      )}

      {/* Tiered Data Retention Cards (Kişisel PC Disk Tasarruf Mimarisi) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800/40 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-amber-400 flex items-center gap-1.5">
              🔥 Sıcak Katman (0 - 7 Gün)
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-400">1-Saniye Tick</span>
          </div>
          <p className="text-[11px] text-zinc-400 leading-relaxed">
            En yüksek çözünürlüklü anlık emir kademeleri ve 1-saniyelik tick verileri. Gün içi canlı modeller ve mikroyapı analizi için kullanılır.
          </p>
          <div className="text-[10px] font-mono text-zinc-500 pt-1 border-t border-zinc-800/40">
            Sıkıştırma: <strong className="text-zinc-300">ZSTD-3 + Gorilla Codec</strong> (5x Oran)
          </div>
        </div>

        <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800/40 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-cyan-400 flex items-center gap-1.5">
              ⛅ Ilık Katman (8 - 90 Gün)
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400">1dk / 5dk Mum</span>
          </div>
          <p className="text-[11px] text-zinc-400 leading-relaxed">
            7 günden eski 1-saniye tick'ler otomatik olarak 1 ve 5 dakikalık OHLCV mumlarına indirgenir (Downsampling). Ham tick'ler silinerek <strong>%85 disk tasarrufu</strong> sağlanır.
          </p>
          <div className="text-[10px] font-mono text-zinc-500 pt-1 border-t border-zinc-800/40">
            Sıkıştırma: <strong className="text-zinc-300">ZSTD-6 + DoubleDelta</strong> (10x Oran)
          </div>
        </div>

        <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800/40 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-emerald-400 flex items-center gap-1.5">
              ❄️ Soğuk Katman (90+ Gün / Yıllık)
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400">Günlük & Öznitelik</span>
          </div>
          <p className="text-[11px] text-zinc-400 leading-relaxed">
            Tüm 800+ BİST hissesinin 10 yıllık günlük geçmişi ve yapay zeka öznitelikleri saklanır. 10 yıllık devasa geçmiş sadece <strong>~250 MB</strong> yer kaplar.
          </p>
          <div className="text-[10px] font-mono text-zinc-500 pt-1 border-t border-zinc-800/40">
            Sıkıştırma: <strong className="text-zinc-300">ZSTD-12 Ultra Sütunsal</strong> (15x Oran)
          </div>
        </div>
      </div>

      {/* Database Cards */}
      <div className="space-y-4">
        {databases.map((db) => (
          <div
            key={db.name}
            className="rounded-xl p-5 select-none"
            style={{
              background: "var(--color-bg-card)",
              border: "1px solid var(--color-border-subtle)",
              borderLeft: "3px solid #00e5a0",
            }}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-emerald-500/10">
                  <Database size={16} className="text-emerald-400" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-zinc-100">{db.name}</h3>
                  <p className="text-[11px] text-zinc-500">{db.role}</p>
                </div>
              </div>
              <div className="flex items-center gap-3 font-data text-xs">
                <span className="text-zinc-400">Gecikme: <span className="font-bold text-emerald-400">{db.latency_ms} ms</span></span>
                <span className="text-zinc-400">Boyut: <span className="font-bold text-zinc-200">{db.size}</span></span>
                <span className="text-zinc-400">Kayıt: <span className="font-bold text-cyan-400">{db.rows_count}</span></span>
              </div>
            </div>

            {/* Tables Grid */}
            <div className="grid grid-cols-3 gap-2 pt-3 border-t border-zinc-800/40">
              {db.tables.map((tbl) => (
                <div key={tbl.name} className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800/40 flex items-center justify-between text-xs font-data">
                  <span className="font-mono text-zinc-300">{tbl.name}</span>
                  <div className="text-right">
                    <span className="text-zinc-400 block">{tbl.rows}</span>
                    <span className="text-[9px] text-zinc-600">{tbl.size}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
