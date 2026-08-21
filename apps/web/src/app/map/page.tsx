"use client";

import { useState } from "react";
import {
  Map, TrendingUp, TrendingDown, Layers, Filter, RefreshCw, BarChart2
} from "lucide-react";

interface SectorHeatmap {
  name: string;
  weight: number;
  change_pct: number;
  stocks: Array<{
    symbol: string;
    name: string;
    price: number;
    change_pct: number;
    volume: string;
    market_cap_weight: number;
  }>;
}

const SECTORS_DATA: SectorHeatmap[] = [
  {
    name: "Bankacılık & Finans",
    weight: 28,
    change_pct: 1.84,
    stocks: [
      { symbol: "GARAN", name: "Garanti BBVA", price: 118.5, change_pct: 2.15, volume: "4.2B ₺", market_cap_weight: 35 },
      { symbol: "AKBNK", name: "Akbank", price: 58.2, change_pct: 1.75, volume: "3.8B ₺", market_cap_weight: 30 },
      { symbol: "ISCTR", name: "İş Bankası (C)", price: 14.85, change_pct: 1.92, volume: "3.1B ₺", market_cap_weight: 20 },
      { symbol: "YKBNK", name: "Yapı Kredi", price: 31.4, change_pct: 1.25, volume: "2.4B ₺", market_cap_weight: 15 },
    ],
  },
  {
    name: "Holding & Yatırım",
    weight: 22,
    change_pct: 0.92,
    stocks: [
      { symbol: "KCHOL", name: "Koç Holding", price: 212.0, change_pct: 1.45, volume: "2.9B ₺", market_cap_weight: 45 },
      { symbol: "SAHOL", name: "Sabancı Holding", price: 96.5, change_pct: 0.85, volume: "1.8B ₺", market_cap_weight: 30 },
      { symbol: "SISE", name: "Şişecam", price: 48.2, change_pct: -0.42, volume: "1.2B ₺", market_cap_weight: 25 },
    ],
  },
  {
    name: "Sanayi & Üretim",
    weight: 18,
    change_pct: -0.35,
    stocks: [
      { symbol: "TUPRS", name: "Tüpraş", price: 174.2, change_pct: 0.65, volume: "3.5B ₺", market_cap_weight: 40 },
      { symbol: "EREGL", name: "Ereğli Demir Çelik", price: 52.4, change_pct: -1.25, volume: "2.1B ₺", market_cap_weight: 35 },
      { symbol: "FROTO", name: "Ford Otosan", price: 1045.0, change_pct: -0.55, volume: "1.4B ₺", market_cap_weight: 25 },
    ],
  },
  {
    name: "Havacılık & Ulaştırma",
    weight: 14,
    change_pct: 2.45,
    stocks: [
      { symbol: "THYAO", name: "Türk Hava Yolları", price: 312.5, change_pct: 2.85, volume: "5.8B ₺", market_cap_weight: 65 },
      { symbol: "PGSUS", name: "Pegasus", price: 238.0, change_pct: 1.70, volume: "1.6B ₺", market_cap_weight: 35 },
    ],
  },
  {
    name: "Teknoloji & Savunma",
    weight: 10,
    change_pct: 3.12,
    stocks: [
      { symbol: "ASELS", name: "Aselsan", price: 64.8, change_pct: 3.65, volume: "3.2B ₺", market_cap_weight: 70 },
      { symbol: "KFEIN", name: "Kafein Yazılım", price: 142.0, change_pct: 1.85, volume: "420M ₺", market_cap_weight: 30 },
    ],
  },
  {
    name: "Enerji & Dağıtım",
    weight: 8,
    change_pct: -0.85,
    stocks: [
      { symbol: "ENJSA", name: "Enerjisa", price: 62.4, change_pct: -0.65, volume: "850M ₺", market_cap_weight: 50 },
      { symbol: "ASTOR", name: "Astor Enerji", price: 98.2, change_pct: -1.05, volume: "1.1B ₺", market_cap_weight: 50 },
    ],
  },
];

export default function MarketMapPage() {
  const [selectedSector, setSelectedSector] = useState<string>("ALL");

  const filtered = selectedSector === "ALL" 
    ? SECTORS_DATA 
    : SECTORS_DATA.filter(s => s.name === selectedSector);

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Piyasa Isı Haritası (Sektörel Dağılım)</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            BIST Sektörel Piyasa Değeri Ağırlıkları · Anlık Fiyat Değişimleri · Para Girişi ve İşlem Hacmi Yoğunluğu
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={selectedSector}
            onChange={(e) => setSelectedSector(e.target.value)}
            className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs text-zinc-200 focus:outline-none"
          >
            <option value="ALL">Tüm Sektörler</option>
            {SECTORS_DATA.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
        </div>
      </div>

      {/* Heatmap Grid */}
      <div className="grid grid-cols-3 gap-4">
        {filtered.map((sector) => {
          const isPos = sector.change_pct >= 0;
          return (
            <div
              key={sector.name}
              className="rounded-xl overflow-hidden p-4 space-y-3"
              style={{
                background: "var(--color-bg-card)",
                border: "1px solid var(--color-border-subtle)",
                borderTop: `2px solid ${isPos ? "#00e5a0" : "#ff4466"}`,
              }}
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-bold" style={{ color: "var(--color-text-primary)" }}>{sector.name}</h3>
                  <span className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>Ağırlık: %{sector.weight}</span>
                </div>
                <span
                  className="text-xs font-bold font-data px-2 py-0.5 rounded-full"
                  style={{
                    background: isPos ? "rgba(0,229,160,0.12)" : "rgba(255,68,102,0.12)",
                    color: isPos ? "#00e5a0" : "#ff4466",
                  }}
                >
                  {isPos ? "+" : ""}%{sector.change_pct.toFixed(2)}
                </span>
              </div>

              {/* Stocks in Sector */}
              <div className="space-y-2 pt-2 border-t border-zinc-800/40">
                {sector.stocks.map((st) => {
                  const stPos = st.change_pct >= 0;
                  return (
                    <div
                      key={st.symbol}
                      className="p-2.5 rounded-lg flex items-center justify-between transition-colors hover:bg-white/5 cursor-pointer"
                      style={{
                        background: stPos ? "rgba(0,229,160,0.04)" : "rgba(255,68,102,0.04)",
                        border: `1px solid ${stPos ? "rgba(0,229,160,0.1)" : "rgba(255,68,102,0.1)"}`,
                      }}
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-xs font-data" style={{ color: "var(--color-text-primary)" }}>{st.symbol}</span>
                          <span className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>{st.name}</span>
                        </div>
                        <span className="text-[9px] font-data text-zinc-500">Hacim: {st.volume}</span>
                      </div>
                      <div className="text-right">
                        <span className="text-xs font-bold font-data block text-zinc-200">₺{st.price.toFixed(2)}</span>
                        <span className="text-[10px] font-bold font-data" style={{ color: stPos ? "#00e5a0" : "#ff4466" }}>
                          {stPos ? "+" : ""}%{st.change_pct.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
