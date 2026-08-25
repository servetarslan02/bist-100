"use client";

/**
 * TradingViewChart — Canvas 2D + requestAnimationFrame Engine
 * ===========================================================
 * Önceki: useEffect + createChart (her data değişiminde chart yeniden oluşuyor)
 * Şimdi: RAF loop + dirty flag + chart reuse (data değişirse sadece series update)
 *
 * Görsel: Aynı. Teknoloji: Canvas 2D + RAF.
 * Referans: TradingView lightweight-charts + requestAnimationFrame pattern.
 */

import { useEffect, useRef, memo, useCallback } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type Time,
} from "lightweight-charts";

interface TradingViewChartProps {
  data: Array<{ time: string; open: number; high: number; low: number; close: number }>;
  height?: number;
  width?: number;
}

function TradingViewChartInner({ data, height = 300, width }: TradingViewChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const rafRef = useRef<number>(0);
  const dirtyRef = useRef(false);
  const dataRef = useRef(data);
  const sizeRef = useRef({ width: 0, height });

  // Mark dirty when data changes
  useEffect(() => {
    dataRef.current = data;
    dirtyRef.current = true;
  }, [data]);

  // Chart init + RAF loop
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Create chart once
    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
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
      width: width || container.clientWidth,
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

    chartRef.current = chart;
    seriesRef.current = series;
    sizeRef.current = { width: width || container.clientWidth, height };

    // Initial data load
    if (data && data.length > 0) {
      try {
        series.setData(data as CandlestickData<Time>[]);
        chart.timeScale().fitContent();
      } catch (e) {
        console.warn("TradingView chart initial data warning:", e);
      }
    }

    // ResizeObserver (replaces window.resize)
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width: newWidth } = entry.contentRect;
        if (newWidth > 0 && newWidth !== sizeRef.current.width) {
          sizeRef.current.width = newWidth;
          chart.applyOptions({ width: newWidth });
        }
      }
    });
    observer.observe(container);

    // RAF loop for data updates (lightweight-charts handles its own rendering,
    // we just need to feed data efficiently)
    const tick = () => {
      if (dirtyRef.current && seriesRef.current) {
        const d = dataRef.current;
        if (d && d.length > 0) {
          try {
            seriesRef.current.setData(d as CandlestickData<Time>[]);
            chartRef.current?.timeScale().fitContent();
          } catch (e) {
            // Silently handle
          }
        }
        dirtyRef.current = false;
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []); // Mount only — no deps

  return <div ref={containerRef} className="w-full min-h-[300px]" />;
}

export const TradingViewChart = memo(TradingViewChartInner);
