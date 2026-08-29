"use client";

import { useState, useEffect } from "react";

export const ISTANBUL_TIMEZONE = "Europe/Istanbul";

/**
 * Verilen tarihi Türkiye / İstanbul saat dilimine göre Date nesnesi olarak döner.
 */
export function getIstanbulDate(input?: Date | string | number): Date {
  const d = input ? new Date(input) : new Date();
  if (isNaN(d.getTime())) return new Date();
  return d;
}

/**
 * Türkiye / İstanbul (TSI / UTC+3) saat formatı: "HH:mm:ss" veya "HH:mm"
 */
export function formatIstanbulTime(
  input?: Date | string | number | null,
  includeSeconds: boolean = true
): string {
  if (!input) return "—";
  const d = typeof input === "object" ? input : new Date(input);
  if (isNaN(d.getTime())) return "—";

  return d.toLocaleTimeString("tr-TR", {
    timeZone: ISTANBUL_TIMEZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: includeSeconds ? "2-digit" : undefined,
    hour12: false,
  });
}

/**
 * Türkiye / İstanbul tam tarih ve saat formatı: "DD MMM YYYY HH:mm:ss"
 */
export function formatIstanbulDateTime(
  input?: Date | string | number | null,
  includeSeconds: boolean = true
): string {
  if (!input) return "—";
  const d = typeof input === "object" ? input : new Date(input);
  if (isNaN(d.getTime())) return "—";

  return d.toLocaleString("tr-TR", {
    timeZone: ISTANBUL_TIMEZONE,
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: includeSeconds ? "2-digit" : undefined,
    hour12: false,
  });
}

/**
 * Türkiye / İstanbul tarih formatı: "DD MMMM YYYY"
 */
export function formatIstanbulDate(
  input?: Date | string | number | null
): string {
  if (!input) return "—";
  const d = typeof input === "object" ? input : new Date(input);
  if (isNaN(d.getTime())) return "—";

  return d.toLocaleDateString("tr-TR", {
    timeZone: ISTANBUL_TIMEZONE,
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export interface ClockState {
  time: string;           // "18:55:42"
  date: string;           // "29 Ağustos 2026"
  dayName: string;        // "Cumartesi"
  isMarketOpen: boolean;  // Hafta içi 10:00 - 18:00
  marketStatus: string;   // "SEANS AÇIK" / "SEANS KAPALI"
  synced: boolean;        // İnternet / Server senkronizasyonu
}

let serverTimeOffsetMs = 0;
let hasSyncedWithServer = false;

// Sunucu saati ile client saat farkını (clock drift) hesaplar
async function syncServerTimeOffset() {
  try {
    const t0 = Date.now();
    const res = await fetch("/api/v1/system/time");
    if (!res.ok) return;
    const data = await res.json();
    const t1 = Date.now();
    const networkLatency = (t1 - t0) / 2;
    if (data.timestamp_ms) {
      serverTimeOffsetMs = data.timestamp_ms + networkLatency - t1;
      hasSyncedWithServer = true;
    }
  } catch {
    // Çevrimdışıysa yerel Intl Europe/Istanbul fallback kullanır
  }
}

/**
 * Tüm sitede saati saniyesi saniyesine internet ve TR/İstanbul eşit senkronize eden React Hook.
 */
export function useIstanbulClock(): ClockState {
  const [clock, setClock] = useState<ClockState>(() => {
    const now = new Date(Date.now() + serverTimeOffsetMs);
    return calculateClock(now);
  });

  function calculateClock(now: Date): ClockState {
    const time = formatIstanbulTime(now, true);
    const date = formatIstanbulDate(now);

    const dayName = now.toLocaleDateString("tr-TR", {
      timeZone: ISTANBUL_TIMEZONE,
      weekday: "long",
    });

    // İstanbul saat ve gün kontrolü
    const hourStr = now.toLocaleTimeString("en-US", { timeZone: ISTANBUL_TIMEZONE, hour: "numeric", hour12: false });
    const minuteStr = now.toLocaleTimeString("en-US", { timeZone: ISTANBUL_TIMEZONE, minute: "numeric" });
    const weekdayStr = now.toLocaleDateString("en-US", { timeZone: ISTANBUL_TIMEZONE, weekday: "short" });

    const hour = parseInt(hourStr, 10);
    const minute = parseInt(minuteStr, 10);
    const isWeekend = weekdayStr === "Sat" || weekdayStr === "Sun";
    const totalMinutes = hour * 60 + minute;

    // BIST Hisse Senedi Seansı: Hafta içi 10:00 - 18:00
    const isMarketOpen = !isWeekend && totalMinutes >= 600 && totalMinutes < 1080;
    const marketStatus = isMarketOpen ? "BİST SEANS AÇIK" : "SEANS KAPALI";

    return {
      time,
      date,
      dayName,
      isMarketOpen,
      marketStatus,
      synced: hasSyncedWithServer,
    };
  }

  useEffect(() => {
    // İlk yüklemede ve her 1 dakikada sunucu ile zaman farkını kalibre et
    syncServerTimeOffset();
    const syncInterval = setInterval(syncServerTimeOffset, 60000);

    // Her saniye saati tıkla
    const tickInterval = setInterval(() => {
      const now = new Date(Date.now() + serverTimeOffsetMs);
      setClock(calculateClock(now));
    }, 1000);

    return () => {
      clearInterval(syncInterval);
      clearInterval(tickInterval);
    };
  }, []);

  return clock;
}
