"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

// All critical endpoints with optimized non-blocking polling intervals
const GLOBAL_TELEMETRY_ENDPOINTS = [
  { path: "/market/state", interval: 10000 },
  { path: "/portfolio", interval: 10000 },
  { path: "/portfolio/alpha-signals", interval: 15000 },
  { path: "/scanner/signals?limit=25", interval: 15000 },
  { path: "/market/radar", interval: 20000 },
  { path: "/market/heatmap", interval: 30000 },
  { path: "/macro/world", interval: 30000 },
  { path: "/event-study/events", interval: 20000 },
  { path: "/system/status", interval: 15000 },
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
