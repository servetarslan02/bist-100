// ALPHA BIST — Market Radar (AG Grid ile)

"use client";

import { useState, useMemo } from "react";
import { usePolling, type Instrument } from "@/lib/api";
import { DataTable, defaultColumnDefs } from "@/components/table/DataTable";
import { useSignalsStore } from "@/lib/store";

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
    <div className="p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Market Radar</h1>
          <p className="text-[11px] text-zinc-600">
            {rowData.length} instruments • live scanning
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search..."
            className="bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1 text-xs text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600 w-40"
          />
          <select
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            className="bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1 text-xs text-zinc-300 focus:outline-none focus:border-zinc-600"
          >
            <option value="">All Sectors</option>
            {sectors.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* AG Grid Table */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg overflow-hidden">
        <DataTable
          rowData={rowData}
          columnDefs={defaultColumnDefs}
          height="calc(100vh - 200px)"
          onRowClick={handleRowClick}
          loading={loading}
        />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-[10px] text-zinc-600">
        <span>Data: yfinance (15min delayed)</span>
        <span>Refresh: 60s</span>
      </div>
    </div>
  );
}
