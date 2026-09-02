/**
 * Dashboard — Hybrid SSR + Client Rendering
 *
 * Server-side: Fetches initial data for instant first paint + SEO
 * Client-side: Takes over with real-time polling after hydration
 */

import { Suspense } from 'react';
import DashboardClient from './DashboardClient';

const API_BASE = process.env.API_URL || 'http://alpha-api:8000';

async function fetchInitialData() {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  if (process.env.SYSTEM_API_KEY) {
    headers['X-API-Key'] = process.env.SYSTEM_API_KEY;
  }

  const fetchOpts: RequestInit = {
    cache: 'no-store',
    headers,
    signal: AbortSignal.timeout(8000),
  };

  const [market, signals, status] = await Promise.allSettled([
    fetch(`${API_BASE}/api/v1/market/state`, fetchOpts).then(r => r.ok ? r.json() : null),
    fetch(`${API_BASE}/api/v1/scanner/signals?limit=10`, fetchOpts).then(r => r.ok ? r.json() : null),
    fetch(`${API_BASE}/api/v1/system/status`, fetchOpts).then(r => r.ok ? r.json() : null),
  ]);

  return {
    market: market.status === 'fulfilled' ? market.value : null,
    signals: signals.status === 'fulfilled' ? signals.value : null,
    status: status.status === 'fulfilled' ? status.value : null,
  };
}

export default async function DashboardPage() {
  const initialData = await fetchInitialData();

  return (
    <Suspense fallback={<DashboardLoading />}>
      <DashboardClient initialData={initialData} />
    </Suspense>
  );
}

function DashboardLoading() {
  return (
    <div className="p-6 max-w-[1400px] mx-auto flex flex-col gap-6 animate-pulse">
      <div className="h-8 w-64 rounded bg-gray-800/50" />
      <div className="grid grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-24 rounded-xl bg-gray-800/30" />
        ))}
      </div>
      <div className="h-64 rounded-xl bg-gray-800/30" />
    </div>
  );
}
