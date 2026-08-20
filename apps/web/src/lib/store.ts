// ALPHA BIST — Zustand State Management
// Merkezi state yönetimi

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

// =====================================================
// Market State
// =====================================================

interface MarketState {
  regime: string | null;
  breadth_pct: number | null;
  advancing: number | null;
  declining: number | null;
  avg_rsi: number | null;
  anomaly_count: number | null;
  risk_appetite: number | null;
  timestamp: string | null;
  setMarket: (data: Partial<MarketState>) => void;
}

export const useMarketStore = create<MarketState>()(
  devtools(
    (set) => ({
      regime: null,
      breadth_pct: null,
      advancing: null,
      declining: null,
      avg_rsi: null,
      anomaly_count: null,
      risk_appetite: null,
      timestamp: null,
      setMarket: (data) => set(data),
    }),
    { name: 'market-store' }
  )
);

// =====================================================
// Portfolio State
// =====================================================

interface Position {
  ticker: string;
  name: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  weight_pct: number;
}

interface PortfolioState {
  id: number | null;
  name: string | null;
  initial_capital: number | null;
  current_capital: number | null;
  cash_balance: number | null;
  invested_value: number | null;
  total_pnl: number | null;
  total_return_pct: number | null;
  positions: Position[];
  setPortfolio: (data: Partial<PortfolioState>) => void;
  updatePosition: (ticker: string, data: Partial<Position>) => void;
}

export const usePortfolioStore = create<PortfolioState>()(
  devtools(
    (set) => ({
      id: null,
      name: null,
      initial_capital: null,
      current_capital: null,
      cash_balance: null,
      invested_value: null,
      total_pnl: null,
      total_return_pct: null,
      positions: [],
      setPortfolio: (data) => set(data),
      updatePosition: (ticker, data) =>
        set((state) => ({
          positions: state.positions.map((p) =>
            p.ticker === ticker ? { ...p, ...data } : p
          ),
        })),
    }),
    { name: 'portfolio-store' }
  )
);

// =====================================================
// Signals State
// =====================================================

interface Signal {
  ticker: string;
  name: string;
  score: number;
  direction: string;
  risk_level: string;
  horizon: string;
  expected_return_pct: number;
  spec_category: string;
}

interface SignalsState {
  signals: Signal[];
  selectedTicker: string | null;
  setSignals: (signals: Signal[]) => void;
  selectTicker: (ticker: string | null) => void;
}

export const useSignalsStore = create<SignalsState>()(
  devtools(
    (set) => ({
      signals: [],
      selectedTicker: null,
      setSignals: (signals) => set({ signals }),
      selectTicker: (ticker) => set({ selectedTicker: ticker }),
    }),
    { name: 'signals-store' }
  )
);

// =====================================================
// UI State
// =====================================================

interface UIState {
  sidebarOpen: boolean;
  theme: 'dark' | 'light';
  selectedView: string;
  toggleSidebar: () => void;
  setTheme: (theme: 'dark' | 'light') => void;
  setSelectedView: (view: string) => void;
}

export const useUIStore = create<UIState>()(
  devtools(
    (set) => ({
      sidebarOpen: true,
      theme: 'dark',
      selectedView: 'overview',
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setTheme: (theme) => set({ theme }),
      setSelectedView: (view) => set({ selectedView: view }),
    }),
    { name: 'ui-store' }
  )
);

// =====================================================
// System State
// =====================================================

interface SystemState {
  status: string | null;
  services: Record<string, string>;
  lastUpdate: string | null;
  setSystem: (data: Partial<SystemState>) => void;
}

export const useSystemStore = create<SystemState>()(
  devtools(
    (set) => ({
      status: null,
      services: {},
      lastUpdate: null,
      setSystem: (data) => set(data),
    }),
    { name: 'system-store' }
  )
);
