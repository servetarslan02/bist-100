"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

// All critical endpoints pre-warmed & polled globally from the second the dashboard launches
const GLOBAL_TELEMETRY_ENDPOINTS = [
  { path: "/market/state", interval: 3000 },
  { path: "/portfolio", interval: 4000 },
  { path: "/portfolio/alpha-signals", interval: 5000 },
  { path: "/scanner/signals?limit=25", interval: 5000 },
  { path: "/scanner/radar", interval: 5000 },
  { path: "/market/heatmap", interval: 8000 },
  { path: "/macro/world", interval: 8000 },
  { path: "/event-study/events", interval: 5000 },
  { path: "/system/alerts", interval: 5000 },
  { path: "/system/status", interval: 3000 },
  { path: "/system/databases", interval: 8000 },
  { path: "/scanner/signals", interval: 10000 },
  { path: "/models/list", interval: 12000 },
  { path: "/learning/performance-matrix", interval: 12000 },
  { path: "/learning/report", interval: 12000 },
  { path: "/risk/stress-test?horizon_days=30&vol_multiplier=1.0&scenario=gfc_2008", interval: 15000 },
];

export function GlobalTelemetrySync() {
  const isRunning = useRef(false);

  useEffect(() => {
    if (isRunning.current) return;
    isRunning.current = true;

    // 1. Immediate bootstrap fetch for all endpoints at startup (0ms)
    GLOBAL_TELEMETRY_ENDPOINTS.forEach((ep) => {
      api(ep.path).catch(() => {});
    });

    // 2. Continuous background sync timers
    const timers = GLOBAL_TELEMETRY_ENDPOINTS.map((ep) => {
      return setInterval(() => {
        api(ep.path).catch(() => {});
      }, ep.interval);
    });

    return () => {
      timers.forEach(clearInterval);
      isRunning.current = false;
    };
  }, []);

  return null;
}
