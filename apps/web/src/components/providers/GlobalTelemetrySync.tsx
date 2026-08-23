"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

// All critical endpoints pre-warmed & polled globally from the second the dashboard launches
const GLOBAL_TELEMETRY_ENDPOINTS = [
  { path: "/portfolio", interval: 3000 },
  { path: "/signals", interval: 5000 },
  { path: "/opportunities", interval: 5000 },
  { path: "/radar", interval: 5000 },
  { path: "/map", interval: 8000 },
  { path: "/world", interval: 8000 },
  { path: "/events", interval: 8000 },
  { path: "/alerts", interval: 5000 },
  { path: "/research", interval: 12000 },
  { path: "/models", interval: 12000 },
  { path: "/learning", interval: 12000 },
  { path: "/system", interval: 5000 },
  { path: "/data", interval: 12000 },
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
