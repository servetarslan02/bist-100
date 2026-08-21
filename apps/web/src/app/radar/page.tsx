"use client";

import { useState, useMemo } from "react";
import { usePolling, type Instrument } from "@/lib/api";
import { DataTable, defaultColumnDefs } from "@/components/table/DataTable";
import { useSignalsStore } from "@/lib/store";
import { Radar, Search, Filter, RefreshCw } from "lucide-react";

interface EnrichedInstrument extends Instrument {
  price?: number;
  rsi?: number;
  mom5?: number;
  mom20?: number;
  vol_z?: number;
  anomaly?: number;
  spec?: number;
  change?: number;
}

export default function MarketRadar() {
  const { data: instruments, loading } = usePolling<Instrument[]>(
    "/market/instruments?limit=500",
    60000
  );
  const { selectTicker } = useSignalsStore();
  const [search, setSearch] = useState("");
  const [sector, setSector] = useState("");

  const sectors = useMemo(() => {
    if (!instruments) return [];
    return [...new Set(instruments.map((i) => i.sector))].sort();
  }, [instruments]);

  const rowData = useMemo(() => {
    if (!instruments) return [];
    return instruments
      .filter((i) => {
        if (
          search &&
          !i.symbol.toLowerCase().includes(search.toLowerCase()) &&
          !i.name.toLowerCase().includes(search.toLowerCase())
        )
          return false;
        if (sector && i.sector !== sector) return false;
        return true;
      })
      .map((i) => ({
        ...i,
        price: undefined,
        change: undefined,
        rsi: undefined,
        mom5: undefined,
        mom20: undefined,
        vol_z: undefined,
        anomaly: undefined,
        spec: undefined,
      }));
  }, [instruments, search, sector]);

  const handleRowClick = (data: EnrichedInstrument) => {
    selectTicker(data.symbol);
  };

  return (
    <div className="p-5 space-y-4 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Piyasa Radarı</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            {rowData.length} BIST hissesi · canlı anomali ve momentum taraması
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Search */}
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-lg"
            style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
          >
            <Search size={12} style={{ color: "var(--color-text-muted)" }} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Sembol veya şirket ara..."
              className="bg-transparent text-xs focus:outline-none w-48"
              style={{ color: "var(--color-text-primary)" }}
            />
          </div>
          {/* Sector filter */}
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-lg"
            style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
          >
            <Filter size={12} style={{ color: "var(--color-text-muted)" }} />
            <select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="bg-transparent text-xs focus:outline-none cursor-pointer"
              style={{ color: "var(--color-text-primary)" }}
            >
              <option value="" style={{ background: "#0d111a" }}>Tüm Sektörler</option>
              {sectors.map((s) => (
                <option key={s} value={s} style={{ background: "#0d111a" }}>{s}</option>
              ))}
            </select>
          </div>
          {/* Refresh indicator */}
          <div
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg"
            style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
          >
            <RefreshCw size={11} style={{ color: "var(--color-text-muted)" }} className={loading ? "animate-spin" : ""} />
            <span className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>60sn</span>
          </div>
        </div>
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
            <Radar size={13} style={{ color: "#00e5a0" }} />
          </div>
          <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-primary)" }}>
            Hisse Senetleri Listesi
          </h2>
        </div>
        <DataTable
          rowData={rowData}
          columnDefs={defaultColumnDefs}
          height="calc(100vh - 220px)"
          onRowClick={handleRowClick}
          loading={loading}
        />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-[10px]" style={{ color: "var(--color-text-faint)" }}>
        <span>Veri: yfinance (15 dk gecikmeli)</span>
        <span>Otomatik Yenileme: Her 60 saniyede bir</span>
      </div>
    </div>
  );
}
