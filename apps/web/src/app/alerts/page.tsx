"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { usePolling } from "@/lib/api";
import { useIstanbulClock } from "@/lib/time";
import {
  Bell, AlertTriangle, Info, ShieldAlert, CheckCircle2,
  Clock, Check, Search, RefreshCw, Zap, Database, CheckCheck
} from "lucide-react";
import { SkeletonList } from "@/components/ui/Skeleton";
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

const ALERT_FILTERS = [
  { id: "ALL", label: "Tüm Alarmlar" },
  { id: "CRITICAL", label: "Kritik Seviye" },
  { id: "SIGNAL", label: "Model Sinyalleri" },
  { id: "VOLATILITY", label: "Volatilite & Hacim" },
  { id: "RISK", label: "Portföy & Risk" },
  { id: "SYSTEM", label: "Sistem Sağlığı" },
];

const LOCAL_STORAGE_KEY_READ_IDS = "alpha_alerts_read_ids";
const LOCAL_STORAGE_KEY_ALL_READ_TS = "alpha_alerts_all_read_ts";

export default function AlertsPage() {
  const router = useRouter();
  const clock = useIstanbulClock();
  const { data: alertsData, loading, refetch } = usePolling<{ alerts: AlertItem[]; count: number } | null>("/system/alerts", 4000);
  
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [allReadTs, setAllReadTs] = useState<string>("");
  const [filter, setFilter] = useState<string>("ALL");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [isMarkingAll, setIsMarkingAll] = useState(false);

  // 1. LocalStorage'dan kalıcı okundu bilgilerini yükle
  useEffect(() => {
    try {
      const savedIds = localStorage.getItem(LOCAL_STORAGE_KEY_READ_IDS);
      if (savedIds) {
        const parsed = JSON.parse(savedIds);
        if (Array.isArray(parsed)) {
          setReadIds(new Set(parsed));
        }
      }
      const savedTs = localStorage.getItem(LOCAL_STORAGE_KEY_ALL_READ_TS);
      if (savedTs) {
        setAllReadTs(savedTs);
      }
    } catch {
      // LocalStorage erişim hatası olursa yut
    }
  }, []);

  const rawAlerts: AlertItem[] = useMemo(() => alertsData?.alerts ?? [], [alertsData]);

  // Alarmları yerel ve sunucu okundu durumlarıyla harmanla
  const alerts: AlertItem[] = useMemo(() => {
    return rawAlerts.map((a: AlertItem) => {
      const isReadLocally = readIds.has(a.id);
      const isReadByTs = Boolean(allReadTs && a.timestamp <= allReadTs);
      return {
        ...a,
        read: a.read || isReadLocally || isReadByTs,
      };
    });
  }, [rawAlerts, readIds, allReadTs]);

  // Sayaçlar ve KPI İstatistikleri
  const stats = useMemo(() => {
    const counts = {
      total: alerts.length,
      unread: 0,
      critical: 0,
      signal: 0,
      volatility: 0,
      risk: 0,
      system: 0,
    };

    for (const a of alerts) {
      if (!a.read) counts.unread++;
      if (a.severity === "CRITICAL") counts.critical++;
      if (a.category === "SIGNAL") counts.signal++;
      if (a.category === "VOLATILITY") counts.volatility++;
      if (a.category === "RISK") counts.risk++;
      if (a.category === "SYSTEM") counts.system++;
    }

    return counts;
  }, [alerts]);

  // Filtreleme & Arama
  const filtered = useMemo(() => {
    return alerts.filter((a) => {
      if (filter === "CRITICAL") {
        if (a.severity !== "CRITICAL") return false;
      } else if (filter !== "ALL") {
        if (a.category !== filter) return false;
      }

      if (searchTerm) {
        const q = searchTerm.toLowerCase().trim();
        const matchTitle = a.title.toLowerCase().includes(q);
        const matchMsg = a.message.toLowerCase().includes(q);
        const matchTicker = a.ticker?.toLowerCase().includes(q) ?? false;
        return matchTitle || matchMsg || matchTicker;
      }

      return true;
    });
  }, [alerts, filter, searchTerm]);

  // Tekil okundu işaretleme (LocalStorage + Backend)
  const toggleRead = useCallback(async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setReadIds((prev) => {
      const next = new Set(prev);
      const isCurrentlyRead = next.has(id);
      if (isCurrentlyRead) {
        next.delete(id);
      } else {
        next.add(id);
      }
      try {
        localStorage.setItem(LOCAL_STORAGE_KEY_READ_IDS, JSON.stringify(Array.from(next)));
      } catch {}
      return next;
    });

    // Backend'e de bildir
    try {
      await fetch("/api/v1/system/alerts/read", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ alert_ids: [id] }),
      });
    } catch {}
  }, []);

  // Tümünü Oku (LocalStorage + Backend kalıcı kaydı)
  const markAllRead = useCallback(async () => {
    setIsMarkingAll(true);
    const nowTimeStr = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const currentAlertIds = alerts.map((a) => a.id);

    // 1. Yerel state'i güncelle
    const updatedIds = new Set([...Array.from(readIds), ...currentAlertIds]);
    setReadIds(updatedIds);
    setAllReadTs(nowTimeStr);

    // 2. LocalStorage'a kalıcı olarak kaydet
    try {
      localStorage.setItem(LOCAL_STORAGE_KEY_READ_IDS, JSON.stringify(Array.from(updatedIds)));
      localStorage.setItem(LOCAL_STORAGE_KEY_ALL_READ_TS, nowTimeStr);
    } catch {}

    // 3. Backend'e bildir
    try {
      await fetch("/api/v1/system/alerts/read-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
    } catch {}

    setTimeout(() => {
      setIsMarkingAll(false);
      refetch();
    }, 400);
  }, [alerts, readIds, refetch]);

  return (
    <ErrorBoundary name="alerts">
      <div className="p-4 space-y-4 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
        {/* ULTRA KOMPAKT HEADER (~45px Toolbar Standardı) */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 rounded-xl bg-zinc-900/80 border border-zinc-800 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              <h1 className="text-sm font-bold text-zinc-100 tracking-tight">Canlı Alarmlar & Risk Radarı</h1>
            </div>

            <div className="h-4 w-px bg-zinc-800 hidden sm:block" />

            {stats.unread > 0 ? (
              <span className="px-2.5 py-0.5 rounded-md text-xs font-bold bg-red-500/15 text-red-400 border border-red-500/30 animate-pulse">
                {stats.unread} Okunmamış Alarm
              </span>
            ) : (
              <span className="px-2.5 py-0.5 rounded-md text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                <CheckCircle2 size={12} />
                Tümü Okundu
              </span>
            )}

            <div className="hidden lg:flex items-center gap-2 text-xs font-mono text-zinc-400 bg-zinc-950 px-2.5 py-1 rounded-md border border-zinc-800">
              <Clock size={12} className="text-emerald-400" />
              <span>{clock.time || "--:--:--"}</span>
              <span className="text-[10px] text-zinc-500">TSİ</span>
            </div>
          </div>

          {/* Aksiyon Araçları */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-zinc-950 border border-zinc-800 text-xs">
              <Search size={13} className="text-zinc-500" />
              <input
                type="text"
                placeholder="Alarm veya hisse ara..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="bg-transparent text-zinc-200 focus:outline-none w-32 sm:w-44 text-xs"
              />
            </div>

            <button
              onClick={markAllRead}
              disabled={isMarkingAll || stats.unread === 0}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                stats.unread === 0
                  ? "bg-zinc-800/60 border border-zinc-800 text-zinc-500 cursor-not-allowed"
                  : "bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/40 text-emerald-300 hover:text-emerald-100 shadow-sm"
              }`}
              title="Tüm Alarmları Okundu Olarak İşaretle (Kalıcı)"
            >
              <CheckCheck size={14} className={isMarkingAll ? "animate-spin" : ""} />
              <span>{isMarkingAll ? "Kaydediliyor..." : "Tümünü Oku"}</span>
            </button>

            <button
              onClick={() => refetch()}
              className="p-1.5 rounded-lg bg-zinc-950 border border-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer"
              title="Yenile"
            >
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* KOMPAKT KPI ÖZET KARTLARI */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          <div className="p-2.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold text-zinc-400">Toplam Alarm</div>
              <div className="text-sm font-bold text-zinc-100 mt-0.5">{stats.total} Bildirim</div>
            </div>
            <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
              <Bell size={15} />
            </div>
          </div>

          <div className="p-2.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold text-red-400">Kritik Risk & Volatilite</div>
              <div className="text-sm font-bold text-red-400 mt-0.5">{stats.critical} Kritik</div>
            </div>
            <div className="w-8 h-8 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center justify-center text-red-400">
              <ShieldAlert size={15} />
            </div>
          </div>

          <div className="p-2.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold text-emerald-400">Model Sinyalleri</div>
              <div className="text-sm font-bold text-emerald-400 mt-0.5">{stats.signal} Sinyal</div>
            </div>
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <Zap size={15} />
            </div>
          </div>

          <div className="p-2.5 rounded-xl bg-zinc-900/60 border border-zinc-800/80 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold text-purple-400">Altyapı Durumu</div>
              <div className="text-sm font-bold text-purple-400 mt-0.5">20/20 Aktif</div>
            </div>
            <div className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
              <Database size={15} />
            </div>
          </div>
        </div>

        {/* FİLTRE ÇUBUĞU */}
        <div className="flex gap-2 overflow-x-auto pb-1 custom-scrollbar">
          {ALERT_FILTERS.map((t) => {
            const active = filter === t.id;
            let count = stats.total;
            if (t.id === "CRITICAL") count = stats.critical;
            else if (t.id === "SIGNAL") count = stats.signal;
            else if (t.id === "VOLATILITY") count = stats.volatility;
            else if (t.id === "RISK") count = stats.risk;
            else if (t.id === "SYSTEM") count = stats.system;

            return (
              <button
                key={t.id}
                onClick={() => setFilter(t.id)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all duration-150 cursor-pointer ${
                  active
                    ? "bg-zinc-100 text-zinc-900 shadow-md"
                    : "bg-zinc-900/80 text-zinc-400 hover:text-zinc-200 border border-zinc-800"
                }`}
              >
                <span>{t.label}</span>
                <span
                  className={`px-1.5 py-0.2 rounded-full text-xs font-bold ${
                    active ? "bg-zinc-900 text-zinc-100" : "bg-zinc-800 text-zinc-400"
                  }`}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Loading State */}
        {loading && alerts.length === 0 && (
          <SkeletonList count={6} />
        )}

        {/* Empty State */}
        {alerts.length === 0 && !loading && (
          <div className="text-center py-12 text-zinc-400 text-xs font-semibold rounded-xl bg-zinc-900/30 border border-zinc-800/50">
            Aktif alarm veya bildirim bulunamadı.
          </div>
        )}

        {/* Filtered Empty State */}
        {filtered.length === 0 && alerts.length > 0 && (
          <div className="text-center py-12 text-zinc-400 text-xs font-semibold rounded-xl bg-zinc-900/30 border border-zinc-800/50">
            Seçilen filtreye uygun alarm bulunamadı.
          </div>
        )}

        {/* ALARM LİSTESİ (12-14px Net Tipografi) */}
        <div className="space-y-2.5">
          {filtered.map((alert) => {
            const isCrit = alert.severity === "CRITICAL";
            const isWarn = alert.severity === "WARNING";
            const borderClr = isCrit ? "#ff4466" : isWarn ? "#ffaa00" : "#00c8ff";
            const Icon = isCrit ? ShieldAlert : isWarn ? AlertTriangle : (alert.category === "SYSTEM" ? Database : Info);

            return (
              <div
                key={alert.id}
                onClick={() => alert.ticker && router.push(`/asset?symbol=${alert.ticker}`)}
                className={`rounded-xl p-3.5 transition-all duration-150 select-none flex items-start gap-3.5 group ${
                  alert.ticker ? "cursor-pointer hover:bg-zinc-900/90" : "bg-zinc-900/50"
                } border border-zinc-800/80 hover:border-zinc-700`}
                style={{
                  background: alert.read ? "rgba(24, 24, 27, 0.45)" : "rgba(24, 24, 27, 0.85)",
                  borderLeft: `4px solid ${borderClr}`,
                  opacity: alert.read ? 0.75 : 1,
                }}
              >
                {/* İkon */}
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
                  style={{ background: `${borderClr}18` }}
                >
                  <Icon size={18} style={{ color: borderClr }} />
                </div>

                {/* İçerik */}
                <div className="flex-1 space-y-1.5">
                  <div className="flex items-center justify-between flex-wrap gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className="text-xs font-bold px-2 py-0.5 rounded uppercase tracking-wide"
                        style={{ background: `${borderClr}15`, color: borderClr }}
                      >
                        {alert.severity}
                      </span>
                      <h3 className="text-sm font-bold text-zinc-100 group-hover:text-cyan-400 transition-colors">
                        {alert.title}
                      </h3>
                      {alert.ticker && (
                        <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-zinc-800 text-emerald-400 border border-zinc-700">
                          {alert.ticker}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2.5 text-xs text-zinc-400 font-mono">
                      <div className="flex items-center gap-1">
                        <Clock size={12} />
                        <span>{alert.timestamp}</span>
                      </div>
                      
                      <button
                        onClick={(e) => toggleRead(alert.id, e)}
                        className={`flex items-center gap-1 px-2 py-0.5 rounded-md border text-xs font-semibold transition-colors cursor-pointer ${
                          alert.read 
                            ? "bg-zinc-800/80 border-zinc-700 text-emerald-400" 
                            : "bg-emerald-500/10 border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20"
                        }`}
                        title={alert.read ? "Okundu (İşareti Kaldır)" : "Okundu Olarak İşaretle"}
                      >
                        <Check size={13} />
                        <span>{alert.read ? "Okundu" : "Okundu Yap"}</span>
                      </button>
                    </div>
                  </div>

                  <p className="text-xs leading-relaxed text-zinc-300 font-normal">
                    {alert.message}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </ErrorBoundary>
  );
}
