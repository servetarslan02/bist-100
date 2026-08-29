"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { usePolling, type MarketState, type Signal, type SystemStatus } from "@/lib/api";
import type { SignalItem, SignalResponse } from "@/types/api";
import { useIstanbulClock } from "@/lib/time";
import {
  TrendingUp, TrendingDown, Minus,
  Activity, BarChart2, Target as TargetIcon, Shield,
  Wifi, WifiOff, ChevronUp, ChevronDown, CheckCircle,
  Clock, Radar as RadarIcon, ArrowRight, Search
} from "lucide-react";
import { SkeletonStat, SkeletonTable, SkeletonList } from "@/components/ui/Skeleton";

// ---------------------------------------------
// Component Helpers
// ---------------------------------------------
interface SectionHeaderProps {
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>;
  title: string;
  sub?: string;
  accent: string;
}

function SectionHeader({ icon: Icon, title, sub, accent }: SectionHeaderProps) {
  return (
    <div className="flex items-center justify-between px-5 py-3" style={{ borderBottom: "1px solid var(--color-border-subtle)" }}>
      <div className="flex items-center gap-2.5">
        <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: `${accent}15` }}>
          <Icon size={13} style={{ color: accent }} />
        </div>
        <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>
          {title}
        </h2>
      </div>
      {sub && <span className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>{sub}</span>}
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: number | string;
  suffix?: string;
  decimals?: number;
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>;
  accent: string;
  trend?: "up" | "down" | "neutral";
}

function StatCard({ label, value, suffix = "", decimals = 2, icon: Icon, accent, trend }: StatCardProps) {
  return (
    <div className="rounded-xl p-4 flex flex-col gap-3 relative overflow-hidden group"
      style={{
        background: "var(--color-bg-card)",
        border: "1px solid var(--color-border-subtle)"
      }}>
      <div className="absolute -right-6 -top-6 w-20 h-20 rounded-full blur-3xl opacity-10 transition-opacity group-hover:opacity-20" style={{ background: accent }} />
      <div className="flex items-center justify-between">
        <span className="text-[10.5px] uppercase tracking-wider font-semibold" style={{ color: "var(--color-text-secondary)" }}>
          {label}
        </span>
        <Icon size={14} style={{ color: "var(--color-text-muted)" }} />
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold font-data tracking-tight" style={{ color: "var(--color-text-primary)" }}>
          {typeof value === 'number' ? value.toFixed(decimals) : value}{suffix}
        </span>
        {trend && (
          <span className="flex items-center text-[10px] font-bold font-data" style={{ color: trend === "up" ? "#00e5a0" : trend === "down" ? "#ff4466" : "var(--color-text-muted)" }}>
            {trend === "up" ? <ChevronUp size={12} strokeWidth={3} /> : trend === "down" ? <ChevronDown size={12} strokeWidth={3} /> : <Minus size={12} strokeWidth={3} />}
          </span>
        )}
      </div>
    </div>
  );
}

function ScoreBar({ score }: { score: number }) {
  let color = "#00e5a0";
  if (score < 40) color = "#ff4466";
  else if (score < 70) color = "#ffaa00";

  return (
    <div className="flex items-center justify-end gap-2">
      <span className="text-[12px] font-data font-bold" style={{ color }}>{score}</span>
      <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.1)" }}>
        <div className="h-full rounded-full transition-all duration-700 ease-out" style={{ width: `${Math.min(100, Math.max(0, score))}%`, background: color }} />
      </div>
    </div>
  );
}

function DirBadge({ dir }: { dir?: string }) {
  const d = String(dir || "BUY").toUpperCase();
  const isUp = d === "BUY" || d === "LONG" || d === "AL";
  const isDown = d === "SELL" || d === "SHORT" || d === "SAT";
  let bg = "rgba(255,255,255,0.05)", fg = "var(--color-text-muted)", Icon = Minus;

  if (isUp) { bg = "rgba(0,229,160,0.1)"; fg = "#00e5a0"; Icon = TrendingUp; }
  else if (isDown) { bg = "rgba(255,68,102,0.1)"; fg = "#ff4466"; Icon = TrendingDown; }

  return (
    <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase" style={{ background: bg, color: fg }}>
      <Icon size={10} strokeWidth={3} />
      {d}
    </div>
  );
}

function RiskBadge({ level }: { level?: string }) {
  const lvl = String(level || "MEDIUM").toUpperCase();
  const isLow = lvl === "LOW" || lvl === "DÜŞÜK";
  const isHigh = lvl === "HIGH" || lvl === "YÜKSEK";
  let fg = "#ffaa00";
  if (isLow) fg = "#00e5a0";
  if (isHigh) fg = "#ff4466";

  return (
    <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider" style={{ border: `1px solid ${fg}30`, color: fg }}>
      <Shield size={10} />
      {lvl}
    </div>
  );
}

function ServiceRow({ name, health }: { name: string, health: string }) {
  const isOk = health === "ok" || health === "healthy";
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-[12px] font-medium" style={{ color: "var(--color-text-secondary)" }}>{name}</span>
      <div className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: isOk ? "#00e5a0" : "#ff4466", boxShadow: `0 0 8px ${isOk ? "#00e5a0" : "#ff4466"}40` }} />
        <span className="text-[10px] uppercase font-bold tracking-wider" style={{ color: isOk ? "#00e5a0" : "#ff4466" }}>{isOk ? "AKTİF" : "HATA"}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------
// Main Dashboard
// ---------------------------------------------
export default function ClientPageRoot() {
  const router = useRouter();
  const clock = useIstanbulClock();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);
  
  // Real-time polling
  const { data: market, loading: marketLoading } = usePolling<MarketState>("/market/state", 2000);
  const { data: rawSignals, loading: signalsLoading } = usePolling<Signal[] | SignalResponse>("/signals?limit=10", 2000);
  const { data: radarData, loading: radarLoading } = usePolling<{
    data: Array<{
      symbol: string;
      price: number;
      change: number;
      volume: number;
      high: number;
      low: number;
      score: number;
      isBist100: boolean;
    }>;
    count: number;
  }>("/market/radar?limit=50", 2500);
  const { data: status } = usePolling<SystemStatus>("/status", 3000);

  const [stockSearch, setStockSearch] = useState("");
  const [flashMap, setFlashMap] = useState<Record<string, "up" | "down">>({});
  const prevScoresRef = useRef<Record<string, number>>({});

  const signals: Signal[] = Array.isArray(rawSignals) ? rawSignals : ((rawSignals as SignalResponse)?.signals ?? []);
  const systemOk = !status || status.status === "healthy" || status.status === "ok" || (status.services && Object.values(status.services).every(s => s === "healthy"));

  useEffect(() => {
    if (!signals || signals.length === 0) return;
    const nextFlash: Record<string, "up" | "down"> = {};
    for (const s of signals) {
      const sym = (s.ticker || s.symbol || "").toUpperCase();
      if (!sym) continue;
      const score = Number(s.score ?? 0);
      const prev = prevScoresRef.current[sym];
      if (prev !== undefined && score > 0) {
        if (score > prev) nextFlash[sym] = "up";
        else if (score < prev) nextFlash[sym] = "down";
      }
      prevScoresRef.current[sym] = score;
    }
    if (Object.keys(nextFlash).length > 0) {
      setFlashMap(nextFlash);
      const timer = setTimeout(() => setFlashMap({}), 1300);
      return () => clearTimeout(timer);
    }
  }, [rawSignals]);

  const marketStocks = radarData?.data ?? [];
  const filteredStocks = marketStocks.filter((st) => {
    if (!stockSearch) return true;
    return st.symbol.toLowerCase().includes(stockSearch.toLowerCase());
  }).slice(0, 15);

  return (
    <div className="p-6 max-w-[1400px] mx-auto flex flex-col gap-6 animate-in fade-in duration-500">
      
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight mb-1" style={{ color: "var(--color-text-primary)" }}>
            BIST Otonom Yönetim Paneli
          </h1>
          <p className="text-[13px]" style={{ color: "var(--color-text-secondary)" }}>
            Tüm veriler <strong style={{color:"var(--color-accent-green)"}}>Phase 18 Otonom Motoru</strong> üzerinden canlı akmaktadır.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] font-medium"
            style={{
              background: systemOk ? "rgba(0,229,160,0.1)" : "rgba(255,68,102,0.1)",
              color: systemOk ? "#00e5a0" : "#ff4466",
              border: `1px solid ${systemOk ? "rgba(0,229,160,0.2)" : "rgba(255,68,102,0.2)"}`
            }}>
            {systemOk ? <Wifi size={13} /> : <WifiOff size={13} />}
            {systemOk ? "SİSTEM CANLI" : "BAĞLANTI SORUNU"}
          </div>
        </div>
      </div>

      {/* ?? Stats Row ???????????????????????????????????????????? */}
      <div className="grid grid-cols-4 gap-3">
        {marketLoading ? (
          <>
            <SkeletonStat /><SkeletonStat /><SkeletonStat /><SkeletonStat />
          </>
        ) : (
          <>
            <StatCard
              label="Piyasa Rejimi (Phase 18)"
              value={market?.regime === "BULL_TREND" ? "BOĞA" : market?.regime === "BEAR_TREND" ? "AYI" : market?.regime ?? "HESAPLANIYOR"}
              icon={Activity}
              accent={market?.regime === "BULL_TREND" ? "#00e5a0" : "#ff4466"}
            />
            <StatCard
              label="Piyasa Genişliği (Yükselen)"
              value={market?.breadth_pct ?? 0}
              suffix="%" decimals={1}
              icon={BarChart2}
              accent={market && market.breadth_pct > 50 ? "#00e5a0" : "#ff4466"}
              trend={market && market.breadth_pct > 50 ? "up" : "down"}
            />
            <StatCard
              label="Yükselen / Düşen"
              value={`${market?.advancing ?? 0} / ${market?.declining ?? 0}`}
              decimals={0}
              icon={TrendingUp}
              accent="#00c8ff"
            />
            <StatCard
              label="Otonom Risk İştahı"
              value={(market?.risk_appetite ?? 0) * 100}
              suffix="%" decimals={0}
              icon={Shield}
              accent={market && market.risk_appetite > 0.5 ? "#00e5a0" : "#ffaa00"}
              trend={market && market.risk_appetite > 0.5 ? "up" : "down"}
            />
          </>
        )}
      </div>

      {/* ?? Opportunity Engine ???????????????????????????????????????????? */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <SectionHeader
          icon={TargetIcon}
          title="Fırsat Motoru (Phase 18 Otonom Kararlar)"
          sub={`Canlı tarama, ${signals?.length ?? 0} aktif sinyal`}
          accent="#00e5a0"
        />

        {signalsLoading ? (
          <div className="p-4">
            <SkeletonList count={5} />
          </div>
        ) : !signals || signals.length === 0 ? (
          <div className="py-12 text-center" style={{ color: "var(--color-text-muted)" }}>
            <TargetIcon size={24} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">Şu an için aktif sinyal bulunmuyor</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider font-semibold"
                  style={{
                    color: "var(--color-text-muted)",
                    borderBottom: "1px solid var(--color-border-subtle)"
                  }}>
                  <th className="text-left py-2.5 px-5">Sembol</th>
                  <th className="text-left py-2.5 px-3">Şirket Ad</th>
                  <th className="text-right py-2.5 px-3">Phase 18 Skoru</th>
                  <th className="text-center py-2.5 px-3">Karar Yön</th>
                  <th className="text-center py-2.5 px-3">Risk</th>
                  <th className="text-right py-2.5 px-5">Beklenen Getiri (ML)</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s, i) => {
                  const sym = s.ticker || s.symbol || "BIST";
                  const flashDir = flashMap[sym];
                  const flashClass = flashDir === "up" ? "flash-up" : (flashDir === "down" ? "flash-down" : "");
                  const expPct = Number(s.expected_return_pct ?? 0);
                  return (
                    <tr
                      key={i}
                      onClick={() => router.push(`/asset?ticker=${sym}`)}
                      className={`row-hover cursor-pointer text-[12px] transition-colors hover:bg-zinc-800/40 ${flashClass}`}
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}
                    >
                      <td className="py-3 px-5">
                        <span className="font-bold font-data" style={{ color: "var(--color-text-primary)" }}>
                          {sym}
                        </span>
                      </td>
                    <td className="py-3 px-3">
                      <span className="truncate max-w-[140px] block" style={{ color: "var(--color-text-secondary)" }}>
                        {s.name || sym}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right">
                      <ScoreBar score={Number(s.score ?? 75)} />
                    </td>
                    <td className="py-3 px-3 text-center">
                      <DirBadge dir={s.direction || s.signal || "AL"} />
                    </td>
                    <td className="py-3 px-3 text-center">
                      <RiskBadge level={s.risk_level ?? "MEDIUM"} />
                    </td>
                    <td className="py-3 px-5 text-right">
                      <span
                        className="font-data font-semibold text-[13px]"
                        style={{ color: expPct > 0 ? "#00e5a0" : "#ff4466" }}
                      >
                        {expPct > 0 ? "+" : ""}%{expPct.toFixed(2)}
                      </span>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Canlı BIST Piyasa Hisseleri */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div className="flex items-center justify-between px-5 py-3 flex-wrap gap-2" style={{ borderBottom: "1px solid var(--color-border-subtle)" }}>
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md flex items-center justify-center bg-sky-500/10 text-sky-400">
              <RadarIcon size={13} />
            </div>
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-100">
                Canlı BİST Piyasa Takibi
              </h2>
              <span className="text-[10px] text-zinc-400">
                Toplam {radarData?.count ?? marketStocks.length} hisse canlı taranıyor
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-zinc-900 border border-zinc-800 text-xs">
              <Search size={11} className="text-zinc-500" />
              <input
                type="text"
                placeholder="Hisse ara (örn: THYAO, ASELS)..."
                value={stockSearch}
                onChange={(e) => setStockSearch(e.target.value)}
                className="bg-transparent text-[11px] text-zinc-200 placeholder-zinc-500 outline-none w-44"
              />
            </div>
            <button
              onClick={() => router.push("/radar")}
              className="flex items-center gap-1 text-[11px] font-semibold text-emerald-400 hover:text-emerald-300 transition-colors"
            >
              Tümünü Gör ({radarData?.count ?? 647}) <ArrowRight size={12} />
            </button>
          </div>
        </div>

        {radarLoading && marketStocks.length === 0 ? (
          <div className="p-4">
            <SkeletonTable rows={5} cols={5} />
          </div>
        ) : filteredStocks.length === 0 ? (
          <div className="py-8 text-center text-zinc-500 text-xs">
            Eşleşen hisse bulunamadı.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider font-semibold text-zinc-400 border-b border-white/5">
                  <th className="text-left py-2.5 px-5">Sembol</th>
                  <th className="text-right py-2.5 px-4">Son Fiyat</th>
                  <th className="text-right py-2.5 px-4">Günlük Değişim</th>
                  <th className="text-right py-2.5 px-4">İşlem Hacmi</th>
                  <th className="text-right py-2.5 px-5">Radar Skoru</th>
                </tr>
              </thead>
              <tbody>
                {filteredStocks.map((st) => {
                  const isPos = st.change > 0;
                  const isNeg = st.change < 0;
                  return (
                    <tr
                      key={st.symbol}
                      onClick={() => router.push(`/asset?ticker=${st.symbol}`)}
                      className="cursor-pointer text-[12px] hover:bg-zinc-800/40 transition-colors border-b border-white/[0.02]"
                    >
                      <td className="py-2.5 px-5">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-zinc-100 font-data">{st.symbol}</span>
                          {st.isBist100 && (
                            <span className="text-[9px] px-1 py-0.2 rounded bg-emerald-500/10 text-emerald-400 font-semibold">
                              B100
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-semibold text-zinc-200">
                        ₺{st.price?.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-4 text-right font-data font-semibold">
                        <span className={`inline-flex items-center gap-0.5 ${
                          isPos ? "text-emerald-400" : isNeg ? "text-rose-400" : "text-zinc-400"
                        }`}>
                          {isPos ? "+" : ""}{st.change?.toFixed(2)}%
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-right font-data text-zinc-400 text-[11px]">
                        {st.volume ? st.volume.toLocaleString("tr-TR") : "-"}
                      </td>
                      <td className="py-2.5 px-5 text-right">
                        <ScoreBar score={Number(st.score ?? 50)} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ?? Bottom Panels ?????????????????????????????????????????????????? */}
      <div className="grid grid-cols-2 gap-4">
        {/* System Health */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <SectionHeader icon={Activity} title="Sistem Sağlığı ve Servisler" accent="#00c8ff" />
          <div className="px-5 py-3 divide-y" style={{ borderColor: "rgba(255,255,255,0.03)" }}>
            {status?.services && Object.entries(status.services).length > 0
              ? Object.entries(status.services).map(([name, health]) => (
                <ServiceRow key={name} name={name} health={health as string} />
              ))
              : (
                <p className="py-6 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
                  Sistem durumu alınıyor...
                </p>
              )
            }
          </div>
        </div>
        
        {/* Phase 18 Engine Summary */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <SectionHeader icon={CheckCircle} title="Otonom Motor (Phase 18) Durumu" accent="#00e5a0" />
          <div className="px-5 py-5 space-y-4">
             <div className="flex justify-between items-center">
                 <span className="text-xs" style={{ color: "var(--color-text-secondary)" }}>Aktif Model</span>
                 <span className="text-xs font-semibold text-white bg-zinc-800 px-2 py-1 rounded">phase18_optuna_lgbm</span>
             </div>
             <div className="flex justify-between items-center">
                 <span className="text-xs" style={{ color: "var(--color-text-secondary)" }}>Model Versiyonu</span>
                 <span className="text-xs font-data" style={{ color: "var(--color-text-primary)" }}>v1.8.0-live</span>
             </div>
             <div className="flex justify-between items-center">
                 <span className="text-xs" style={{ color: "var(--color-text-secondary)" }}>Günlük Sinyal (Tahmin) Hacmi</span>
                 <span className="text-xs font-data" style={{ color: "var(--color-text-primary)" }}>{market?.advancing !== undefined ? (market.advancing + market.declining) : 100} Sembol</span>
             </div>
             <div className="flex justify-between items-center">
                 <span className="text-xs" style={{ color: "var(--color-text-secondary)" }}>Test Başarısı (OOS CAGR)</span>
                 <span className="text-xs font-data font-bold" style={{ color: "#00e5a0" }}>%51.86</span>
             </div>
          </div>
        </div>
      </div>
    </div>
  );
}