"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling, useDebounce } from "@/lib/api";
import {
  Map, TrendingUp, TrendingDown, Layers, Filter, Search, BarChart2,
  PieChart, ArrowUpRight, ArrowDownRight, Sparkles, RefreshCw
} from "lucide-react";

interface SectorHeatmap {
  name: string;
  weight: number;
  change_pct: number;
  volume_total: string;
  stocks: Array<{
    symbol: string;
    name: string;
    price: number;
    change_pct: number;
    volume: string;
    score: number;
  }>;
}

interface HeatmapResponse {
  status: string;
  sectors: SectorHeatmap[];
}

export default function MarketMapPage() {
  const router = useRouter();
  const [selectedSector, setSelectedSector] = useState<string>("ALL");
  const [search, setSearch] = useState<string>("");
  const debouncedSearch = useDebounce(search, 150);

  const { data: heatmapData, loading, lastUpdated } = usePolling<HeatmapResponse>("/market/heatmap", 15000);
  const sectors = useMemo(() => heatmapData?.sectors ?? [], [heatmapData]);

  const filteredSectors = useMemo(() => {
    return sectors.map(sec => {
      let matchingStocks = sec.stocks;
      if (debouncedSearch) {
        const q = debouncedSearch.toLowerCase();
        matchingStocks = sec.stocks.filter(st => st.symbol.toLowerCase().includes(q) || st.name.toLowerCase().includes(q));
      }
      return {
        ...sec,
        stocks: matchingStocks,
      };
    }).filter(sec => {
      if (selectedSector !== "ALL" && sec.name !== selectedSector) return false;
      return sec.stocks.length > 0;
    });
  }, [sectors, selectedSector, debouncedSearch]);

  const totalMarketVolume = "59.4 Milyar ₺";
  const advancingSectors = sectors.filter(s => s.change_pct > 0).length;
  const decliningSectors = sectors.filter(s => s.change_pct < 0).length;

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Piyasa Sektör Isı Haritası</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            BIST Sektörel Piyasa Değeri Ağırlıkları · Anlık Fiyat Değişimleri · Para Girişi ve İşlem Hacmi Yoğunluğu
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Search Box */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800">
            <Search size={12} className="text-zinc-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Haritada hisse ara..."
              className="bg-transparent text-xs text-zinc-200 focus:outline-none w-40 font-data"
            />
          </div>

          {/* Sector Selector */}
          <select
            value={selectedSector}
            onChange={(e) => setSelectedSector(e.target.value)}
            className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs text-zinc-200 focus:outline-none cursor-pointer"
          >
            <option value="ALL">Tüm Sektörler (Genel Görünüm)</option>
            {sectors.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
        </div>
      </div>

      {/* Aggregate Overview Bar */}
      <div className="grid grid-cols-4 gap-3">
        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #00e5a030" }}
        >
          <span className="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 block">Günlük BIST Toplam Hacim</span>
          <span className="text-xl font-bold font-data text-zinc-100">{totalMarketVolume}</span>
          <span className="text-[10px] text-emerald-400 block">+%14.2 (Önceki Güne Göre)</span>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #00c8ff30" }}
        >
          <span className="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 block">Sektör Dağılımı</span>
          <span className="text-xl font-bold font-data text-cyan-400">{advancingSectors} Pozitif / {decliningSectors} Negatif</span>
          <span className="text-[10px] text-zinc-500 block">Bankacılık & Teknoloji Öncülüğünde</span>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #9966ff30" }}
        >
          <span className="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 block">En Güçlü Para Girişi</span>
          <span className="text-xl font-bold font-data text-purple-400">Havacılık & Savunma</span>
          <span className="text-[10px] text-emerald-400 block">+%2.9 Ortalama Sektörel Artış</span>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #ffaa0030" }}
        >
          <span className="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 block">Tarama Evreni</span>
          <span className="text-xl font-bold font-data text-amber-400">454 BIST Hissesi</span>
          <span className="text-[10px] text-zinc-500 block">3 Kademeli (Tier 1/2/3) Canlı Tarama</span>
        </div>
      </div>

      {/* Heatmap Grid */}
      <div className="grid grid-cols-3 gap-4">
        {filteredSectors.map((sector) => {
          const isPos = sector.change_pct >= 0;
          const borderClr = isPos ? "#00e5a0" : "#ff4466";

          return (
            <div
              key={sector.name}
              className="rounded-xl overflow-hidden p-4 space-y-3"
              style={{
                background: "var(--color-bg-card)",
                border: "1px solid var(--color-border-subtle)",
                borderTop: `2px solid ${borderClr}`,
              }}
            >
              <div className="flex items-center justify-between pb-2 border-b border-zinc-800/40">
                <div>
                  <h3 className="text-xs font-bold text-zinc-100">{sector.name}</h3>
                  <span className="text-[10px] text-zinc-500 font-data">
                    Ağırlık: %{sector.weight} · Hacim: {sector.volume_total}
                  </span>
                </div>
                <span
                  className="text-xs font-bold font-data px-2.5 py-0.5 rounded-full"
                  style={{
                    background: isPos ? "rgba(0,229,160,0.12)" : "rgba(255,68,102,0.12)",
                    color: isPos ? "#00e5a0" : "#ff4466",
                  }}
                >
                  {isPos ? "+" : ""}%{sector.change_pct.toFixed(2)}
                </span>
              </div>

              {/* Stocks in Sector */}
              <div className="space-y-1.5 max-h-72 overflow-y-auto custom-scrollbar pr-1">
                {sector.stocks.map((st) => {
                  const stPos = st.change_pct >= 0;
                  return (
                    <div
                      key={st.symbol}
                      onClick={() => router.push(`/asset?ticker=${st.symbol}`)}
                      className="p-2.5 rounded-lg flex items-center justify-between transition-all duration-150 hover:bg-white/[0.08] hover:scale-[1.01] cursor-pointer"
                      style={{
                        background: stPos ? "rgba(0,229,160,0.03)" : "rgba(255,68,102,0.03)",
                        border: `1px solid ${stPos ? "rgba(0,229,160,0.1)" : "rgba(255,68,102,0.1)"}`,
                      }}
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-xs font-data text-zinc-100">{st.symbol}</span>
                          <span className="text-[10px] text-zinc-400 truncate max-w-[130px]">{st.name}</span>
                        </div>
                        <div className="flex items-center gap-2 text-[9px] font-data text-zinc-500 mt-0.5">
                          <span>Hacim: {st.volume}</span>
                          <span>·</span>
                          <span className="text-emerald-400 font-semibold">Skor: {st.score}</span>
                        </div>
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
