"use client";

import { useState } from "react";
import {
  TrendingUp, BarChart2, PieChart, Sliders, ShieldCheck,
  Zap, ArrowUpRight, ArrowDownRight, Layers, CheckCircle2, Play
} from "lucide-react";

interface StrategyItem {
  id: string;
  name: string;
  category: string;
  sharpe: number;
  sortino: number;
  cagr: number;
  max_drawdown: number;
  win_rate: number;
  status: "ACTIVE" | "STANDBY" | "BACKTEST";
  description: string;
  allocation: number;
}

const STRATEGIES: StrategyItem[] = [
  {
    id: "risk_parity",
    name: "Risk Parity (Volatilite Dengeli)",
    category: "Portföy Optimizasyonu",
    sharpe: 2.14,
    sortino: 3.42,
    cagr: 38.6,
    max_drawdown: 11.2,
    win_rate: 68.4,
    status: "ACTIVE",
    description: "Varlıkların risk katkılarını eşitleyerek piyasa dalgalanmalarında portföy oynaklığını minimize eden kantitatif model.",
    allocation: 35,
  },
  {
    id: "momentum_breakout",
    name: "Momentum & Kanal Kırılımı",
    category: "Trend Takipçisi",
    sharpe: 1.88,
    sortino: 2.95,
    cagr: 44.2,
    max_drawdown: 16.4,
    win_rate: 61.2,
    status: "ACTIVE",
    description: "20 ve 50 günlük hacimli tepe kırılımlarını ve ADX trend gücünü takip ederek güçlü momentum hisselerinde uzun pozisyon açar.",
    allocation: 30,
  },
  {
    id: "mean_reversion",
    name: "İstatistiki Ortalamaya Dönüş",
    category: "Salınım (Swing)",
    sharpe: 1.65,
    sortino: 2.40,
    cagr: 29.8,
    max_drawdown: 9.8,
    win_rate: 72.1,
    status: "ACTIVE",
    description: "RSI < 30 ve Bollinger Alt Bandı altındaki aşırı satılmış BIST-30 hisselerinde istatistiki tepki alımları hedefler.",
    allocation: 20,
  },
  {
    id: "event_driven",
    name: "KAP & Olay Odaklı Arbitraj",
    category: "Temel & Olay Odaklı",
    sharpe: 1.92,
    sortino: 3.10,
    cagr: 34.5,
    max_drawdown: 8.5,
    win_rate: 76.0,
    status: "STANDBY",
    description: "KAP haber akışındaki sentiment ve finansal bilanço sürprizlerini doğal dil işleme (NLP) ile analiz ederek erken pozisyon alır.",
    allocation: 15,
  },
];

export default function StrategyPage() {
  const [strategies, setStrategies] = useState<StrategyItem[]>(STRATEGIES);
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyItem>(STRATEGIES[0]);

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Kantitatif Strateji & Portföy Motoru</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Risk Parity · Momentum Trend · Mean Reversion · Event-Driven Backtest & Algoritmik Tahsis
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-bold"
            style={{ background: "rgba(0,229,160,0.08)", border: "1px solid rgba(0,229,160,0.2)", color: "#00e5a0" }}
          >
            <ShieldCheck size={14} />
            4 Model Aktif
          </div>
        </div>
      </div>

      {/* Aggregate Performance Cards */}
      <div className="grid grid-cols-5 gap-3">
        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #00e5a030" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Ortalama Sharpe Oranı</p>
          <p className="text-2xl font-bold font-data" style={{ color: "#00e5a0" }}>1.95</p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Risk Düzeltilmiş Üstün Getiri</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #00c8ff30" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Kombine Yıllık Getiri (CAGR)</p>
          <p className="text-2xl font-bold font-data" style={{ color: "#00c8ff" }}>+%38.2</p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>BIST-100 Alfa: +%19.4</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #ffaa0030" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Kombine Maksimum Drawdown</p>
          <p className="text-2xl font-bold font-data" style={{ color: "#ffaa00" }}>-%11.8</p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Tarihsel Tepe Düşüşü</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #9966ff30" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Sortino Oranı (Aşağı Yönlü Risk)</p>
          <p className="text-2xl font-bold font-data" style={{ color: "#9966ff" }}>3.02</p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Zarar Volatilitesi Düşük</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #00e5a030" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>Genel İşlem Başarı Oranı</p>
          <p className="text-2xl font-bold font-data" style={{ color: "#00e5a0" }}>%69.4</p>
          <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Kârlı Kapanan Pozisyonlar</p>
        </div>
      </div>

      {/* Strategy Allocation & Comparison */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
        >
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "rgba(0,229,160,0.12)" }}>
              <Sliders size={13} style={{ color: "#00e5a0" }} />
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>
              Aktif Kantitatif Stratejiler & Portföy Ağırlıkları
            </h2>
          </div>
          <span className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Toplam Portföy Dağılımı: %100</span>
        </div>

        <div className="p-5 space-y-4">
          {strategies.map((st) => {
            const isSelected = selectedStrategy.id === st.id;
            return (
              <div
                key={st.id}
                onClick={() => setSelectedStrategy(st)}
                className="rounded-xl p-4 cursor-pointer transition-all duration-200 select-none"
                style={{
                  background: isSelected ? "rgba(0,229,160,0.06)" : "var(--color-bg-elevated)",
                  border: `1px solid ${isSelected ? "rgba(0,229,160,0.3)" : "var(--color-border-subtle)"}`,
                }}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full" style={{ background: st.status === "ACTIVE" ? "#00e5a0" : "#ffaa00" }} />
                    <h3 className="text-sm font-bold" style={{ color: "var(--color-text-primary)" }}>{st.name}</h3>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 font-medium">
                      {st.category}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-bold font-data" style={{ color: "#00e5a0" }}>
                      Tahsis: %{st.allocation}
                    </span>
                    <span
                      className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                      style={{
                        background: st.status === "ACTIVE" ? "rgba(0,229,160,0.12)" : "rgba(255,170,0,0.12)",
                        color: st.status === "ACTIVE" ? "#00e5a0" : "#ffaa00",
                      }}
                    >
                      {st.status === "ACTIVE" ? "CANLI ÇALIŞIYOR" : "BEKLEMEDE"}
                    </span>
                  </div>
                </div>

                <p className="text-[11px] leading-relaxed mb-3" style={{ color: "var(--color-text-secondary)" }}>
                  {st.description}
                </p>

                {/* Progress Allocation Bar */}
                <div className="w-full h-1.5 rounded-full overflow-hidden bg-zinc-800 mb-3">
                  <div className="h-full rounded-full" style={{ width: `${st.allocation}%`, background: "linear-gradient(90deg, #00e5a0, #00c8ff)" }} />
                </div>

                {/* Metrics Row */}
                <div className="grid grid-cols-5 gap-2 pt-2 border-t border-zinc-800/40 text-[11px] font-data">
                  <div>
                    <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Sharpe</span>
                    <span className="font-bold text-zinc-200">{st.sharpe}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Sortino</span>
                    <span className="font-bold text-zinc-200">{st.sortino}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Yıllık CAGR</span>
                    <span className="font-bold text-emerald-400">+%{st.cagr}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Maks. Drawdown</span>
                    <span className="font-bold text-amber-400">-%{st.max_drawdown}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase tracking-wider text-zinc-500 block">Kazanma Oranı</span>
                    <span className="font-bold text-cyan-400">%{st.win_rate}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
