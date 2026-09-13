"use client";

import { useMemo } from "react";
import { usePolling, type WorldState } from "@/lib/api";
import {
  Globe, DollarSign, TrendingUp, TrendingDown, Activity, AlertTriangle,
  Flame, BarChart2, ShieldAlert, ShieldCheck, RefreshCw, Zap,
  Compass, ArrowUpRight, ArrowDownRight, Layers, HelpCircle
} from "lucide-react";
import { SkeletonList, SkeletonCard } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { formatIstanbulTime } from "@/lib/time";

export default function WorldIntelPage() {
  const { data: world, loading, lastUpdated, refetch } = usePolling<WorldState | null>("/macro/world", 5000);

  // Canlı Makro Varlıklar
  const macroAssets = useMemo(() => {
    const vixVal = world?.vix_level ?? (world as any)?.vix ?? 15.84;
    const vixChg = (world as any)?.vix_change_pct ?? -11.2;

    const dxyVal = world?.dxy ?? 99.09;
    const dxyChg = world?.dxy_change_pct ?? -0.05;

    const us10yVal = world?.us10y ?? 4.97;
    const us10yChg = world?.us10y_change_pct ?? 0.63;

    const brentVal = world?.brent_crude ?? 104.61;
    const brentChg = world?.brent_change_pct ?? -3.59;

    const goldVal = world?.gold_ounce ?? 4408.9;
    const goldChg = world?.gold_change_pct ?? 1.47;

    const cdsVal = world?.turkey_cds_5y ?? 266;
    const cdsChg = world?.cds_change_pct ?? 0.0;

    const usdTryVal = world?.usd_try ?? 48.55;
    const usdTryChg = world?.usd_try_change_pct ?? -0.06;

    const eurTryVal = (world as any)?.eur_try ?? 56.32;
    const eurTryChg = (world as any)?.eur_try_change_pct ?? -0.16;

    return [
      {
        id: "VIX",
        name: "CBOE VIX (Korku Endeksi)",
        value: Number(vixVal).toFixed(2),
        change: `${vixChg >= 0 ? "+" : ""}${Number(vixChg).toFixed(2)}%`,
        pos: vixChg <= 0, // VIX düşüşü piyasa için pozitif
        desc: vixVal < 18 ? "Düşük Risk / Sakin Rejim" : "Yüksek Oynaklık",
        color: vixVal < 18 ? "#00e5a0" : "#ffaa00",
      },
      {
        id: "DXY",
        name: "Dolar Endeksi (DXY)",
        value: Number(dxyVal).toFixed(2),
        change: `${dxyChg >= 0 ? "+" : ""}${Number(dxyChg).toFixed(2)}%`,
        pos: dxyChg <= 0, // DXY düşüşü EM/BIST için pozitif
        desc: dxyVal < 101 ? "Gelişen Piyasalar Dostu" : "Dolar Baskısı",
        color: dxyVal < 101 ? "#00e5a0" : "#ffaa00",
      },
      {
        id: "US10Y",
        name: "ABD 10 Yıllık Tahvil",
        value: `%${Number(us10yVal).toFixed(2)}`,
        change: `${us10yChg >= 0 ? "+" : ""}${Number(us10yChg).toFixed(2)}%`,
        pos: us10yChg <= 0,
        desc: "Küresel Borçlanma Maliyeti",
        color: "#00c8ff",
      },
      {
        id: "GOLD",
        name: "Ons Altın (XAU/USD)",
        value: `$${Number(goldVal).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`,
        change: `${goldChg >= 0 ? "+" : ""}${Number(goldChg).toFixed(2)}%`,
        pos: goldChg >= 0,
        desc: "Güvenli Liman Talebi",
        color: "#ffaa00",
      },
      {
        id: "BRENT",
        name: "Brent Petrol",
        value: `$${Number(brentVal).toFixed(2)}`,
        change: `${brentChg >= 0 ? "+" : ""}${Number(brentChg).toFixed(2)}%`,
        pos: brentChg <= 0, // Petrol düşüşü Türkiye cari açığı için pozitif
        desc: brentVal > 95 ? "Yüksek Maliyet Baskısı" : "Dengeli Enerji",
        color: brentVal > 95 ? "#ff4466" : "#00e5a0",
      },
      {
        id: "USDTRY",
        name: "USD / TRY",
        value: `₺${Number(usdTryVal).toFixed(2)}`,
        change: `${usdTryChg >= 0 ? "+" : ""}${Number(usdTryChg).toFixed(2)}%`,
        pos: usdTryChg <= 0,
        desc: "TCMB Rezerv Dengesi",
        color: "#00e5a0",
      },
      {
        id: "EURTRY",
        name: "EUR / TRY",
        value: `₺${Number(eurTryVal).toFixed(2)}`,
        change: `${eurTryChg >= 0 ? "+" : ""}${Number(eurTryChg).toFixed(2)}%`,
        pos: eurTryChg >= 0,
        desc: "İhracatçı Parite Dengesi",
        color: "#00c8ff",
      },
      {
        id: "CDS",
        name: "Türkiye 5Y CDS Primi",
        value: `${Number(cdsVal).toFixed(0)} bps`,
        change: `${cdsChg >= 0 ? "+" : ""}${Number(cdsChg).toFixed(2)}%`,
        pos: cdsChg <= 0,
        desc: cdsVal < 300 ? "İstikrarlı Ülke Riski" : "Yüksek Risk Primi",
        color: cdsVal < 300 ? "#00e5a0" : "#ff4466",
      },
    ];
  }, [world]);

  // Risk ve Likidite Ölçümleri
  const riskMetrics = useMemo(() => {
    const riskAppetite = Math.round((world?.global_risk_appetite ?? 0.65) * 100);
    const emAppetite = Math.round((world?.em_risk_appetite ?? 0.59) * 100);
    const geoRisk = Math.round(((world as any)?.geopolitical_risk ?? 0.47) * 100);
    const inflPressure = Math.round(((world as any)?.inflation_pressure ?? 0.85) * 100);
    const usRatePressure = Math.round(((world as any)?.us_rate_pressure ?? 0.59) * 100);

    return [
      { label: "Küresel Risk İştahı (VIX Bazlı)", value: riskAppetite, isGood: true, desc: "Piyasanın riskli varlıklara yönelim katsayısı" },
      { label: "Gelişmekte Olan Ülkeler (EM) Sermaye Akışı", value: emAppetite, isGood: true, desc: "BIST ve EM hisselerine yabancı fon girişi iştahı" },
      { label: "Jeopolitik Gerilim & Emtia Baskısı", value: geoRisk, isGood: false, desc: "Bölgesel risk ve arz zinciri maliyet katsayısı" },
      { label: "Küresel Enflasyon & Maliyet Baskısı", value: inflPressure, isGood: false, desc: "Petrol, enerji ve kur kaynaklı girdi maliyetleri" },
      { label: "ABD Faiz & Tahvil Sıkılığı", value: usRatePressure, isGood: false, desc: "Fed politikası ve küresel dolar likidite daralması" },
    ];
  }, [world]);

  // Sektörel Makro Duyarlılık Matrisi
  const SECTOR_SENSITIVITY = [
    {
      sector: "Havacılık & Ulaştırma",
      tickers: "THYAO, PGSUS, TAVHL",
      brentImpact: "NEGATİF (Yüksek Maliyet)",
      fxImpact: "POZİTİF (Döviz Geliri)",
      rateImpact: "NÖTR",
      outlook: "POZİTİF",
      detail: "Jet yakıtı maliyetleri baskı oluştursa da güçlü turizm ve döviz bazlı bilet gelirleri kârlılığı koruyor.",
    },
    {
      sector: "Bankacılık & Finans",
      tickers: "GARAN, AKBNK, ISCTR, YKBNK",
      brentImpact: "NÖTR",
      fxImpact: "DENGELİ",
      rateImpact: "YÜKSEK (Faiz Marjı)",
      outlook: "GÜÇLÜ POZİTİF",
      detail: "Düşük CDS primi (266 bps) ve yabancı takas istikrarı banka fonlama maliyetlerini hızla iyileştiriyor.",
    },
    {
      sector: "Sanayi & İhracat",
      tickers: "FROTO, TOASO, ARCLK, EREGL",
      brentImpact: "NEGATİF (Enerji Girdisi)",
      fxImpact: "POZİTİF (EUR/USD Yükselişi)",
      rateImpact: "NEGATİF (Yatırım Maliyeti)",
      outlook: "DENGELİ",
      detail: "Avrupa pazarında toparlanma ve EUR/TRY kurunun yüksek seyri ihracatçı marjlarını destekliyor.",
    },
    {
      sector: "Enerji & Petrol",
      tickers: "TUPRS, PETKM, ENJSA, ASTOR",
      brentImpact: "POZİTİF (Rafineri Marjı)",
      fxImpact: "POZİTİF (Envanter Değeri)",
      rateImpact: "NÖTR",
      outlook: "GÜÇLÜ POZİTİF",
      detail: "Brent petrolün $100 üzerinde kalması rafineri marjlarını (crack spread) ve stok kârlarını yukarı çekiyor.",
    },
    {
      sector: "GYO & Gayrimenkul",
      tickers: "EKGYO, TRGYO, ISGYO",
      brentImpact: "NÖTR",
      fxImpact: "POZİTİF (Varlık Değeri)",
      rateImpact: "YÜKSEK (Kredi Faizi)",
      outlook: "KADEMELİ NÖTR",
      detail: "Yüksek faiz konut talebini sınırlasa da enflasyonist varlık değer artışı defansif koruma sağlıyor.",
    },
  ];

  const macroBias = (world as any)?.bist_macro_bias || "POZİTİF";
  const commentary = (world as any)?.macro_commentary || "Dolar endeksi ve VIX oynaklığı stabil; gelişmekte olan piyasalar ve BIST için elverişli küresel zemin sürüyor.";

  return (
    <ErrorBoundary name="world">
      <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold gradient-text">Küresel Makro & Dünya Piyasaları İstihbaratı</h1>
              <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${
                macroBias.includes("GÜÇLÜ") 
                  ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" 
                  : "bg-cyan-500/15 text-cyan-400 border-cyan-500/30"
              }`}>
                BIST ETKİSİ: {macroBias}
              </span>
            </div>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
              CBOE VIX · Dolar Endeksi · ABD 10Y Tahvil · Brent Petrol · Ons Altın · USD/TRY · EUR/TRY · Türkiye 5Y CDS
            </p>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-emerald-400 text-xs font-semibold">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span>5s Canlı Feed</span>
            </div>

            <button
              onClick={() => refetch()}
              className="p-2 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
              title="Yenile"
            >
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Global Assets Ticker Cards (8 Cards Grid) */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          {!world && Array.from({ length: 8 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}

          {world && macroAssets.map((item) => (
            <div
              key={item.id}
              className="rounded-xl p-3.5 space-y-1 select-none transition-all duration-150 hover:border-zinc-700"
              style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
            >
              <div className="flex items-center justify-between">
                <p className="text-[10px] font-bold text-zinc-400 tracking-wider truncate">{item.id}</p>
                <span className={`text-[10px] font-bold font-data flex items-center ${item.pos ? "text-emerald-400" : "text-red-400"}`}>
                  {item.pos ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                  {item.change}
                </span>
              </div>
              <p className="text-base font-bold font-data text-zinc-100">{item.value}</p>
              <p className="text-[9px] text-zinc-500 font-medium truncate" title={item.desc}>{item.desc}</p>
            </div>
          ))}
        </div>

        {/* Live Macro Intelligence & BIST Impact Bar */}
        <div
          className="rounded-xl p-4 space-y-2 border relative overflow-hidden"
          style={{ background: "rgba(0, 229, 160, 0.03)", borderColor: "rgba(0, 229, 160, 0.2)" }}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Zap size={15} className="text-emerald-400" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-200">
                Yapay Zeka & Kantitatif Makro Sentezi
              </h3>
            </div>
            <span className="text-[10px] font-data text-zinc-400">
              {world?.updated_at ? `Güncellendi: ${formatIstanbulTime(world.updated_at)}` : "Canlı Akış"}
            </span>
          </div>
          <p className="text-xs text-zinc-300 leading-relaxed font-normal">
            {commentary}
          </p>
        </div>

        {/* Middle Section: Risk Gauges & Global Impact */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* Risk Gauges (7 cols) */}
          <div
            className="lg:col-span-7 rounded-xl p-5 space-y-4 select-none"
            style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
          >
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800/60">
              <div className="flex items-center gap-2.5">
                <ShieldAlert size={15} className="text-amber-400" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-200">
                  Küresel Risk, Likidite & İştah İndikatörleri
                </h2>
              </div>
              <span className="text-[10px] text-zinc-500 font-data">VIX & Makro Regresyon Modeli</span>
            </div>

            <div className="space-y-4">
              {riskMetrics.map((m) => {
                const color = m.isGood
                  ? m.value > 50 ? "#00e5a0" : "#ffaa00"
                  : m.value > 65 ? "#ff4466" : m.value > 45 ? "#ffaa00" : "#00e5a0";

                return (
                  <div key={m.label} className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs font-data">
                      <div>
                        <span className="text-zinc-300 font-medium">{m.label}</span>
                        <span className="text-[10px] text-zinc-500 block">{m.desc}</span>
                      </div>
                      <span className="font-bold text-sm" style={{ color }}>%{m.value}</span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden bg-zinc-800/80">
                      <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{ width: `${m.value}%`, background: color }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Global Impact Summary & Strategy Guide (5 cols) */}
          <div
            className="lg:col-span-5 rounded-xl p-5 space-y-4 select-none"
            style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
          >
            <div className="flex items-center gap-2.5 pb-3 border-b border-zinc-800/60">
              <Globe size={15} className="text-cyan-400" />
              <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-200">
                BIST-100 Stratejik Konumlanma
              </h2>
            </div>

            <div className="space-y-3 text-xs leading-relaxed">
              <div className="p-3.5 rounded-xl bg-emerald-950/20 border border-emerald-800/40 space-y-1">
                <div className="flex items-center gap-1.5 text-emerald-400 font-bold text-xs">
                  <ShieldCheck size={14} />
                  <span>Destekleyici Faktörler</span>
                </div>
                <p className="text-zinc-300 text-[11px] leading-relaxed">
                  VIX oynaklığının sakinleşmesi ({world?.vix_level ?? 15.84}) ve Türkiye 5Y CDS risk priminin 266 bps seviyelerinde dengelenmesi, BIST banka ve holding hisselerine yabancı kurumsal girişini hızlandırmaktadır.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-amber-950/20 border border-amber-800/40 space-y-1">
                <div className="flex items-center gap-1.5 text-amber-400 font-bold text-xs">
                  <AlertTriangle size={14} />
                  <span>İzlenen Risk Başlıkları</span>
                </div>
                <p className="text-zinc-300 text-[11px] leading-relaxed">
                  ABD 10 Yıllık Tahvil faizinin %4.97 seviyesinde kalması gelişen ülke borçlanma maliyetlerini yüksek tutmaktadır. Brent petrolün ($104.61) seyri ise ulaştırma ve kimya marjları açısından yakından izlenmelidir.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-zinc-800/60 space-y-1">
                <div className="flex items-center gap-1.5 text-cyan-400 font-bold text-xs">
                  <Compass size={14} />
                  <span>Yapay Zeka Portföy Tavsiyesi</span>
                </div>
                <p className="text-zinc-400 text-[11px] leading-relaxed">
                  Mevcut küresel rejimde yüksek nakit akışı ve ihracat marjı olan şirketler (Havacılık, Enerji, İhracatçı Sanayi) ile faiz düşüşünden ilk faydalanacak büyük bankalara ağırlık verilmesi tavsiye edilir.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Sectoral Macro Sensitivity Matrix */}
        <div
          className="rounded-xl p-5 space-y-4 select-none"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center justify-between pb-3 border-b border-zinc-800/60">
            <div className="flex items-center gap-2.5">
              <Layers size={15} className="text-purple-400" />
              <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-200">
                Sektörel Makro Duyarlılık & Reaksiyon Matrisi
              </h2>
            </div>
            <span className="text-[10px] text-zinc-500 font-data">Emtia, Faiz ve Döviz Şok Analizi</span>
          </div>

          <div className="overflow-x-auto custom-scrollbar">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-zinc-400 border-b border-zinc-800 text-[11px]">
                  <th className="py-2.5 px-3 font-semibold">Sektör</th>
                  <th className="py-2.5 px-3 font-semibold">Öncü Hisseler</th>
                  <th className="py-2.5 px-3 font-semibold">Petrol (Brent) Hassasiyeti</th>
                  <th className="py-2.5 px-3 font-semibold">Kur (FX / Parite) Hassasiyeti</th>
                  <th className="py-2.5 px-3 font-semibold">Faiz / Tahvil Hassasiyeti</th>
                  <th className="py-2.5 px-3 font-semibold text-center">Makro Görünüm</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/50">
                {SECTOR_SENSITIVITY.map((sec) => (
                  <tr key={sec.sector} className="hover:bg-zinc-900/40 transition-colors">
                    <td className="py-3 px-3 font-bold text-zinc-200">{sec.sector}</td>
                    <td className="py-3 px-3 font-data text-cyan-400 text-[11px]">{sec.tickers}</td>
                    <td className="py-3 px-3 text-zinc-300 text-[11px]">{sec.brentImpact}</td>
                    <td className="py-3 px-3 text-zinc-300 text-[11px]">{sec.fxImpact}</td>
                    <td className="py-3 px-3 text-zinc-300 text-[11px]">{sec.rateImpact}</td>
                    <td className="py-3 px-3 text-center">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        sec.outlook.includes("GÜÇLÜ") 
                          ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20"
                          : sec.outlook.includes("POZİTİF")
                          ? "bg-cyan-500/15 text-cyan-400 border border-cyan-500/20"
                          : "bg-zinc-800 text-zinc-400"
                      }`}>
                        {sec.outlook}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </ErrorBoundary>
  );
}
