"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

// All critical endpoints pre-warmed & polled globally across the whole dashboard
const GLOBAL_TELEMETRY_ENDPOINTS = [
  { path: "/market/state", interval: 8000 },
  { path: "/portfolio", interval: 8000 },
  { path: "/portfolio/alpha-signals", interval: 10000 },
  { path: "/scanner/signals?limit=25", interval: 10000 },
  { path: "/market/radar", interval: 15000 },
  { path: "/market/heatmap", interval: 20000 },
  { path: "/macro/world", interval: 20000 },
  { path: "/event-study/events", interval: 10000 },
  { path: "/system/alerts", interval: 10000 },
  { path: "/system/status", interval: 8000 },
  { path: "/system/databases", interval: 20000 },
  { path: "/models/list", interval: 25000 },
  { path: "/learning/performance-matrix", interval: 25000 },
  { path: "/learning/report", interval: 25000 },
  { path: "/risk/stress-test?horizon_days=30&vol_multiplier=1.0&scenario=gfc_2008", interval: 30000 },
];

export function GlobalTelemetrySync() {
  const isRunning = useRef(false);

  useEffect(() => {
    if (isRunning.current) return;
    isRunning.current = true;

    // Staggered startup to prevent UI thread locking
    const startupTimeouts = GLOBAL_TELEMETRY_ENDPOINTS.map((ep, idx) => {
      return setTimeout(() => {
        api(ep.path).catch(() => {});
      }, idx * 250);
    });

    // Continuous background sync timers
    const timers = GLOBAL_TELEMETRY_ENDPOINTS.map((ep) => {
      return setInterval(() => {
        api(ep.path).catch(() => {});
      }, ep.interval);
    });

    return () => {
      startupTimeouts.forEach(clearTimeout);
      timers.forEach(clearInterval);
      isRunning.current = false;
    };
  }, []);

  return null;
}
