// ALPHA BIST - API Client & WebSocket Hook

import { useState, useEffect, useCallback, useRef } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

// =====================================================
// API Client
// =====================================================

export async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}/api${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// =====================================================
// WebSocket Hook (Live Updates)
// =====================================================

export function useWebSocket(channel: string) {
  const [data, setData] = useState<any>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const wsUrl = `ws://${window.location.host}/ws/${channel}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        setData(JSON.parse(event.data));
      } catch {}
    };

    return () => ws.close();
  }, [channel]);

  return { data, connected };
}

// =====================================================
// Polling Hook (HTTP fallback)
// =====================================================

export function usePolling<T>(path: string, intervalMs: number = 30000) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const result = await api<T>(path);
      setData(result);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, intervalMs);
    return () => clearInterval(timer);
  }, [fetchData, intervalMs]);

  return { data, loading, error, refetch: fetchData };
}

// =====================================================
// Types
// =====================================================

export interface MarketState {
  regime: string;
  breadth_pct: number;
  advancing: number;
  declining: number;
  avg_rsi: number;
  avg_momentum: number;
  avg_volatility: number;
  anomaly_count: number;
  risk_appetite: number;
  timestamp: string;
}

export interface Signal {
  ticker: string;
  name: string;
  score: number;
  direction: string;
  risk_level: string;
  horizon: string;
  expected_return_pct: number;
  spec_category: string;
}

export interface Instrument {
  symbol: string;
  name: string;
  sector: string;
}

export interface AssetData {
  instrument: Instrument;
  features: Record<string, string>;
}

export interface PortfolioData {
  portfolio: {
    id: number;
    name: string;
    initial_capital: number;
    current_capital: number;
    cash_balance: number;
    invested_value: number;
    total_pnl: number;
    total_return_pct: number;
  };
  positions: Array<{
    ticker: string;
    name: string;
    quantity: number;
    avg_cost: number;
    current_price: number;
    market_value: number;
    unrealized_pnl: number;
    unrealized_pnl_pct: number;
    weight_pct: number;
  }>;
}

export interface Alert {
  id: number;
  alert_type: string;
  severity: string;
  title: string;
  message: string;
  created_at: string;
}

export interface ModelInfo {
  id: number;
  name: string;
  description: string;
  model_type: string;
  status: string;
  latest_version: string;
  latest_status: string;
  metrics: Record<string, number>;
}

export interface WorldState {
  global_risk_appetite: number;
  usd_strength: number;
  us_rate_pressure: number;
  commodity_pressure: number;
  oil_pressure: number;
  turkey_macro_risk: number;
  geopolitical_risk: number;
  em_risk_appetite: number;
  vix_level: number;
  inflation_pressure: number;
  timestamp: string;
}

export interface SystemStatus {
  status: string;
  services: Record<string, string>;
  timestamp: string;
}
