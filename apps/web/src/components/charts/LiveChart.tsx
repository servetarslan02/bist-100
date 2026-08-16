"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { createChart, ColorType, CrosshairMode, type IChartApi, type ISeriesApi, type CandlestickData, type Time } from "lightweight-charts";

interface LiveChartProps {
  ticker: string;
  height?: number;
}

interface TickData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function LiveChart({ ticker, height = 300 }: LiveChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastPrice, setLastPrice] = useState<number | null>(null);
  const [priceChange, setPriceChange] = useState<number>(0);

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#09090b" },
        textColor: "#71717a",
        fontSize: 10,
        fontFamily: "JetBrains Mono, monospace",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.03)" },
        horzLines: { color: "rgba(255,255,255,0.03)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(16,185,129,0.3)", width: 1, style: 2 },
        horzLine: { color: "rgba(16,185,129,0.3)", width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.05)",
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.05)",
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height,
    });

    const series = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#ef4444",
      borderUpColor: "#10b981",
      borderDownColor: "#ef4444",
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
    });

    // Volume series
    const volumeSeries = chart.addHistogramSeries({
      color: "rgba(16,185,129,0.15)",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });

    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    seriesRef.current = series;

    // Load historical data
    loadHistoricalData(ticker, series, volumeSeries);

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [ticker, height]);

  // WebSocket connection
  useEffect(() => {
    const connectWS = () => {
      const wsUrl = `ws://${window.location.host}/ws/market.tick`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        // Subscribe to ticker
        ws.send(JSON.stringify({ action: "subscribe", ticker }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "tick" && data.ticker === ticker) {
            handleTick(data);
          }
        } catch {}
      };

      ws.onclose = () => {
        setConnected(false);
        // Reconnect after 3 seconds
        setTimeout(connectWS, 3000);
      };

      ws.onerror = () => setConnected(false);
    };

    connectWS();
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [ticker]);

  const handleTick = useCallback((data: any) => {
    if (!seriesRef.current) return;

    const price = data.price;
    const time = Math.floor(data.timestamp / 1000) as Time;

    setLastPrice(price);
    setPriceChange(data.change_pct || 0);

    // Update candlestick
    seriesRef.current.update({
      time,
      open: data.open || price,
      high: data.high || price,
      low: data.low || price,
      close: price,
    });
  }, []);

  const loadHistoricalData = async (ticker: string, series: any, volumeSeries: any) => {
    try {
      const res = await fetch(`/api/market/instrument/${ticker}/ohlcv?period=60d`);
      if (!res.ok) return;
      const data = await res.json();

      if (data.candles) {
        series.setData(data.candles.map((c: any) => ({
          time: c.time as Time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        })));

        if (data.volumes) {
          volumeSeries.setData(data.volumes.map((v: any) => ({
            time: v.time as Time,
            value: v.volume,
            color: v.close >= v.open ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)",
          })));
        }

        // Set initial price
        if (data.candles.length > 0) {
          const last = data.candles[data.candles.length - 1];
          setLastPrice(last.close);
          if (data.candles.length > 1) {
            const prev = data.candles[data.candles.length - 2];
            setPriceChange((last.close / prev.close - 1) * 100);
          }
        }
      }
    } catch {}
  };

  return (
    <div className="relative">
      {/* Price Header */}
      <div className="absolute top-2 left-3 z-10 flex items-center gap-3">
        <span className="text-xs font-semibold text-zinc-300">{ticker}</span>
        {lastPrice !== null && (
          <>
            <span className="text-sm font-mono font-semibold text-zinc-100">
              ₺{lastPrice.toFixed(2)}
            </span>
            <span className={`text-[10px] font-mono ${priceChange >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {priceChange >= 0 ? "+" : ""}{priceChange.toFixed(2)}%
            </span>
          </>
        )}
      </div>

      {/* Connection Status */}
      <div className="absolute top-2 right-3 z-10 flex items-center gap-1.5">
        <div className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-emerald-500 pulse-dot" : "bg-red-500"}`} />
        <span className="text-[9px] text-zinc-600">{connected ? "LIVE" : "OFFLINE"}</span>
      </div>

      {/* Chart */}
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
