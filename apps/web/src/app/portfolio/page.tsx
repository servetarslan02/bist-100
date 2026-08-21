"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { usePolling, type PortfolioData } from "@/lib/api";
import { Briefcase, TrendingUp, TrendingDown, Wallet, ArrowUpRight, ArrowDownRight } from "lucide-react";

function MetricCard({ label, value, prefix = "", suffix = "", color }: {
  label: string; value?: number; prefix?: string; suffix?: string; color?: string;
}) {
  const isPos = (value ?? 0) >= 0;
  const accent = color === "auto" ? (isPos ? "#00e5a0" : "#ff4466") : color ?? "#00c8ff";
  return (
    <div
      className="rounded-xl p-4 space-y-2 select-none"
      style={{
        background: "var(--color-bg-card)",
        border: "1px solid var(--color-border-subtle)",
        borderTop: `1px solid ${accent}30`,
      }}
    >
      <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>
        {label}
      </p>
      <p className="text-2xl font-bold font-data" style={{ color: value === undefined ? "var(--color-text-muted)" : accent }}>
        {prefix}{value !== undefined ? value.toLocaleString("tr-TR", { maximumFractionDigits: 0 }) : "—"}{suffix}
      </p>
    </div>
  );
}

export default function PortfolioPage() {
  const router = useRouter();
  const { data, loading } = usePolling<PortfolioData>("/portfolio", 15000);
  const [rebalancing, setRebalancing] = useState(false);
  const [rebalanceMsg, setRebalanceMsg] = useState<string | null>(null);

  const rawP = (data as any)?.portfolio ?? data ?? {};
  const currentCapital = rawP.current_capital ?? rawP.total_value ?? 100000;
  const investedValue = rawP.invested_value ?? 0;
  const cashBalance = rawP.cash_balance ?? rawP.cash ?? 100000;
  const totalPnl = rawP.total_pnl ?? rawP.unrealized_pnl ?? 0;
  const totalReturnPct = rawP.total_return_pct ?? rawP.unrealized_pnl_pct ?? 0;
  const positions = data?.positions ?? rawP.positions ?? [];
  const totalPnlPos = totalPnl >= 0;

  const handleAutoRebalance = async () => {
    setRebalancing(true);
    setRebalanceMsg(null);
    try {
      const res = await fetch("/api/v1/portfolio/auto_rebalance", { method: "POST" });
      const r = await res.json();
      if (r.success) {
        setRebalanceMsg(`${r.rebalanced_count} adet yüksek skorlu hisse (THYAO, ASELS, GARAN, KCHOL) Kelly kriterine göre portföye eklendi.`);
        window.location.reload();
      }
    } catch (e) {
      setRebalanceMsg("Yeniden dengeleme hatası oluştu.");
    } finally {
      setRebalancing(false);
    }
  };

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Portföy Yönetimi & Otonom İşlem Motoru</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Sanal İşlem (Paper Trading) · Fractional Kelly Sizing · {positions.length} aktif pozisyon
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleAutoRebalance}
            disabled={rebalancing}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 text-zinc-950 hover:brightness-110 cursor-pointer shadow-lg transition-all"
          >
            <Wallet size={14} className={rebalancing ? "animate-spin" : ""} />
            {rebalancing ? "Dengeleniyor..." : "Otonom Yeniden Dengele (Kelly Bot)"}
          </button>
          <div
            className="flex items-center gap-2 px-4 py-2 rounded-xl"
            style={{
              background: totalPnlPos ? "rgba(0,229,160,0.08)" : "rgba(255,68,102,0.08)",
              border: `1px solid ${totalPnlPos ? "rgba(0,229,160,0.2)" : "rgba(255,68,102,0.2)"}`,
            }}
          >
            {totalPnlPos ? <TrendingUp size={14} style={{ color: "#00e5a0" }} /> : <TrendingDown size={14} style={{ color: "#ff4466" }} />}
            <span className="text-sm font-bold font-data" style={{ color: totalPnlPos ? "#00e5a0" : "#ff4466" }}>
              {totalPnlPos ? "+" : ""}₺{totalPnl.toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
            </span>
            <span className="text-xs font-data" style={{ color: "var(--color-text-secondary)" }}>
              ({totalPnlPos ? "+" : ""}%{totalReturnPct.toFixed(2)})
            </span>
          </div>
        </div>
      </div>

      {rebalanceMsg && (
        <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-xs text-emerald-400 font-medium">
          {rebalanceMsg}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-5 gap-3">
        <MetricCard label="Toplam Sermaye" value={currentCapital} prefix="₺" accent="#00c8ff" />
        <MetricCard label="Yatırımdaki Tutar" value={investedValue} prefix="₺" accent="#9966ff" />
        <MetricCard label="Nakit Bakiye" value={cashBalance} prefix="₺" accent="#ffaa00" />
        <MetricCard label="Toplam K/Z" value={totalPnl} prefix="₺" color="auto" />
        <MetricCard label="Toplam Getiri" value={totalReturnPct} suffix="%" color="auto" />
      </div>

      {/* Positions Table */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(0,200,255,0.12)" }}>
              <Briefcase size={13} style={{ color: "#00c8ff" }} />
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>
              Açık Pozisyonlar
            </h2>
          </div>
          <span className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>{positions.length} hisse</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr
                className="text-[10px] uppercase tracking-wider font-semibold"
                style={{
                  color: "var(--color-text-muted)",
                  borderBottom: "1px solid var(--color-border-subtle)",
                  background: "rgba(255,255,255,0.01)"
                }}
              >
                <th className="text-left py-3 px-5">Sembol</th>
                <th className="text-left py-3 px-3">Şirket Adı</th>
                <th className="text-right py-3 px-3">Adet</th>
                <th className="text-right py-3 px-3">Ort. Maliyet</th>
                <th className="text-right py-3 px-3">Güncel Fiyat</th>
                <th className="text-right py-3 px-3">Piyasa Değeri</th>
                <th className="text-right py-3 px-3">Kâr / Zarar</th>
                <th className="text-right py-3 px-3">K/Z %</th>
                <th className="text-right py-3 px-5">Portföy Payı</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="text-center py-16" style={{ color: "var(--color-text-muted)" }}>Veriler yükleniyor...</td></tr>
              ) : positions.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-16">
                    <Wallet size={28} className="mx-auto mb-3" style={{ color: "var(--color-text-faint)" }} />
                    <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>Henüz açık pozisyon bulunmuyor</p>
                  </td>
                </tr>
              ) : (
                positions.map((pos, i) => {
                  const pnlPos = (pos.unrealized_pnl ?? 0) >= 0;
                  return (
                    <tr
                      key={i}
                      onClick={() => router.push(`/asset?ticker=${pos.ticker}`)}
                      className="row-hover cursor-pointer text-[12px] transition-colors hover:bg-zinc-800/40"
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}
                    >
                      <td className="py-3 px-5">
                        <span className="font-bold font-data" style={{ color: "var(--color-text-primary)" }}>{pos.ticker}</span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="truncate max-w-[120px] block text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
                          {pos.name}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-right font-data" style={{ color: "var(--color-text-primary)" }}>
                        {pos.quantity}
                      </td>
                      <td className="py-3 px-3 text-right font-data" style={{ color: "var(--color-text-secondary)" }}>
                        ₺{pos.avg_cost?.toFixed(2)}
                      </td>
                      <td className="py-3 px-3 text-right font-data" style={{ color: "var(--color-text-primary)" }}>
                        ₺{pos.current_price?.toFixed(2)}
                      </td>
                      <td className="py-3 px-3 text-right font-data" style={{ color: "var(--color-text-primary)" }}>
                        ₺{pos.market_value?.toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {pnlPos ? <ArrowUpRight size={11} style={{ color: "#00e5a0" }} /> : <ArrowDownRight size={11} style={{ color: "#ff4466" }} />}
                          <span className="font-data font-semibold" style={{ color: pnlPos ? "#00e5a0" : "#ff4466" }}>
                            ₺{pos.unrealized_pnl?.toLocaleString("tr-TR", { maximumFractionDigits: 0 })}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-3 text-right">
                        <span className="font-data font-semibold" style={{ color: pnlPos ? "#00e5a0" : "#ff4466" }}>
                          {pnlPos ? "+" : ""}%{pos.unrealized_pnl_pct?.toFixed(2)}
                        </span>
                      </td>
                      <td className="py-3 px-5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-12 h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
                            <div className="h-full rounded-full" style={{ width: `${pos.weight_pct ?? 0}%`, background: "#00c8ff" }} />
                          </div>
                          <span className="font-data text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
                            %{pos.weight_pct?.toFixed(1)}
                          </span>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
