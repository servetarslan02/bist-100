"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { usePolling, type PortfolioData, apiFetch } from "@/lib/api";
import { 
  Briefcase, TrendingUp, TrendingDown, Wallet, ArrowUpRight, ArrowDownRight, 
  RefreshCw, ShieldCheck, Activity, PieChart, Layers, Clock, CheckCircle2, 
  AlertCircle, BarChart3, ArrowRight, Zap, Building2, Coins, Receipt
} from "lucide-react";

function MetricCard({ label, value, prefix = "", suffix = "", color, subtext }: {
  label: string; value?: number; prefix?: string; suffix?: string; color?: string; subtext?: string;
}) {
  const isPos = (value ?? 0) >= 0;
  const accent = color === "auto" ? (isPos ? "#00e5a0" : "#ff4466") : color ?? "#00c8ff";
  return (
    <div
      className="rounded-xl p-4 space-y-1.5 select-none transition-all hover:border-zinc-700"
      style={{
        background: "var(--color-bg-card)",
        border: "1px solid var(--color-border-subtle)",
        borderTop: `2px solid ${accent}`,
      }}
    >
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>
          {label}
        </p>
      </div>
      <p className="text-2xl font-bold font-data tracking-tight" style={{ color: value === undefined ? "var(--color-text-muted)" : accent }}>
        {prefix}{value !== undefined ? value.toLocaleString("tr-TR", { maximumFractionDigits: 2 }) : "—"}{suffix}
      </p>
      {subtext && (
        <p className="text-[10px] truncate" style={{ color: "var(--color-text-muted)" }}>
          {subtext}
        </p>
      )}
    </div>
  );
}

export default function PortfolioPage() {
  const router = useRouter();
  const { data, loading, refetch } = usePolling<any>("/portfolio", 1500);
  const { data: ordersData, refetch: refetchOrders } = usePolling<any>("/portfolio/orders", 3000);
  const { data: metricsData } = usePolling<any>("/portfolio/metrics", 5000);
  
  const [triggering, setTriggering] = useState(false);
  const [actionMsg, setActionMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [flashMap, setFlashMap] = useState<Record<string, "up" | "down">>({});
  const prevPricesRef = useState<Record<string, number>>({})[0];

  // BIST Seans Kontrolü (10:00 - 18:00 İstanbul)
  const isBistOpen = () => {
    const now = new Date();
    const istanbul = new Date(now.toLocaleString("en-US", { timeZone: "Europe/Istanbul" }));
    const day = istanbul.getDay();
    if (day === 0 || day === 6) return false;
    const minutes = istanbul.getHours() * 60 + istanbul.getMinutes();
    return minutes >= 600 && minutes < 1080;
  };
  const marketOpen = isBistOpen();

  const rawP = (data as any)?.portfolio ?? data ?? {};
  const currentCapital = rawP.total_value ?? rawP.current_capital ?? 1000000;
  const investedValue = rawP.invested_value ?? 0;
  const cashBalance = rawP.cash ?? rawP.total_cash ?? rawP.settled_cash ?? 0;
  const settledCash = rawP.settled_cash ?? cashBalance;
  const unsettledT1 = rawP.unsettled_cash_t1 ?? 0;
  const unsettledT2 = rawP.unsettled_cash_t2 ?? 0;
  const purchasingPower = rawP.purchasing_power ?? cashBalance;
  const totalPnl = rawP.total_pnl ?? rawP.unrealized_pnl ?? 0;
  const totalReturnPct = rawP.total_return_pct ?? 0;
  const positions = (data as any)?.positions ?? rawP.positions ?? [];
  const sectorWeights = rawP.sector_weights ?? {};
  const orders = ordersData?.orders ?? [];
  const totalPnlPos = totalPnl >= 0;

  // Canlı fiyat adımı yanıp sönme kontrolü (Green / Red Flash)
  useEffect(() => {
    if (!positions || positions.length === 0) return;
    const nextFlash: Record<string, "up" | "down"> = {};
    for (const pos of positions) {
      const sym = pos.ticker || pos.symbol;
      const price = Number(pos.current_price ?? pos.avg_cost ?? 0);
      const prev = prevPricesRef[sym];
      if (prev !== undefined && price > 0) {
        if (price > prev) nextFlash[sym] = "up";
        else if (price < prev) nextFlash[sym] = "down";
      }
      prevPricesRef[sym] = price;
    }
    if (Object.keys(nextFlash).length > 0) {
      setFlashMap(nextFlash);
      const timer = setTimeout(() => setFlashMap({}), 1300);
      return () => clearTimeout(timer);
    }
  }, [data]);

  const handleRunRebalanceCycle = async () => {
    setTriggering(true);
    setActionMsg(null);
    try {
      const res = await apiFetch("/scanner/trigger?scan_type=manual", { method: "POST" });
      setActionMsg({ 
        type: "success", 
        text: "Günlük seans sinyal ve portföy emir yürütme döngüsü başarıyla tetiklendi. Veriler güncelleniyor..." 
      });
      setTimeout(() => {
        refetch();
        refetchOrders();
      }, 2500);
    } catch (e: any) {
      setActionMsg({ type: "error", text: `İşlem tetiklenirken hata oluştu: ${e.message || e}` });
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-bold gradient-text">Portföy Yönetimi & T+2 Takas Defteri</h1>
            <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${
              marketOpen 
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : "bg-amber-500/10 border-amber-500/30 text-amber-400"
            }`}>
              {marketOpen ? "● BIST SEANSI AÇIK" : "○ BIST KAPALI (Sabah 09:55 Seans Emri Hazır)"}
            </span>
            <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-purple-500/10 border border-purple-500/30 text-purple-300">
              🤖 LambdaRank v3.0 Şampiyon Model
            </span>
          </div>
          <p className="text-[11px] mt-1" style={{ color: "var(--color-text-muted)" }}>
            BIST Kurumsal Risk Kapısı · T+2 Takas Mahsup Kuralları · Sentetik Derinlik ve Kayma Koruması · {positions.length} aktif pozisyon
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleRunRebalanceCycle}
            disabled={triggering}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 transition-all disabled:opacity-50"
          >
            <RefreshCw size={13} className={triggering ? "animate-spin" : ""} />
            {triggering ? "Seans Yürütülüyor..." : "Seansı Şimdi Çalıştır"}
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
              {totalPnlPos ? "+" : ""}₺{totalPnl.toLocaleString("tr-TR", { maximumFractionDigits: 2 })}
            </span>
            <span className="text-xs font-data" style={{ color: "var(--color-text-secondary)" }}>
              ({totalPnlPos ? "+" : ""}%{totalReturnPct.toFixed(2)})
            </span>
          </div>
        </div>
      </div>

      {actionMsg && (
        <div className={`p-3 rounded-lg border text-xs font-medium flex items-center gap-2 ${
          actionMsg.type === "success" 
            ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
            : "bg-rose-500/10 border-rose-500/30 text-rose-400"
        }`}>
          {actionMsg.type === "success" ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
          {actionMsg.text}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label="Toplam Portföy (NAV)" value={currentCapital} prefix="₺" color="#00c8ff" subtext="Toplam Net Varlık Değeri" />
        <MetricCard label="Yatırımdaki Tutar" value={investedValue} prefix="₺" color="#9966ff" subtext={`Hisseler (${positions.length} adet)`} />
        <MetricCard label="Alım Gücü (Nakit)" value={purchasingPower} prefix="₺" color="#ffaa00" subtext="T+2 Mahsup Dahil" />
        <MetricCard label="Toplam Kâr / Zarar" value={totalPnl} prefix="₺" color="auto" subtext="Anlık Realized + Unrealized" />
        <MetricCard label="Portföy Getirisi" value={totalReturnPct} suffix="%" color="auto" subtext="Model Başlangıç Getirisi" />
      </div>

      {/* T+2 Takas & Sektör Dağılım Bölümü */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* T+2 Takasbank Bakiye Modeli */}
        <div 
          className="rounded-xl p-4 space-y-3"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center justify-between border-b border-zinc-800 pb-2.5">
            <div className="flex items-center gap-2">
              <Coins size={15} className="text-amber-400" />
              <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-200">
                T+2 Takas & Valör Durumu
              </h2>
            </div>
            <span className="text-[10px] text-zinc-400">Takasbank Uyumlu</span>
          </div>

          <div className="space-y-2 text-xs font-data">
            <div className="flex items-center justify-between p-2 rounded-lg bg-zinc-900/60 border border-zinc-800">
              <span className="text-zinc-400">T+0 Serbest Nakit (Çekilebilir):</span>
              <span className="font-bold text-zinc-200">₺{settledCash.toLocaleString("tr-TR", { maximumFractionDigits: 2 })}</span>
            </div>
            <div className="flex items-center justify-between p-2 rounded-lg bg-zinc-900/60 border border-zinc-800">
              <span className="text-zinc-400">T+1 Takas Alacağı:</span>
              <span className="font-bold text-zinc-300">₺{unsettledT1.toLocaleString("tr-TR", { maximumFractionDigits: 2 })}</span>
            </div>
            <div className="flex items-center justify-between p-2 rounded-lg bg-zinc-900/60 border border-zinc-800">
              <span className="text-zinc-400">T+2 Takas Alacağı:</span>
              <span className="font-bold text-zinc-300">₺{unsettledT2.toLocaleString("tr-TR", { maximumFractionDigits: 2 })}</span>
            </div>
            <div className="flex items-center justify-between p-2 rounded-lg bg-cyan-950/20 border border-cyan-500/20">
              <span className="text-cyan-400 font-semibold">Toplam İşlem Gücü:</span>
              <span className="font-bold text-cyan-300">₺{purchasingPower.toLocaleString("tr-TR", { maximumFractionDigits: 2 })}</span>
            </div>
          </div>
        </div>

        {/* Sektörel Dağılım & Risk Kapısı */}
        <div 
          className="rounded-xl p-4 space-y-3 md:col-span-2"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center justify-between border-b border-zinc-800 pb-2.5">
            <div className="flex items-center gap-2">
              <PieChart size={15} className="text-cyan-400" />
              <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-200">
                Sektörel Dağılım & Konsantrasyon Limiti
              </h2>
            </div>
            <span className="text-[10px] text-zinc-400 font-medium">Maks. %30 / Sektör</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            {Object.keys(sectorWeights).length === 0 ? (
              <p className="text-xs text-zinc-500 col-span-2 py-4 text-center">Henüz sektör verisi bulunmuyor</p>
            ) : (
              Object.entries(sectorWeights).map(([sec, weight]: any, i) => {
                const wPct = (Number(weight) * 100);
                const isNearLimit = wPct >= 25.0;
                return (
                  <div key={i} className="p-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800 space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium text-zinc-300">{sec}</span>
                      <span className={`font-data font-bold ${isNearLimit ? "text-amber-400" : "text-cyan-400"}`}>
                        %{wPct.toFixed(1)}
                      </span>
                    </div>
                    <div className="w-full h-1.5 rounded-full overflow-hidden bg-zinc-800">
                      <div 
                        className={`h-full rounded-full transition-all ${isNearLimit ? "bg-amber-400" : "bg-cyan-400"}`} 
                        style={{ width: `${Math.min(100, (wPct / 30) * 100)}%` }} 
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Positions Table */}
      <div
        className="rounded-xl overflow-hidden shadow-lg"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div
          className="flex items-center justify-between px-5 py-3.5"
          style={{ borderBottom: "1px solid var(--color-border-subtle)", background: "rgba(255,255,255,0.01)" }}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-cyan-500/10 border border-cyan-500/20">
              <Briefcase size={14} className="text-cyan-400" />
            </div>
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-100">
                Açık Pozisyonlar & Canlı Değerleme
              </h2>
              <p className="text-[10px] text-zinc-400">Gerçek zamanlı piyasa fiyatı, kâr/zarar ve portföy ağırlıkları</p>
            </div>
          </div>
          <span className="px-2.5 py-1 rounded-md text-[11px] font-bold bg-zinc-800 text-zinc-300 border border-zinc-700">
            {positions.length} Hisse Aktif
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr
                className="text-[10px] uppercase tracking-wider font-semibold"
                style={{
                  color: "var(--color-text-muted)",
                  borderBottom: "1px solid var(--color-border-subtle)",
                  background: "rgba(0,0,0,0.2)"
                }}
              >
                <th className="text-left py-3 px-5">Sembol</th>
                <th className="text-left py-3 px-3">Şirket Adı</th>
                <th className="text-left py-3 px-3">Sektör</th>
                <th className="text-right py-3 px-3">Adet (Lot)</th>
                <th className="text-right py-3 px-3">Giriş Maliyeti</th>
                <th className="text-right py-3 px-3">Güncel Fiyat</th>
                <th className="text-right py-3 px-3">Piyasa Değeri</th>
                <th className="text-right py-3 px-3">Kâr / Zarar (₺)</th>
                <th className="text-right py-3 px-3">K/Z %</th>
                <th className="text-right py-3 px-5">Portföy Payı</th>
              </tr>
            </thead>
            <tbody>
              {loading && positions.length === 0 ? (
                <tr><td colSpan={10} className="text-center py-16 text-zinc-500">Portföy verileri yükleniyor...</td></tr>
              ) : positions.length === 0 ? (
                <tr>
                  <td colSpan={10} className="text-center py-16">
                    <Wallet size={32} className="mx-auto mb-3 text-zinc-600" />
                    <p className="text-sm font-semibold text-zinc-400">Henüz açık pozisyon bulunmuyor</p>
                    <p className="text-xs text-zinc-500 mt-1">Sabah 09:55 seansında veya Seansı Şimdi Çalıştır ile otomatik alım yapılır.</p>
                  </td>
                </tr>
              ) : (
                positions.map((pos: any, i: number) => {
                  const sym = pos.ticker || pos.symbol;
                  const pnlVal = Number(pos.unrealized_pnl ?? 0);
                  const pnlPct = Number(pos.unrealized_pnl_pct ?? 0);
                  const pnlPos = pnlVal >= 0;
                  const flashDir = flashMap[sym];
                  const flashClass = flashDir === "up" ? "flash-up" : (flashDir === "down" ? "flash-down" : "");
                  return (
                    <tr
                      key={i}
                      onClick={() => router.push(`/asset?ticker=${sym}`)}
                      className={`row-hover cursor-pointer text-[12px] transition-colors hover:bg-zinc-800/40 border-b border-zinc-800/50 ${flashClass}`}
                    >
                      <td className="py-3 px-5">
                        <span className="font-bold font-data text-cyan-400 hover:underline">{sym}</span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="truncate max-w-[150px] block text-[11px] text-zinc-300 font-medium">
                          {pos.name || pos.company_name || sym}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-zinc-800 border border-zinc-700 text-zinc-300">
                          {pos.sector || "DİĞER"}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-right font-data font-bold text-zinc-200">
                        {pos.quantity?.toLocaleString("tr-TR")}
                      </td>
                      <td className="py-3 px-3 text-right font-data text-zinc-400">
                        ₺{Number(pos.avg_cost ?? 0).toFixed(2)}
                      </td>
                      <td className={`py-3 px-3 text-right font-data font-bold text-zinc-100 transition-colors ${flashClass}`}>
                        ₺{Number(pos.current_price ?? pos.avg_cost ?? 0).toFixed(2)}
                      </td>
                      <td className="py-3 px-3 text-right font-data font-semibold text-zinc-200">
                        ₺{Number(pos.market_value ?? 0).toLocaleString("tr-TR", { maximumFractionDigits: 2 })}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <div className="flex items-center justify-end gap-1 font-data font-bold">
                          {pnlPos ? <ArrowUpRight size={12} className="text-emerald-400" /> : <ArrowDownRight size={12} className="text-rose-400" />}
                          <span className={pnlPos ? "text-emerald-400" : "text-rose-400"}>
                            {pnlPos ? "+" : ""}₺{pnlVal.toLocaleString("tr-TR", { maximumFractionDigits: 2 })}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-3 text-right font-data font-bold">
                        <span className={`px-2 py-0.5 rounded text-[11px] ${
                          pnlPos 
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" 
                            : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                        }`}>
                          {pnlPos ? "+" : ""}%{pnlPct.toFixed(2)}
                        </span>
                      </td>
                      <td className="py-3 px-5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-16 h-1.5 rounded-full overflow-hidden bg-zinc-800">
                            <div className="h-full rounded-full bg-cyan-400" style={{ width: `${Math.min(100, Number(pos.weight_pct ?? 0) * 5)}%` }} />
                          </div>
                          <span className="font-data text-[11px] text-zinc-300 font-semibold w-10 text-right">
                            %{Number(pos.weight_pct ?? 0).toFixed(1)}
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

      {/* Gerçekleşen Son Emirler ve İşlem Kayıtları */}
      <div
        className="rounded-xl overflow-hidden shadow-lg"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div
          className="flex items-center justify-between px-5 py-3.5"
          style={{ borderBottom: "1px solid var(--color-border-subtle)", background: "rgba(255,255,255,0.01)" }}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-purple-500/10 border border-purple-500/20">
              <Receipt size={14} className="text-purple-400" />
            </div>
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-100">
                Son Gerçekleşen Emirler & Mikro-Yapı Defteri
              </h2>
              <p className="text-[10px] text-zinc-400">BIST sentetik derinlik eşleşmesi, komisyon ve kayma (slippage) denetim izi</p>
            </div>
          </div>
          <span className="text-[10px] text-zinc-400 font-medium">Toplam {orders.length} Emir Kaydı</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr
                className="text-[10px] uppercase tracking-wider font-semibold"
                style={{
                  color: "var(--color-text-muted)",
                  borderBottom: "1px solid var(--color-border-subtle)",
                  background: "rgba(0,0,0,0.2)"
                }}
              >
                <th className="text-left py-3 px-5">Tarih</th>
                <th className="text-left py-3 px-3">Emir No</th>
                <th className="text-left py-3 px-3">Hisse</th>
                <th className="text-center py-3 px-3">İşlem Yönü</th>
                <th className="text-right py-3 px-3">Miktar (Lot)</th>
                <th className="text-right py-3 px-3">Sinyal Fiyatı</th>
                <th className="text-right py-3 px-3">Gerçekleşme Fiyatı</th>
                <th className="text-right py-3 px-3">Kayma (Slippage)</th>
                <th className="text-right py-3 px-3">Komisyon (₺)</th>
                <th className="text-right py-3 px-5">Durum</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 ? (
                <tr>
                  <td colSpan={10} className="text-center py-10 text-xs text-zinc-500">
                    Henüz işlem emri kaydı bulunmuyor
                  </td>
                </tr>
              ) : (
                orders.map((ord: any, i: number) => {
                  const isBuy = ord.side === "BUY";
                  return (
                    <tr key={i} className="text-[12px] border-b border-zinc-800/40 hover:bg-zinc-800/20">
                      <td className="py-2.5 px-5 font-data text-zinc-400">{ord.date || "2026-08-24"}</td>
                      <td className="py-2.5 px-3 font-data text-zinc-500 text-[11px] truncate max-w-[120px]">{ord.order_id || `ORD_${i+1}`}</td>
                      <td className="py-2.5 px-3 font-bold font-data text-zinc-200">{ord.ticker}</td>
                      <td className="py-2.5 px-3 text-center">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          isBuy ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                        }`}>
                          {isBuy ? "ALIŞ" : "SATIŞ"}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-right font-data font-semibold text-zinc-200">{ord.quantity?.toLocaleString("tr-TR")}</td>
                      <td className="py-2.5 px-3 text-right font-data text-zinc-400">₺{Number(ord.signal_price ?? 0).toFixed(2)}</td>
                      <td className="py-2.5 px-3 text-right font-data font-bold text-zinc-100">₺{Number(ord.execution_price ?? 0).toFixed(2)}</td>
                      <td className="py-2.5 px-3 text-right font-data text-amber-400/90 text-[11px]">%{Number(ord.slippage_pct ?? 0).toFixed(3)}</td>
                      <td className="py-2.5 px-3 text-right font-data text-zinc-400">₺{Number(ord.commission ?? 0).toFixed(2)}</td>
                      <td className="py-2.5 px-5 text-right">
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                          {ord.status === "FILLED" ? "GERÇEKLEŞTİ" : ord.status}
                        </span>
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
