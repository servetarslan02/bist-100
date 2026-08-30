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
  // SSD write reduction: interval'lar 2-3x artırıldı
  { path: "/market/state", interval: 20000, offset: 0 },
  { path: "/system/status", interval: 20000, offset: 800 },
  { path: "/portfolio", interval: 20000, offset: 1600 },
  // Radar erken oncelikli: /radar sayfasi ziyaret edildiginde cache aninda dolu olsun diye
  { path: "/market/radar?limit=1000", interval: 60000, offset: 2400 },
  { path: "/portfolio/alpha-signals", interval: 30000, offset: 4400 },
  { path: "/scanner/signals?limit=25", interval: 30000, offset: 5800 },
  { path: "/event-study/events", interval: 30000, offset: 7200 },
  { path: "/system/alerts", interval: 30000, offset: 8600 },
  { path: "/models/list", interval: 60000, offset: 10000 },
  { path: "/learning/performance-matrix", interval: 60000, offset: 11400 },
  { path: "/learning/report", interval: 60000, offset: 12800 },
  { path: "/system/databases", interval: 60000, offset: 14400 },
  // En agir/yavas iki endpoint (network-bound, saniyeler surebilir) en sona alindi
  { path: "/macro/world", interval: 60000, offset: 19000 },
  { path: "/market/heatmap", interval: 60000, offset: 25000 },
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
