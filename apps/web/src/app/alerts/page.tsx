"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling } from "@/lib/api";
import {
  Bell, AlertTriangle, AlertCircle, Info, ShieldAlert, CheckCircle2,
  Filter, Clock, Check
} from "lucide-react";
import { SkeletonList, SkeletonCard, SkeletonTable, SkeletonChart } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

interface AlertItem {
  id: string;
  title: string;
  message: string;
  severity: "CRITICAL" | "WARNING" | "INFO";
  category: "RISK" | "SIGNAL" | "SYSTEM" | "VOLATILITY";
  timestamp: string;
  ticker?: string;
  read: boolean;
}

const FALLBACK_ALERTS: AlertItem[] = [
  {
    id: "1",
    title: "Yüksek Volatilite & Hacim Patlaması",
    message: "THYAO hissesinde 5 dakikalık ortalama hacmin 3.8 katı gerçekleşti. Olası kırılım sinyali.",
    severity: "CRITICAL",
    category: "VOLATILITY",
    timestamp: "Canlı Alarm",
    ticker: "THYAO",
    read: false,
  },
  {
    id: "2",
    title: "Portföy VaR Sınırı Normal",
    message: "Günlük %95 Parametrik VaR seviyesi (%2.8) güvenli sınır içerisinde. Risk toleransı %4.5.",
    severity: "WARNING",
    category: "RISK",
    timestamp: "Canlı Alarm",
    read: false,
  },
  {
    id: "3",
    title: "Yeni Yüksek Güvenilirlikli Sinyal Üretildi",
    message: "GARAN için Momentum & Breakout modeli tarafından 88 skorlu AL sinyali üretildi.",
    severity: "INFO",
    category: "SIGNAL",
    timestamp: "Canlı Alarm",
    ticker: "GARAN",
    read: true,
  },
  {
    id: "4",
    title: "KAP Özel Durum Açıklaması",
    message: "ASELS savunma sanayii başkanlığı ile 120M $ tutarında yeni sözleşme imzaladı.",
    severity: "INFO",
    category: "SIGNAL",
    timestamp: "Canlı Alarm",
    ticker: "ASELS",
    read: true,
  },
  {
    id: "5",
    title: "Veritabanı Senkronizasyon Başarılı",
    message: "ClickHouse ve PostgreSQL arası son 1 saatlik tick verileri kayıpsız eşitlendi.",
    severity: "INFO",
    category: "SYSTEM",
    timestamp: "Canlı Alarm",
    read: true,
  },
];

export default function AlertsPage() {
  const router = useRouter();
  const { data: alertsData } = usePolling<any>("/system/alerts", 5000);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<string>("ALL");

  const alerts: AlertItem[] = useMemo(() => {
    const raw = alertsData?.alerts ?? FALLBACK_ALERTS;
    return raw.map((a: AlertItem) => ({
      ...a,
      read: a.read || readIds.has(a.id)
    }));
  }, [alertsData, readIds]);

  const filtered = filter === "ALL" 
    ? alerts 
    : alerts.filter(a => a.severity === filter || a.category === filter);

  return (
    <ErrorBoundary name="alerts">
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Alarm & Risk Bildirim Merkezi</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Anlık Volatilite Alarmları · Stop-Loss / Take-Profit Tetikleyicileri · Risk Limit İhlalleri
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setReadIds(new Set(alerts.map(a => a.id)))}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-zinc-900 border border-zinc-800 text-zinc-300 hover:text-white cursor-pointer"
          >
            <Check size={13} />
            Tümünü Okundu İşaretle
          </button>
        </div>
      </div>

      {/* Alert List */}
      <div className="space-y-3">
        {!alertsData && (
          <SkeletonList count={5} />
        )}
        {alertsData && filtered.map((alert) => {
          const isCrit = alert.severity === "CRITICAL";
          const isWarn = alert.severity === "WARNING";
          const borderClr = isCrit ? "#ff4466" : isWarn ? "#ffaa00" : "#00c8ff";
          const Icon = isCrit ? ShieldAlert : isWarn ? AlertTriangle : Info;

          return (
            <div
              key={alert.id}
              onClick={() => alert.ticker && router.push(`/asset?ticker=${alert.ticker}`)}
              className={`rounded-xl p-4 transition-all duration-150 select-none flex items-start gap-3.5 ${alert.ticker ? "cursor-pointer hover:bg-white/[0.04] hover:scale-[1.005]" : ""}`}
              style={{
                background: "var(--color-bg-card)",
                border: "1px solid var(--color-border-subtle)",
                borderLeft: `3px solid ${borderClr}`,
                opacity: alert.read ? 0.75 : 1,
              }}
            >
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
                style={{ background: `${borderClr}15` }}
              >
                <Icon size={16} style={{ color: borderClr }} />
              </div>

              <div className="flex-1">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-xs font-bold text-zinc-100">{alert.title}</h3>
                    {alert.ticker && (
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-zinc-800 text-emerald-400">
                        {alert.ticker}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 text-[10px] text-zinc-500 font-data">
                    <Clock size={11} />
                    {alert.timestamp}
                  </div>
                </div>

                <p className="text-[11px] leading-relaxed text-zinc-400">{alert.message}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
    </ErrorBoundary>
  );
}
