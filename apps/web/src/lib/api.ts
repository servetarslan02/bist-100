// ALPHA BIST - API Client & WebSocket Hook v2.0 (Real-Time Live Streaming)

import { useState, useEffect, useCallback, useRef } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

// =====================================================
// API Client
// =====================================================

export async function api<T>(path: string): Promise<T> {
  const url = path.startsWith('/api') ? path : `/api${path}`;
  const res = await fetch(url, {
    headers: {
      'Accept': 'application/json',
    },
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const url = path.startsWith('/api') ? path : `/api${path}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// =====================================================
// Polling Hook (Ultra-Fast Live Polling: Default 3s)
// =====================================================

export function usePolling<T>(path: string, intervalMs: number = 3000) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [tick, setTick] = useState(0);

  const fetchData = useCallback(async () => {
    try {
      const result = await api<T>(path);
      setData(result);
      setError(null);
      setLastUpdated(new Date());
      setTick(t => t + 1);
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

  return { data, loading, error, lastUpdated, tick, refetch: fetchData };
}

// =====================================================
// WebSocket Hook (Live Streaming)
// =====================================================

export function useWebSocket(channel: string) {
  const [data, setData] = useState<any>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${channel}`;
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => setConnected(false);
      ws.onerror = () => setConnected(false);
      ws.onmessage = (event) => {
        try {
          setData(JSON.parse(event.data));
        } catch {}
      };

      return () => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.close();
        }
      };
    } catch {
      setConnected(false);
    }
  }, [channel]);

  return { data, connected };
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
  price?: number;
  change_pct?: number;
  volume?: number;
  market_cap?: number;
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
  id: number | string;
  alert_type: string;
  severity: "CRITICAL" | "WARNING" | "INFO";
  title: string;
  message: string;
  created_at: string;
  ticker?: string;
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
