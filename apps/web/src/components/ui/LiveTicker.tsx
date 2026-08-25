"use client";

/**
 * LiveTicker — WebSocket + requestAnimationFrame + Ref State Engine
 * ================================================================
 * Önceki: setState per tick (her WebSocket mesajında re-render)
 * Şimdi: Ref state + RAF batch update (idle CPU ≈ 0)
 *
 * Görsel: Aynı. Teknoloji: RAF + Ref batching.
 */

import { useEffect, useState, useRef, memo } from "react";

interface TickerItem {
  symbol: string;
  price: number;
  change: number;
  volume: number;
}

function LiveTickerInner() {
  const [tickers, setTickers] = useState<TickerItem[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const rafRef = useRef<number>(0);
  const dirtyRef = useRef(false);

  // Ref-based ticker map (no re-render per tick)
  const tickerMapRef = useRef<Map<string, TickerItem>>(new Map());

  useEffect(() => {
    const ws = new WebSocket(`ws://${window.location.host}/ws/market.tick`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "tick") {
          // Update ref map (no re-render)
          tickerMapRef.current.set(data.ticker, {
            symbol: data.ticker,
            price: data.price,
            change: data.change_pct || 0,
            volume: data.volume || 0,
          });
          dirtyRef.current = true;
        }
      } catch {}
    };

    // RAF loop for batching ticker updates
    const tick = () => {
      if (dirtyRef.current) {
        const items = Array.from(tickerMapRef.current.values()).slice(-20);
        setTickers(items);
        dirtyRef.current = false;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ws.close();
    };
  }, []);

  if (tickers.length === 0) return null;

  return (
    <div className="bg-zinc-900/80 border-b border-zinc-800/60 px-4 py-1 flex items-center gap-4 overflow-x-auto">
      {tickers.map((t) => (
        <div key={t.symbol} className="flex items-center gap-2 shrink-0">
          <span className="text-[10px] font-semibold text-zinc-400">
            {t.symbol}
          </span>
          <span className="text-[10px] font-mono text-zinc-300">
            ₺{t.price.toFixed(2)}
          </span>
          <span
            className={`text-[9px] font-mono ${
              t.change >= 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {t.change >= 0 ? "+" : ""}
            {t.change.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
}

export const LiveTicker = memo(LiveTickerInner);
