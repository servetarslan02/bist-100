// ALPHA BIST — AG Grid Data Table Component
// Profesyonel data table: sortable, filterable, virtual scroll

"use client";

import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef, ICellRendererParams } from "ag-grid-community";
import { AllCommunityModule, ModuleRegistry } from "ag-grid-community";

// Register AG Grid modules
ModuleRegistry.registerModules([AllCommunityModule]);

// =====================================================
// Cell Renderers
// =====================================================

function ChangeCellRenderer(params: ICellRendererParams) {
  const value = params.value;
  if (value == null) return <span className="text-zinc-600">—</span>;
  const color = value > 0 ? "text-emerald-400" : value < 0 ? "text-red-400" : "text-zinc-400";
  const prefix = value > 0 ? "+" : "";
  return <span className={`font-mono ${color}`}>{prefix}{value.toFixed(2)}%</span>;
}

function ScoreCellRenderer(params: ICellRendererParams) {
  const value = params.value;
  if (value == null) return <span className="text-zinc-600">—</span>;
  const color = value > 70 ? "text-emerald-400" : value > 30 ? "text-amber-400" : "text-red-400";
  return <span className={`font-mono ${color}`}>{value.toFixed(1)}</span>;
}

function SectorCellRenderer(params: ICellRendererParams) {
  return (
    <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">
      {params.value}
    </span>
  );
}

// =====================================================
// Column Definitions
// =====================================================

export const defaultColumnDefs: ColDef[] = [
  {
    field: "symbol",
    headerName: "TICKER",
    width: 90,
    pinned: "left",
    cellClass: "font-semibold text-zinc-200",
  },
  {
    field: "name",
    headerName: "NAME",
    width: 160,
    cellClass: "text-zinc-500 truncate",
  },
  {
    field: "sector",
    headerName: "SECTOR",
    width: 100,
    cellRenderer: SectorCellRenderer,
  },
  {
    field: "price",
    headerName: "PRICE",
    width: 90,
    cellClass: "font-mono text-right text-zinc-300",
    valueFormatter: (params) => params.value?.toFixed(2) ?? "—",
  },
  {
    field: "change",
    headerName: "CHG%",
    width: 90,
    cellRenderer: ChangeCellRenderer,
  },
  {
    field: "rsi",
    headerName: "RSI",
    width: 70,
    cellRenderer: ScoreCellRenderer,
  },
  {
    field: "mom5",
    headerName: "MOM5",
    width: 80,
    cellRenderer: ChangeCellRenderer,
  },
  {
    field: "mom20",
    headerName: "MOM20",
    width: 80,
    cellRenderer: ChangeCellRenderer,
  },
  {
    field: "vol_z",
    headerName: "VOL Z",
    width: 80,
    cellClass: "font-mono text-right text-zinc-400",
    valueFormatter: (params) => params.value?.toFixed(2) ?? "—",
  },
  {
    field: "anomaly",
    headerName: "ANOM",
    width: 70,
    cellClass: "font-mono text-right",
    cellRenderer: (params: ICellRendererParams) => {
      const v = params.value;
      if (v == null) return <span className="text-zinc-600">—</span>;
      const color = v > 5 ? "text-red-400" : v > 2 ? "text-amber-400" : "text-zinc-400";
      return <span className={`font-mono ${color}`}>{v}</span>;
    },
  },
  {
    field: "spec",
    headerName: "SPEC",
    width: 80,
    cellRenderer: ScoreCellRenderer,
  },
];

// =====================================================
// AG Grid Component
// =====================================================

interface DataTableProps<T extends Record<string, unknown> = Record<string, unknown>> {
  rowData: T[];
  columnDefs?: ColDef[];
  height?: string;
  onRowClick?: (data: T) => void;
  loading?: boolean;
}

export function DataTable({
  rowData,
  columnDefs = defaultColumnDefs,
  height = "600px",
  onRowClick,
  loading = false,
}: DataTableProps) {
  const defaultColDef = useMemo<ColDef>(
    () => ({
      sortable: true,
      filter: true,
      resizable: true,
      suppressMovable: false,
    }),
    []
  );

  return (
    <div className="ag-theme-alpine-dark" style={{ height, width: "100%" }}>
      <AgGridReact
        rowData={rowData}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        rowSelection="single"
        onRowClicked={(e) => onRowClick?.(e.data)}
        animateRows={true}
        rowHeight={32}
        headerHeight={36}
        suppressCellFocus={true}
        loading={loading}
        overlayNoRowsTemplate='<span class="text-zinc-600">No data available</span>'
      />
    </div>
  );
}
