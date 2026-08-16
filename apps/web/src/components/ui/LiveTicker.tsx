"use client";

import { useEffect, useState, useRef } from "react";

interface TickerItem {
  symbol: string;
  price: number;
  change: number;
  volume: number;
}

export function LiveTicker() {
  const [tickers, setTickers] = useState<TickerItem[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(`ws://${window.location.host}/ws/market.tick`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "tick") {
          setTickers(prev => {
            const existing = prev.findIndex(t => t.symbol === data.ticker);
            if (existing >= 0) {
              const updated = [...prev];
              updated[existing] = {
                symbol: data.ticker,
                price: data.price,
                change: data.change_pct || 0,
                volume: data.volume || 0,
              };
              return updated;
            }
            return [...prev.slice(-19), {
              symbol: data.ticker,
              price: data.price,
              change: data.change_pct || 0,
              volume: data.volume || 0,
            }];
          });
        }
      } catch {}
    };

    return () => ws.close();
  }, []);

  if (tickers.length === 0) return null;

  return (
    <div className="bg-zinc-900/80 border-b border-zinc-800/60 px-4 py-1 flex items-center gap-4 overflow-x-auto">
      {tickers.map(t => (
        <div key={t.symbol} className="flex items-center gap-2 shrink-0">
          <span className="text-[10px] font-semibold text-zinc-400">{t.symbol}</span>
          <span className="text-[10px] font-mono text-zinc-300">₺{t.price.toFixed(2)}</span>
          <span className={`text-[9px] font-mono ${t.change >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {t.change >= 0 ? "+" : ""}{t.change.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
}
