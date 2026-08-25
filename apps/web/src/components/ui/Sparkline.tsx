"use client";

/**
 * Sparkline — Canvas 2D + requestAnimationFrame Engine
 * ====================================================
 * Önceki: SVG (DOM-based, her data değişiminde DOM manipülasyonu)
 * Şimdi: Canvas 2D + RAF (GPU-accelerated, dirty flag, zero idle CPU)
 *
 * Görsel: Aynı. Teknoloji: Canvas 2D.
 */

import { useRef, useEffect, memo, useCallback } from "react";

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fillColor?: string;
  lineWidth?: number;
}

function SparklineInner({
  data,
  width = 120,
  height = 32,
  color = "#10b981",
  fillColor,
  lineWidth = 1.5,
}: SparklineProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number>(0);
  const dirtyRef = useRef(true);
  const dataRef = useRef<number[]>(data);

  // Mark dirty when data changes
  useEffect(() => {
    dataRef.current = data;
    dirtyRef.current = true;
  }, [data]);

  // RAF render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;

    // Set canvas size once
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const tick = () => {
      if (dirtyRef.current) {
        const d = dataRef.current;
        if (d && d.length >= 2) {
          const min = Math.min(...d);
          const max = Math.max(...d);
          const range = max - min || 1;

          const isPositive = d[d.length - 1] >= d[0];
          const lineColor = color || (isPositive ? "#10b981" : "#ef4444");
          const fill = fillColor || (isPositive ? "rgba(16,185,129,0.08)" : "rgba(239,68,68,0.08)");

          ctx.clearRect(0, 0, width, height);

          // Build path points
          const getX = (i: number) => (i / (d.length - 1)) * width;
          const getY = (v: number) => height - ((v - min) / range) * (height - 4) - 2;

          // Fill area
          ctx.beginPath();
          ctx.moveTo(getX(0), getY(d[0]));
          for (let i = 1; i < d.length; i++) {
            ctx.lineTo(getX(i), getY(d[i]));
          }
          ctx.lineTo(width, height);
          ctx.lineTo(0, height);
          ctx.closePath();
          ctx.fillStyle = fill;
          ctx.fill();

          // Line
          ctx.beginPath();
          ctx.moveTo(getX(0), getY(d[0]));
          for (let i = 1; i < d.length; i++) {
            ctx.lineTo(getX(i), getY(d[i]));
          }
          ctx.strokeStyle = lineColor;
          ctx.lineWidth = lineWidth;
          ctx.lineCap = "round";
          ctx.lineJoin = "round";
          ctx.stroke();

          // End dot
          const lastX = getX(d.length - 1);
          const lastY = getY(d[d.length - 1]);
          ctx.beginPath();
          ctx.arc(lastX, lastY, 2, 0, Math.PI * 2);
          ctx.fillStyle = lineColor;
          ctx.fill();
        }

        dirtyRef.current = false;
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    dirtyRef.current = true;
    rafRef.current = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(rafRef.current);
  }, [width, height, color, fillColor, lineWidth]);

  if (!data || data.length < 2) return null;

  return (
    <canvas
      ref={canvasRef}
      className="overflow-visible"
      style={{ width, height }}
    />
  );
}

export const Sparkline = memo(SparklineInner);
