// ALPHA BIST - Institutional-Grade API Client, SWR Cache, Deduplication & Real-Time WebSockets v3.0

import { useState, useEffect, useCallback, useRef } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

// =====================================================
// API Client & Normalizer
// =====================================================

function normalizeApiPath(path: string): string {
  let p = path.startsWith('/') ? path : `/${path}`;
  if (p.startsWith('/api/v1/')) return p;
  if (p.startsWith('/api/')) {
    p = p.replace('/api/', '/api/v1/');
    return p;
  }
  if (p.startsWith('/v1/')) return `/api${p}`;

  // Smart aliases
  if (p === '/portfolio') return '/api/v1/portfolio/state';
  if (p === '/world/state' || p === '/world') return '/api/v1/macro/world';
  if (p === '/models') return '/api/v1/models/registry';
  if (p === '/events') return '/api/v1/event-study/events';
  if (p.startsWith('/signals')) return p.replace('/signals', '/api/v1/scanner/signals');
  if (p === '/status') return '/api/v1/system/status';
  if (p === '/decisions/signals') return '/api/v1/scanner/signals';
  if (p === '/decisions/rankings') return '/api/v1/scanner/rankings';

  return `/api/v1${p}`;
}

// 1 & 4. Global In-Memory Cache, In-Flight Request Deduplication Bus & Global PubSub
const memoryCache = new Map<string, { data: unknown; timestamp: number }>();
const inFlightRequests = new Map<string, Promise<unknown>>();
const cacheSubscribers = new Map<string, Set<(data: unknown) => void>>();

let lastGlobalSyncTimestamp = Date.now();
const syncStatusListeners = new Set<(ts: number) => void>();

export function useGlobalSyncStatus() {
  const [lastSync, setLastSync] = useState(lastGlobalSyncTimestamp);
  const [secondsAgo, setSecondsAgo] = useState(0);

  useEffect(() => {
    const handler = (ts: number) => {
      setLastSync(ts);
      setSecondsAgo(0);
    };
    syncStatusListeners.add(handler);

    const interval = setInterval(() => {
      setSecondsAgo(Math.max(0, Math.floor((Date.now() - lastGlobalSyncTimestamp) / 1000)));
    }, 1000);

    return () => {
      syncStatusListeners.delete(handler);
      clearInterval(interval);
    };
  }, []);

  return { lastSync: new Date(lastSync), secondsAgo };
}

function subscribeToCache(key: string, callback: (data: unknown) => void) {
  if (!cacheSubscribers.has(key)) {
    cacheSubscribers.set(key, new Set());
  }
  cacheSubscribers.get(key)!.add(callback);
  return () => {
    cacheSubscribers.get(key)?.delete(callback);
  };
}

function notifyCacheSubscribers(key: string, data: unknown) {
  lastGlobalSyncTimestamp = Date.now();
  syncStatusListeners.forEach(cb => {
    try { cb(lastGlobalSyncTimestamp); } catch {}
  });

  const listeners = cacheSubscribers.get(key);
  if (listeners) {
    listeners.forEach(cb => {
      try { cb(data); } catch {}
    });
  }
}

// 5. LocalStorage Hydration Helper (Instant Zero-Lag Hydration)
function getInitialCachedData<T>(key: string): T | null {
  if (memoryCache.has(key)) {
    return memoryCache.get(key)!.data as T;
  }
  if (typeof window !== 'undefined') {
    try {
      const stored = localStorage.getItem(`ALPHA_CACHE_${key}`);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed && parsed.data !== undefined) {
          memoryCache.set(key, { data: parsed.data, timestamp: parsed.timestamp || Date.now() });
          return parsed.data as T;
        }
      }
    } catch {}
  }
  return null;
}

// Public helper: bazi sayfalar (orn. Asset Intel) usePolling kullanmiyor,
// kendi useEffect'i icinde manuel fetch yapiyor. Bu sayfalarin da anlik
// cache'ten okuyup 0ms gosterebilmesi icin getInitialCachedData disari acildi.
export function getCachedData<T>(key: string): T | null {
  return getInitialCachedData<T>(key);
}

function persistCacheLocally(key: string, data: unknown) {
  memoryCache.set(key, { data, timestamp: Date.now() });
  notifyCacheSubscribers(key, data);

  // Non-blocking asynchronous persistence to avoid freezing UI click events
  if (typeof window !== 'undefined') {
    const defer = typeof window.requestIdleCallback === 'function' 
      ? window.requestIdleCallback 
      : (cb: () => void) => setTimeout(cb, 16);

    defer(() => {
      try {
        if (key.length < 120) {
          const serialized = JSON.stringify({ data, timestamp: Date.now() });
          // Only persist manageable sizes (< 500KB) to prevent synchronous browser I/O locks
          if (serialized.length < 500000) {
            localStorage.setItem(`ALPHA_CACHE_${key}`, serialized);
          }
        }
      } catch {}
    });
  }
}

export async function api<T>(path: string): Promise<T> {
  const url = normalizeApiPath(path);

  // Request Deduplication
  if (inFlightRequests.has(url)) {
    return inFlightRequests.get(url) as Promise<T>;
  }

  const fetchPromise = (async () => {
    try {
      const res = await fetch(url, {
        headers: {
          'Accept': 'application/json',
        },
        cache: 'no-store',
      });
      if (!res.ok) throw new Error(`API error: ${res.status} (${url})`);
      const data = await res.json();
      persistCacheLocally(path, data);
      return data;
    } finally {
      inFlightRequests.delete(url);
    }
  })();

  inFlightRequests.set(url, fetchPromise);
  return fetchPromise;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = normalizeApiPath(path);
  const res = await fetch(url, {
    headers: { 'Accept': 'application/json' },
    cache: 'no-store',
    ...init,
  });
  if (!res.ok) throw new Error(`API error: ${res.status} (${url})`);
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const url = normalizeApiPath(path);
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`API error: ${res.status} (${url})`);
  return res.json();
}

// =====================================================
// 1. SWR Polling Hook (0.0ms Instant Render & Global Live Sync)
// =====================================================

export function usePolling<T>(path: string, intervalMs: number = 3000) {
  const [data, setData] = useState<T | null>(() => getInitialCachedData<T>(path));
  const [loading, setLoading] = useState<boolean>(() => !memoryCache.has(path));
  const [isValidating, setIsValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(() => {
    const c = memoryCache.get(path);
    return c ? new Date(c.timestamp) : new Date();
  });
  const [tick, setTick] = useState(0);

  const fetchData = useCallback(async () => {
    setIsValidating(true);
    try {
      const result = await api<T>(path);
      setData(result);
      setError(null);
      setLastUpdated(new Date());
      setTick(t => t + 1);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      setIsValidating(false);
    }
  }, [path]);

  useEffect(() => {
    // 1. Listen for background global telemetry pushes
    const unsubscribe = subscribeToCache(path, (freshData) => {
      setData(freshData);
      setLoading(false);
      setError(null);
      setLastUpdated(new Date());
      setTick(t => t + 1);
    });

    // 2. Fetch immediately and start periodic interval
    fetchData();
    const timer = setInterval(fetchData, intervalMs);

    return () => {
      unsubscribe();
      clearInterval(timer);
    };
  }, [fetchData, intervalMs, path]);

  return { data, loading, isValidating, error, lastUpdated, tick, refetch: fetchData };
}

// =====================================================
// 2. Resilient WebSocket Hook (Heartbeat & Auto-Reconnect)
// =====================================================

export function useWebSocket(channel: string) {
  const [data, setData] = useState<unknown>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    let isSubscribed = true;

    function connectWs() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/${channel}`;
      
      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isSubscribed) return;
          setConnected(true);
        };

        ws.onclose = () => {
          if (!isSubscribed) return;
          setConnected(false);
          // 3 saniye sonra otomatik yeniden bağlan
          reconnectTimeoutRef.current = setTimeout(connectWs, 3000);
        };

        ws.onerror = () => {
          if (!isSubscribed) return;
          setConnected(false);
        };

        ws.onmessage = (event) => {
          if (!isSubscribed) return;
          try {
            const parsed = JSON.parse(event.data);
            setData(parsed);
          } catch {}
        };
      } catch {
        setConnected(false);
      }
    }

    connectWs();

    // 15 saniyede bir Heartbeat Ping göndererek hattı açık tut
    const heartbeatTimer = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send("ping");
        } catch {}
      }
    }, 15000);

    return () => {
      isSubscribed = false;
      clearInterval(heartbeatTimer);
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
    };
  }, [channel]);

  return { data, connected };
}

// =====================================================
// 4. Debounce Utility Hook (Filtreleme & Arama Fırtınasını Önler)
// =====================================================

export function useDebounce<T>(value: T, delay: number = 250): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
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
  dxy?: number;
  dxy_change_pct?: number;
  us10y?: number;
  us10y_change_pct?: number;
  brent_crude?: number;
  brent_change_pct?: number;
  gold?: number;
  gold_change_pct?: number;
  btc?: number;
  btc_change_pct?: number;
}

export interface SystemStatus {
  status: string;
  services: Record<string, string>;
  timestamp: string;
}
