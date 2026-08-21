"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling } from "@/lib/api";
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

const FALLBACK_SECTORS: SectorHeatmap[] = [
  {
    name: "Bankacılık & Finans",
    weight: 22.5,
    change_pct: 1.84,
    volume_total: "14.2 Milyar ₺",
    stocks: [
      { symbol: "GARAN", name: "Garanti BBVA", price: 118.50, change_pct: 2.15, volume: "4.2B ₺", score: 88 },
      { symbol: "AKBNK", name: "Akbank", price: 58.20, change_pct: 1.75, volume: "3.8B ₺", score: 84 },
      { symbol: "ISCTR", name: "İş Bankası (C)", price: 14.85, change_pct: 1.92, volume: "3.1B ₺", score: 82 },
      { symbol: "YKBNK", name: "Yapı Kredi", price: 31.40, change_pct: 1.25, volume: "2.4B ₺", score: 80 },
      { symbol: "VAKBN", name: "Vakıfbank", price: 21.20, change_pct: 1.10, volume: "980M ₺", score: 76 },
      { symbol: "HALKB", name: "Halkbank", price: 17.65, change_pct: 0.85, volume: "740M ₺", score: 74 },
      { symbol: "ISMEN", name: "İş Yatırım Menkul", price: 38.40, change_pct: 2.40, volume: "520M ₺", score: 81 },
      { symbol: "TSKB", name: "T.S.K.B.", price: 11.20, change_pct: 1.45, volume: "410M ₺", score: 78 },
    ],
  },
  {
    name: "Holding & Yatırım",
    weight: 18.0,
    change_pct: 1.12,
    volume_total: "9.8 Milyar ₺",
    stocks: [
      { symbol: "KCHOL", name: "Koç Holding", price: 212.00, change_pct: 1.45, volume: "3.4B ₺", score: 86 },
      { symbol: "SAHOL", name: "Sabancı Holding", price: 96.50, change_pct: 0.85, volume: "2.1B ₺", score: 80 },
      { symbol: "ALARK", name: "Alarko Holding", price: 104.20, change_pct: 1.65, volume: "1.2B ₺", score: 82 },
      { symbol: "ENKAI", name: "Enka İnşaat", price: 44.10, change_pct: 0.90, volume: "890M ₺", score: 75 },
      { symbol: "AGHOL", name: "Anadolu Grubu", price: 318.00, change_pct: 1.80, volume: "650M ₺", score: 83 },
      { symbol: "DOHOL", name: "Doğan Holding", price: 15.40, change_pct: 0.45, volume: "420M ₺", score: 72 },
    ],
  },
  {
    name: "Havacılık & Ulaştırma",
    weight: 14.5,
    change_pct: 2.35,
    volume_total: "8.6 Milyar ₺",
    stocks: [
      { symbol: "THYAO", name: "Türk Hava Yolları", price: 312.50, change_pct: 2.85, volume: "5.8B ₺", score: 91 },
      { symbol: "PGSUS", name: "Pegasus", price: 238.00, change_pct: 1.70, volume: "1.9B ₺", score: 84 },
      { symbol: "TAVHL", name: "TAV Havalimanları", price: 245.00, change_pct: 1.95, volume: "920M ₺", score: 83 },
      { symbol: "CLEBI", name: "Çelebi Hava Servisi", price: 1850.00, change_pct: 2.10, volume: "310M ₺", score: 79 },
    ],
  },
  {
    name: "Sanayi, Demir-Çelik & Üretim",
    weight: 12.0,
    change_pct: -0.45,
    volume_total: "6.2 Milyar ₺",
    stocks: [
      { symbol: "EREGL", name: "Ereğli Demir Çelik", price: 52.40, change_pct: -1.25, volume: "2.4B ₺", score: 68 },
      { symbol: "KRDMD", name: "Kardemir (D)", price: 28.10, change_pct: -0.85, volume: "1.1B ₺", score: 70 },
      { symbol: "SISE", name: "Şişecam", price: 48.20, change_pct: -0.42, volume: "1.4B ₺", score: 73 },
      { symbol: "ARCLK", name: "Arçelik", price: 168.50, change_pct: 0.35, volume: "680M ₺", score: 75 },
      { symbol: "VESTL", name: "Vestel Elektronik", price: 82.40, change_pct: -0.70, volume: "420M ₺", score: 69 },
      { symbol: "CIMSA", name: "Çimsa Çimento", price: 36.80, change_pct: 0.85, volume: "380M ₺", score: 77 },
    ],
  },
  {
    name: "Savunma & Teknoloji",
    weight: 10.5,
    change_pct: 2.90,
    volume_total: "5.4 Milyar ₺",
    stocks: [
      { symbol: "ASELS", name: "Aselsan", price: 64.80, change_pct: 3.65, volume: "3.2B ₺", score: 90 },
      { symbol: "KFEIN", name: "Kafein Yazılım", price: 142.00, change_pct: 2.15, volume: "480M ₺", score: 82 },
      { symbol: "LOGO", name: "Logo Yazılım", price: 94.50, change_pct: 1.80, volume: "390M ₺", score: 80 },
      { symbol: "MIATK", name: "Mia Teknoloji", price: 68.20, change_pct: 3.10, volume: "740M ₺", score: 85 },
      { symbol: "VBTYZ", name: "VBT Yazılım", price: 42.10, change_pct: 2.45, volume: "290M ₺", score: 78 },
      { symbol: "SDTTR", name: "SDT Uzay Savunma", price: 285.00, change_pct: 3.40, volume: "410M ₺", score: 86 },
    ],
  },
  {
    name: "Enerji & Petrol Rafineri",
    weight: 9.0,
    change_pct: 0.35,
    volume_total: "7.1 Milyar ₺",
    stocks: [
      { symbol: "TUPRS", name: "Tüpraş", price: 174.20, change_pct: 0.65, volume: "3.5B ₺", score: 82 },
      { symbol: "ASTOR", name: "Astor Enerji", price: 98.20, change_pct: -1.05, volume: "1.3B ₺", score: 71 },
      { symbol: "ENJSA", name: "Enerjisa", price: 62.40, change_pct: -0.65, volume: "850M ₺", score: 73 },
      { symbol: "AKSEN", name: "Aksa Enerji", price: 42.80, change_pct: 0.40, volume: "510M ₺", score: 74 },
      { symbol: "EUPWR", name: "Europower Enerji", price: 112.40, change_pct: 1.25, volume: "620M ₺", score: 77 },
      { symbol: "KONTR", name: "Kontrolmatik", price: 56.40, change_pct: 1.85, volume: "490M ₺", score: 79 },
    ],
  },
  {
    name: "Otomotiv & Yan Sanayi",
    weight: 7.5,
    change_pct: 0.15,
    volume_total: "3.8 Milyar ₺",
    stocks: [
      { symbol: "FROTO", name: "Ford Otosan", price: 1045.00, change_pct: -0.55, volume: "1.4B ₺", score: 76 },
      { symbol: "TOASO", name: "Tofaş Oto", price: 232.00, change_pct: 0.45, volume: "1.1B ₺", score: 77 },
      { symbol: "TTRAK", name: "Türk Traktör", price: 820.00, change_pct: 0.85, volume: "560M ₺", score: 79 },
      { symbol: "DOAS", name: "Doğuş Otomotiv", price: 268.00, change_pct: 0.20, volume: "480M ₺", score: 75 },
      { symbol: "OTKAR", name: "Otokar", price: 495.00, change_pct: 1.15, volume: "310M ₺", score: 80 },
    ],
  },
  {
    name: "Perakende, Gıda & İçecek",
    weight: 6.0,
    change_pct: 0.72,
    volume_total: "4.1 Milyar ₺",
    stocks: [
      { symbol: "BIMAS", name: "BİM Mağazalar", price: 485.00, change_pct: 0.45, volume: "1.8B ₺", score: 81 },
      { symbol: "MGROS", name: "Migros Ticaret", price: 492.00, change_pct: 1.20, volume: "950M ₺", score: 83 },
      { symbol: "CCOLA", name: "Coca-Cola İçecek", price: 72.50, change_pct: 1.65, volume: "620M ₺", score: 84 },
      { symbol: "ULKER", name: "Ülker Bisküvi", price: 165.00, change_pct: 0.35, volume: "490M ₺", score: 78 },
      { symbol: "SOKM", name: "Şok Marketler", price: 54.20, change_pct: -0.25, volume: "310M ₺", score: 72 },
    ],
  },
];

export default function MarketMapPage() {
  const router = useRouter();
  const [selectedSector, setSelectedSector] = useState<string>("ALL");
  const [search, setSearch] = useState<string>("");

  const { data: heatmapData, loading, lastUpdated } = usePolling<HeatmapResponse>("/market/heatmap", 15000);
  const sectors = useMemo(() => heatmapData?.sectors ?? FALLBACK_SECTORS, [heatmapData]);

  const filteredSectors = useMemo(() => {
    return sectors.map(sec => {
      let matchingStocks = sec.stocks;
      if (search) {
        const q = search.toLowerCase();
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
  }, [sectors, selectedSector, search]);

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
