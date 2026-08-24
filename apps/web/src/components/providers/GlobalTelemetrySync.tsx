"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

// All critical endpoints pre-warmed & polled globally from the second the dashboard launches.
// NOT: "offset" degerleri elle atanir (idx*250 yerine) boylece agir/yavas endpoint'ler
// (heatmap ~3s, macro/world ~2.7s) birbirinden ve diger hafif endpoint'lerden uzak tutulur.
// Bu olmadan tum setInterval'lar t=0'da baslatildigindan 10s/15s/30s isaretlerinde
// (ozellikle 30s'de LCM nedeniyle 6 endpoint birden) hepsi es zamanli ates alip
// ana thread'i (fetch sonrasi JSON parse + React state update yagmuru) donduruyordu.
const GLOBAL_TELEMETRY_ENDPOINTS = [
  { path: "/market/state", interval: 10000, offset: 0 },
  { path: "/system/status", interval: 10000, offset: 400 },
  { path: "/portfolio", interval: 10000, offset: 800 },
  // Radar erken oncelikli: /radar sayfasi ziyaret edildiginde cache aninda dolu olsun diye
  { path: "/market/radar?limit=1000", interval: 25000, offset: 1200 },
  { path: "/portfolio/alpha-signals", interval: 15000, offset: 2200 },
  { path: "/scanner/signals?limit=25", interval: 15000, offset: 2900 },
  { path: "/event-study/events", interval: 15000, offset: 3600 },
  { path: "/system/alerts", interval: 15000, offset: 4300 },
  { path: "/models/list", interval: 30000, offset: 5000 },
  { path: "/learning/performance-matrix", interval: 30000, offset: 5700 },
  { path: "/learning/report", interval: 30000, offset: 6400 },
  { path: "/system/databases", interval: 30000, offset: 7200 },
  // En agir/yavas iki endpoint (network-bound, saniyeler surebilir) en sona alindi
  { path: "/macro/world", interval: 30000, offset: 9500 },
  { path: "/market/heatmap", interval: 30000, offset: 12500 },
];

export function GlobalTelemetrySync() {
  const isRunning = useRef(false);

  useEffect(() => {
    if (isRunning.current) return;
    isRunning.current = true;

    const startupTimeouts: ReturnType<typeof setTimeout>[] = [];
    const timers: ReturnType<typeof setInterval>[] = [];

    GLOBAL_TELEMETRY_ENDPOINTS.forEach((ep) => {
      // 1. Staggered startup fetch — her endpoint kendi "offset" degerinde ates alir.
      const t = setTimeout(() => {
        api(ep.path).catch(() => {});

        // 2. Recurring sync — setInterval bu staggered noktada baslatildigi icin
        //    periyodik tekrarlar da faz kaymasini korur, asla hepsi ayni anda
        //    tetiklenmez (onceki hatanin kaynagi buydu).
        const id = setInterval(() => {
          api(ep.path).catch(() => {});
        }, ep.interval);
        timers.push(id);
      }, ep.offset);

      startupTimeouts.push(t);
    });

    return () => {
      startupTimeouts.forEach(clearTimeout);
      timers.forEach(clearInterval);
      isRunning.current = false;
    };
  }, []);

  return null;
}
