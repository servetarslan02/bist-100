"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling, type Signal } from "@/lib/api";
import { Target, ArrowUpRight, ArrowDownRight, Flame, Eye, Star, Layers } from "lucide-react";

const CATEGORIES = ["ALL", "HIGH_CONVICTION", "CANDIDATE", "WATCH", "NORMAL"] as const;

const CAT_CONFIG: Record<string, { label: string; color: string; bg: string; icon: React.ElementType }> = {
  HIGH_CONVICTION: { label: "Yüksek Güven", color: "#ff4466", bg: "rgba(255,68,102,0.1)", icon: Flame },
  CANDIDATE:       { label: "Güçlü Aday",   color: "#ffaa00", bg: "rgba(255,170,0,0.1)", icon: Star },
  WATCH:           { label: "İzleme Listesi",color: "#00c8ff", bg: "rgba(0,200,255,0.1)", icon: Eye },
  NORMAL:          { label: "Standart",     color: "#8892a4", bg: "rgba(136,146,164,0.1)", icon: Layers },
};

function CatBadge({ cat }: { cat: string }) {
  const cfg = CAT_CONFIG[cat] ?? { color: "#8892a4", bg: "rgba(136,146,164,0.1)", icon: Layers, label: cat };
  const Icon = cfg.icon;
  return (
    <span
      className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold"
      style={{ background: cfg.bg, color: cfg.color }}
    >
      <Icon size={9} />
      {cfg.label}
    </span>
  );
}

export default function Opportunities() {
  const router = useRouter();
  const { data: signals, loading } = usePolling<Signal[]>("/signals?limit=100", 15000);
  const [filter, setFilter] = useState<string>("ALL");

  const normalizedSignals = useMemo(() => {
    if (!signals) return [];
    const list = Array.isArray(signals) ? signals : ((signals as any).signals || []);
    return list.map((s: any) => {
      const score = s.score ?? 75;
      const autoCat = s.spec_category || (score >= 88 ? "HIGH_CONVICTION" : score >= 80 ? "CANDIDATE" : score >= 70 ? "WATCH" : "NORMAL");
      return {
        ...s,
        spec_category: autoCat,
      };
    });
  }, [signals]);

  const filtered = useMemo(() => {
    if (filter === "ALL") return normalizedSignals;
    return normalizedSignals.filter(s => s.spec_category === filter);
  }, [normalizedSignals, filter]);

  const counts = useMemo(() => {
    return {
      ALL: normalizedSignals.length,
      HIGH_CONVICTION: normalizedSignals.filter(s => s.spec_category === "HIGH_CONVICTION").length,
      CANDIDATE: normalizedSignals.filter(s => s.spec_category === "CANDIDATE").length,
      WATCH: normalizedSignals.filter(s => s.spec_category === "WATCH").length,
      NORMAL: normalizedSignals.filter(s => s.spec_category === "NORMAL").length,
    };
  }, [normalizedSignals]);

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Piyasa Fırsatları</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            SPEC · Momentum · Kırılım · Değer · Olay Odaklı Stratejiler
          </p>
        </div>
        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] font-semibold"
          style={{ background: "rgba(0,229,160,0.08)", border: "1px solid rgba(0,229,160,0.2)", color: "#00e5a0" }}
        >
          <div className="w-1.5 h-1.5 rounded-full live-dot" style={{ background: "#00e5a0" }} />
          {signals?.length ?? 0} aktif sinyal
        </div>
      </div>

      {/* Category Filter */}
      <div className="flex gap-2 select-none">
        {CATEGORIES.map(cat => {
          const cfg = cat === "ALL" ? null : CAT_CONFIG[cat];
          const active = filter === cat;
          return (
            <button
              key={cat}
              onClick={() => setFilter(cat)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-all duration-150 cursor-pointer"
              style={{
                background: active ? (cfg?.bg ?? "rgba(0,229,160,0.1)") : "var(--color-bg-card)",
                border: `1px solid ${active ? (cfg?.color ?? "#00e5a0") + "40" : "var(--color-border-subtle)"}`,
                color: active ? (cfg?.color ?? "#00e5a0") : "var(--color-text-muted)",
              }}
            >
              {cfg && <cfg.icon size={10} />}
              {cat === "ALL" ? "Tümü" : cfg?.label}
              <span
                className="ml-0.5 px-1.5 py-0.5 rounded-full text-[9px]"
                style={{
                  background: active ? "rgba(0,0,0,0.2)" : "rgba(255,255,255,0.05)",
                }}
              >
                {(counts as Record<string,number>)[cat] ?? 0}
              </span>
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div
          className="flex items-center gap-2.5 px-5 py-3"
          style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
        >
          <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(0,229,160,0.12)" }}>
            <Target size={13} style={{ color: "#00e5a0" }} />
          </div>
          <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>
            Sinyal Listesi
          </h2>
          <span className="text-[10px] ml-auto" style={{ color: "var(--color-text-muted)" }}>
            {filtered.length} sonuç listelendi
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr
                className="text-[10px] uppercase tracking-wider font-semibold"
                style={{ color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border-subtle)", background: "rgba(255,255,255,0.01)" }}
              >
                <th className="text-left py-2.5 px-5">Sembol</th>
                <th className="text-left py-2.5 px-3">Şirket Adı</th>
                <th className="text-right py-2.5 px-3">Model Skoru</th>
                <th className="text-center py-2.5 px-3">Yön</th>
                <th className="text-center py-2.5 px-3">Risk</th>
                <th className="text-center py-2.5 px-3">Vade</th>
                <th className="text-right py-2.5 px-3">Beklenen Getiri</th>
                <th className="text-center py-2.5 px-5">Kategori</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="text-center py-16">
                    <div className="flex items-center justify-center gap-2" style={{ color: "var(--color-text-muted)" }}>
                      <div className="w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
                      Fırsatlar taranıyor...
                    </div>
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-16">
                    <Target size={28} className="mx-auto mb-3" style={{ color: "var(--color-text-faint)" }} />
                    <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>Filtreye uygun sinyal bulunamadı</p>
                  </td>
                </tr>
              ) : (
                filtered.map((s, i) => {
                  const up = s.direction === "LONG" || s.direction === "AL";
                  const score = s.score ?? 0;
                  const scoreColor = score >= 80 ? "#00e5a0" : score >= 60 ? "#ffaa00" : "#ff4466";
                  const retPos = (s.expected_return_pct ?? 0) > 0;
                  const riskCfg: Record<string, { bg: string; color: string; text: string }> = {
                    LOW: { bg: "rgba(0,229,160,0.1)", color: "#00e5a0", text: "DÜŞÜK" },
                    MEDIUM: { bg: "rgba(255,170,0,0.1)", color: "#ffaa00", text: "ORTA" },
                    HIGH: { bg: "rgba(255,68,102,0.1)", color: "#ff4466", text: "YÜKSEK" },
                  };
                  const risk = riskCfg[s.risk_level ?? "MEDIUM"] ?? riskCfg.MEDIUM;
                  return (
                    <tr
                      key={i}
                      onClick={() => router.push(`/asset?ticker=${s.ticker}`)}
                      className="row-hover cursor-pointer text-[12px] transition-colors hover:bg-zinc-800/40"
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}
                    >
                      <td className="py-3 px-5">
                        <span className="font-bold font-data" style={{ color: "var(--color-text-primary)" }}>{s.ticker}</span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-[11px] truncate max-w-[140px] block" style={{ color: "var(--color-text-secondary)" }}>{s.name}</span>
                      </td>
                      <td className="py-3 px-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-10 h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
                            <div className="h-full rounded-full" style={{ width: `${score}%`, background: scoreColor }} />
                          </div>
                          <span className="font-data font-semibold text-[11px]" style={{ color: scoreColor }}>{score.toFixed(0)}</span>
                        </div>
                      </td>
                      <td className="py-3 px-3 text-center">
                        <span
                          className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold"
                          style={{ background: up ? "rgba(0,229,160,0.12)" : "rgba(255,68,102,0.12)", color: up ? "#00e5a0" : "#ff4466" }}
                        >
                          {up ? <ArrowUpRight size={9} /> : <ArrowDownRight size={9} />}
                          {up ? "AL" : "SAT"}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-center">
                        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-semibold" style={{ background: risk.bg, color: risk.color }}>
                          {risk.text}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-center">
                        <span className="text-[11px] font-data" style={{ color: "var(--color-text-secondary)" }}>
                          {s.horizon === "SHORT" ? "Kısa Vade" : s.horizon === "MID" ? "Orta Vade" : s.horizon === "LONG" ? "Uzun Vade" : s.horizon}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-right">
                        <span className="font-data font-semibold" style={{ color: retPos ? "#00e5a0" : "#ff4466" }}>
                          {retPos ? "+" : ""}%{s.expected_return_pct?.toFixed(1)}
                        </span>
                      </td>
                      <td className="py-3 px-5 text-center">
                        <CatBadge cat={s.spec_category ?? "NORMAL"} />
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
