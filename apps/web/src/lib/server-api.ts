/**
 * Server-side API client for SSR data fetching.
 * No React hooks — pure async functions for use in Server Components.
 */

const API_BASE = process.env.API_URL || 'http://alpha-api:8000';

interface FetchOptions {
  cache?: RequestCache;
  next?: { revalidate?: number };
  timeout?: number;
}

async function serverFetch<T>(
  path: string,
  options: FetchOptions = {}
): Promise<T | null> {
  const { cache = 'no-store', next, timeout = 10000 } = options;

  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    const response = await fetch(url, {
      cache,
      next,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': process.env.SYSTEM_API_KEY || '',
      },
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      return null;
    }

    return await response.json();
  } catch {
    return null;
  }
}

// =====================================================
// Server-side data fetchers
// =====================================================

export async function fetchMarketState() {
  return serverFetch('/api/v1/market/state');
}

export async function fetchPortfolioState() {
  return serverFetch('/api/v1/portfolio/state');
}

export async function fetchSignals(limit = 50) {
  return serverFetch(`/api/v1/scanner/signals?limit=${limit}`);
}

export async function fetchSystemStatus() {
  return serverFetch('/api/v1/system/status');
}

export async function fetchEvents(ticker?: string) {
  const path = ticker
    ? `/api/v1/event-study/events?ticker=${ticker}`
    : '/api/v1/event-study/events';
  return serverFetch(path);
}

export async function fetchModels() {
  return serverFetch('/api/v1/models/registry');
}

export async function fetchMacroWorld() {
  return serverFetch('/api/v1/macro/world');
}

export async function fetchHeatmap() {
  return serverFetch('/api/v1/market/heatmap');
}

export async function fetchAlerts() {
  return serverFetch('/api/v1/system/alerts');
}

export async function fetchRadar() {
  return serverFetch('/api/v1/scanner/opportunities');
}
