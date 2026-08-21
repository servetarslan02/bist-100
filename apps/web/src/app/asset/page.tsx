"use client";

import { useState } from "react";
import {
  LineChart, Search, TrendingUp, TrendingDown, DollarSign,
  BarChart3, Activity, PieChart, ShieldCheck, Zap
} from "lucide-react";

interface AssetProfile {
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
  sector: string;
  market_cap: string;
  pe_ratio: number;
  pb_ratio: number;
  rsi_14: number;
  macd_signal: string;
  support: number;
  resistance: number;
  recommendation: "STRONG_BUY" | "BUY" | "HOLD";
}

const ASSET_DATA: AssetProfile = {
  symbol: "THYAO",
  name: "Türk Hava Yolları A.O.",
  price: 312.50,
  change_pct: 2.85,
  sector: "Havacılık & Ulaştırma",
  market_cap: "431.2 Milyar ₺",
  pe_ratio: 4.8,
  pb_ratio: 0.95,
  rsi_14: 62.4,
  macd_signal: "POZİTİF KESİŞİM (AL)",
  support: 298.0,
  resistance: 325.0,
  recommendation: "STRONG_BUY",
};

export default function AssetIntelPage() {
  const [ticker, setTicker] = useState("THYAO");
  const [asset] = useState<AssetProfile>(ASSET_DATA);

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header & Search */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Tekil Varlık & Derinlik Analizi</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            BIST Şirket Değerleme Çarpanları · Teknik Göstergeler · Destek / Direnç Seviyeleri
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800">
            <Search size={12} className="text-zinc-500" />
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="Hisse Kodu (Örn: THYAO)..."
              className="bg-transparent text-xs text-zinc-200 focus:outline-none w-36 font-data"
            />
          </div>
        </div>
      </div>

      {/* Asset Hero Card */}
      <div
        className="rounded-xl p-5 select-none"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl flex items-center justify-center bg-emerald-500/10 border border-emerald-500/20">
              <span className="text-base font-bold font-data text-emerald-400">{asset.symbol}</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-zinc-100">{asset.name}</h2>
                <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 font-medium">{asset.sector}</span>
              </div>
              <p className="text-[11px] text-zinc-500 mt-0.5">Piyasa Değeri: {asset.market_cap}</p>
            </div>
          </div>

          <div className="text-right">
            <span className="text-2xl font-bold font-data block text-zinc-100">₺{asset.price.toFixed(2)}</span>
            <span className="text-xs font-bold font-data text-emerald-400">
              +%{asset.change_pct.toFixed(2)} (Bugün)
            </span>
          </div>
        </div>
      </div>

      {/* Multi-Indicator Cards */}
      <div className="grid grid-cols-4 gap-3">
        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <span className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500 block">Fiyat / Kazanç (F/K)</span>
          <span className="text-xl font-bold font-data text-emerald-400">{asset.pe_ratio}x</span>
          <span className="text-[10px] text-zinc-500 block">Sektör Ortalaması: 7.2x (İskontolu)</span>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <span className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500 block">Piyasa / Defter Değeri (PD/DD)</span>
          <span className="text-xl font-bold font-data text-cyan-400">{asset.pb_ratio}x</span>
          <span className="text-[10px] text-zinc-500 block">Özkaynak Güçlü</span>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <span className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500 block">14 Günlük RSI</span>
          <span className="text-xl font-bold font-data text-zinc-200">{asset.rsi_14}</span>
          <span className="text-[10px] text-emerald-400 block">Pozitif Momentum Bölgesinde</span>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
        >
          <span className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500 block">Model Kararı</span>
          <span className="text-xl font-bold font-data text-emerald-400">GÜÇLÜ AL</span>
          <span className="text-[10px] text-zinc-500 block">Güven Seviyesi: %88</span>
        </div>
      </div>

      {/* Support & Resistance */}
      <div
        className="rounded-xl p-5"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-300 mb-4">Teknik Seviyeler & Pivotlar</h3>
        <div className="flex items-center justify-between p-4 rounded-lg bg-zinc-900/60 border border-zinc-800/40 text-xs font-data">
          <div>
            <span className="text-[10px] text-zinc-500 uppercase block">Kritik Destek (S1)</span>
            <span className="text-sm font-bold text-red-400">₺{asset.support.toFixed(2)}</span>
          </div>
          <div className="text-center">
            <span className="text-[10px] text-zinc-500 uppercase block">Mevcut Fiyat</span>
            <span className="text-base font-bold text-zinc-100">₺{asset.price.toFixed(2)}</span>
          </div>
          <div className="text-right">
            <span className="text-[10px] text-zinc-500 uppercase block">Hedef Direnç (R1)</span>
            <span className="text-sm font-bold text-emerald-400">₺{asset.resistance.toFixed(2)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
