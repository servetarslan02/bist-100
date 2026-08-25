"use client";

/**
 * MonteCarloCanvas — TradingView-Standard Canvas 2D Rendering Engine
 * ================================================================
 * Mimarisi: requestAnimationFrame + Dirty Flag + Float32Array
 * Performans: Stabil 60 FPS, idle CPU ≈ 0
 * Referans: TradingView lightweight-charts Canvas motoru
 *
 * Bu bileşen, mevcut useEffect-based rendering'in yerine geçer.
 * TradingView'in kendi Canvas 2D motorunun kullandığı aynı prensipleri uygular:
 * - requestAnimationFrame render loop (state değişince değil, frame zamanında render)
 * - Dirty flag (sadece veri değişirse yeniden çiz)
 * - Float32Array columnar data layout (CPU cache-friendly)
 * - Tek canvas, tek context, tek render loop
 */

import { useEffect, useRef, useCallback, memo } from "react";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface FanCones {
  p05: number[];
  p25: number[];
  p50: number[];
  p75: number[];
  p95: number[];
}

export interface HistogramBin {
  bin_start: number;
  bin_end: number;
  count: number;
  is_loss: boolean;
}

export interface MonteCarloData {
  horizon_days: number;
  paths: number[][];
  fan_cones: FanCones;
  histogram: HistogramBin[];
}

interface RenderState {
  data: MonteCarloData | null;
  mousePos: { x: number; y: number; step: number } | null;
  dirty: boolean;
  dpr: number;
  width: number;
  height: number;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const COLORS = {
  bg: "#07090e",
  gridH: "rgba(255, 255, 255, 0.04)",
  gridV: "rgba(255, 255, 255, 0.03)",
  label: "rgba(255, 255, 255, 0.35)",
  labelTime: "rgba(255, 255, 255, 0.4)",
  baseline: "rgba(0, 200, 255, 0.75)",
  pathUp: "rgba(0, 229, 160, 0.28)",
  pathDown: "rgba(255, 68, 102, 0.28)",
  median: "#00c8ff",
  medianGlow: "#00c8ff",
  fanOuterTop: "rgba(0, 229, 160, 0.12)",
  fanOuterBot: "rgba(255, 68, 102, 0.12)",
  fanInnerTop: "rgba(0, 200, 255, 0.22)",
  fanInnerBot: "rgba(0, 200, 255, 0.08)",
  crosshair: "rgba(255, 255, 255, 0.6)",
  dot: "#00e5a0",
  dotBorder: "#ffffff",
} as const;

const PADDING = { left: 60, right: 25, top: 25, bottom: 30 } as const;
const GRID_LINES = 5;
const INITIAL_VAL = 100000;
const FONT = "10px JetBrains Mono, monospace";

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Convert paths to Float32Array for cache-friendly access */
function pathsToFloat32(paths: number[][]): Float32Array[] {
  return paths.map((p) => Float32Array.from(p));
}

/** Convert fan cones to Float32Array */
function fanConesToFloat32(fc: FanCones): Record<string, Float32Array> {
  return {
    p05: Float32Array.from(fc.p05),
    p25: Float32Array.from(fc.p25),
    p50: Float32Array.from(fc.p50),
    p75: Float32Array.from(fc.p75),
    p95: Float32Array.from(fc.p95),
  };
}

// ─── Render Engine (pure function, no React state) ───────────────────────────

function renderFrame(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  data: MonteCarloData,
  pathsF32: Float32Array[],
  fanF32: Record<string, Float32Array>,
  mousePos: { x: number; y: number; step: number } | null
) {
  const chartW = Math.max(10, w - PADDING.left - PADDING.right);
  const chartH = Math.max(10, h - PADDING.top - PADDING.bottom);
  const steps = Math.max(1, data.horizon_days);

  // Find min/max across all paths
  let minVal = Infinity;
  let maxVal = -Infinity;
  for (const path of pathsF32) {
    for (let i = 0; i < path.length; i++) {
      if (path[i] < minVal) minVal = path[i];
      if (path[i] > maxVal) maxVal = path[i];
    }
  }
  const valRange = Math.max(1, maxVal - minVal);

  const getX = (step: number) => PADDING.left + (step / steps) * chartW;
  const getY = (val: number) =>
    PADDING.top + chartH - ((val - minVal) / valRange) * chartH;

  // ── 1. Clear ──
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, w, h);

  // ── 2. Horizontal Grid + Price Labels ──
  ctx.font = FONT;
  for (let i = 0; i <= GRID_LINES; i++) {
    const gy = PADDING.top + (i / GRID_LINES) * chartH;
    const gVal = maxVal - (i / GRID_LINES) * valRange;

    ctx.beginPath();
    ctx.strokeStyle = COLORS.gridH;
    ctx.lineWidth = 1;
    ctx.moveTo(PADDING.left, gy);
    ctx.lineTo(w - PADDING.right, gy);
    ctx.stroke();

    ctx.fillStyle = COLORS.label;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(
      `₺${Math.round(gVal).toLocaleString("tr-TR")}`,
      PADDING.left - 8,
      gy
    );
  }

  // ── 3. Vertical Grid + Time Labels ──
  const stepInterval = Math.max(5, Math.round(steps / 6));
  for (let s = 0; s <= steps; s += stepInterval) {
    const gx = getX(s);
    ctx.beginPath();
    ctx.strokeStyle = COLORS.gridV;
    ctx.moveTo(gx, PADDING.top);
    ctx.lineTo(gx, h - PADDING.bottom);
    ctx.stroke();

    ctx.fillStyle = COLORS.labelTime;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(`${s}G`, gx, h - PADDING.bottom + 8);
  }

  // ── 4. Fan Cones (Confidence Bands) ──
  const p05 = fanF32.p05;
  const p25 = fanF32.p25;
  const p50 = fanF32.p50;
  const p75 = fanF32.p75;
  const p95 = fanF32.p95;

  if (p95.length > steps && p05.length > steps) {
    // 90% band (p05 - p95)
    const gradOuter = ctx.createLinearGradient(0, PADDING.top, 0, h - PADDING.bottom);
    gradOuter.addColorStop(0, COLORS.fanOuterTop);
    gradOuter.addColorStop(1, COLORS.fanOuterBot);

    ctx.beginPath();
    ctx.moveTo(getX(0), getY(p95[0]));
    for (let i = 1; i <= steps; i++) ctx.lineTo(getX(i), getY(p95[i]));
    for (let i = steps; i >= 0; i--) ctx.lineTo(getX(i), getY(p05[i]));
    ctx.closePath();
    ctx.fillStyle = gradOuter;
    ctx.fill();

    // 50% band (p25 - p75)
    if (p75.length > steps && p25.length > steps) {
      const gradInner = ctx.createLinearGradient(0, PADDING.top, 0, h - PADDING.bottom);
      gradInner.addColorStop(0, COLORS.fanInnerTop);
      gradInner.addColorStop(1, COLORS.fanInnerBot);

      ctx.beginPath();
      ctx.moveTo(getX(0), getY(p75[0]));
      for (let i = 1; i <= steps; i++) ctx.lineTo(getX(i), getY(p75[i]));
      for (let i = steps; i >= 0; i--) ctx.lineTo(getX(i), getY(p25[i]));
      ctx.closePath();
      ctx.fillStyle = gradInner;
      ctx.fill();
    }
  }

  // ── 5. Baseline Reference Line ──
  const baseY = getY(INITIAL_VAL);
  ctx.beginPath();
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = COLORS.baseline;
  ctx.lineWidth = 1.2;
  ctx.moveTo(PADDING.left, baseY);
  ctx.lineTo(w - PADDING.right, baseY);
  ctx.stroke();
  ctx.setLineDash([]);

  // ── 6. Stochastic Paths ──
  for (const path of pathsF32) {
    if (path.length === 0) continue;
    const isPos = path[path.length - 1] >= INITIAL_VAL;
    ctx.beginPath();
    ctx.strokeStyle = isPos ? COLORS.pathUp : COLORS.pathDown;
    ctx.lineWidth = 0.9;
    ctx.moveTo(getX(0), getY(path[0]));
    for (let s = 1; s <= steps && s < path.length; s++) {
      ctx.lineTo(getX(s), getY(path[s]));
    }
    ctx.stroke();
  }

  // ── 7. Median Path (p50 Glowing Line) ──
  if (p50.length > steps) {
    ctx.beginPath();
    ctx.strokeStyle = COLORS.median;
    ctx.lineWidth = 2.2;
    ctx.shadowColor = COLORS.medianGlow;
    ctx.shadowBlur = 8;
    ctx.moveTo(getX(0), getY(p50[0]));
    for (let s = 1; s <= steps; s++) {
      ctx.lineTo(getX(s), getY(p50[s]));
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
  }

  // ── 8. Crosshair Cursor ──
  if (mousePos && mousePos.step >= 0 && mousePos.step <= steps) {
    const hx = getX(mousePos.step);
    const medianVal = p50[mousePos.step] || INITIAL_VAL;
    const hy = getY(medianVal);

    // Vertical dashed guide
    ctx.beginPath();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = COLORS.crosshair;
    ctx.lineWidth = 1;
    ctx.moveTo(hx, PADDING.top);
    ctx.lineTo(hx, h - PADDING.bottom);
    ctx.stroke();
    ctx.setLineDash([]);

    // Highlight dot
    ctx.beginPath();
    ctx.arc(hx, hy, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.dot;
    ctx.shadowColor = COLORS.dot;
    ctx.shadowBlur = 10;
    ctx.fill();
    ctx.strokeStyle = COLORS.dotBorder;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.shadowBlur = 0;
  }
}

// ─── Component ───────────────────────────────────────────────────────────────

interface MonteCarloCanvasProps {
  data: MonteCarloData | null;
  onMouseMove?: (info: { x: number; y: number; step: number } | null) => void;
  className?: string;
}

function MonteCarloCanvasInner({
  data,
  onMouseMove,
  className = "",
}: MonteCarloCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const rafRef = useRef<number>(0);

  // Render state lives in refs (no React re-renders for mouse moves)
  const stateRef = useRef<RenderState>({
    data: null,
    mousePos: null,
    dirty: true,
    dpr: 1,
    width: 0,
    height: 0,
  });

  // Pre-converted Float32 arrays (cached)
  const pathsF32Ref = useRef<Float32Array[]>([]);
  const fanF32Ref = useRef<Record<string, Float32Array>>({
    p05: new Float32Array(),
    p25: new Float32Array(),
    p50: new Float32Array(),
    p75: new Float32Array(),
    p95: new Float32Array(),
  });

  // ── Data update: convert to Float32 and mark dirty ──
  useEffect(() => {
    if (!data) return;
    stateRef.current.data = data;
    stateRef.current.dirty = true;

    // Pre-convert to Float32Array (cache-friendly layout)
    pathsF32Ref.current = pathsToFloat32(data.paths);
    fanF32Ref.current = fanConesToFloat32(data.fan_cones);
  }, [data]);

  // ── RAF render loop (TradingView pattern) ──
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;

    // Size observer (replaces resize event)
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          stateRef.current.width = width;
          stateRef.current.height = height;
          stateRef.current.dirty = true;
        }
      }
    });
    observer.observe(container);

    // Initial size
    const rect = container.getBoundingClientRect();
    stateRef.current.width = rect.width;
    stateRef.current.height = rect.height;
    stateRef.current.dpr = window.devicePixelRatio || 1;
    stateRef.current.dirty = true;

    // ── The Render Loop ──
    const tick = () => {
      const st = stateRef.current;

      // Only render if dirty and we have data
      if (st.dirty && st.data && st.width > 0 && st.height > 0) {
        const dpr = st.dpr;
        const w = st.width;
        const h = st.height;

        // Resize canvas backing store if needed
        const needResize =
          canvas.width !== Math.round(w * dpr) ||
          canvas.height !== Math.round(h * dpr);

        if (needResize) {
          canvas.width = Math.round(w * dpr);
          canvas.height = Math.round(h * dpr);
          canvas.style.width = `${w}px`;
          canvas.style.height = `${h}px`;
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }

        renderFrame(
          ctx,
          w,
          h,
          st.data,
          pathsF32Ref.current,
          fanF32Ref.current,
          st.mousePos
        );

        st.dirty = false;
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      observer.disconnect();
    };
  }, []);

  // ── Mouse handler (updates ref, marks dirty — no setState) ──
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      const data = stateRef.current.data;
      if (!canvas || !data) return;

      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const chartW = Math.max(
        10,
        rect.width - PADDING.left - PADDING.right
      );

      if (mouseX >= PADDING.left && mouseX <= rect.width - PADDING.right) {
        const stepRatio = (mouseX - PADDING.left) / chartW;
        const step = Math.min(
          data.horizon_days,
          Math.max(0, Math.round(stepRatio * data.horizon_days))
        );
        const newPos = { x: mouseX, y: mouseY, step };

        // Only mark dirty if position actually changed
        const prev = stateRef.current.mousePos;
        if (!prev || prev.step !== step || prev.x !== mouseX) {
          stateRef.current.mousePos = newPos;
          stateRef.current.dirty = true;
          onMouseMove?.(newPos);
        }
      } else {
        if (stateRef.current.mousePos !== null) {
          stateRef.current.mousePos = null;
          stateRef.current.dirty = true;
          onMouseMove?.(null);
        }
      }
    },
    [onMouseMove]
  );

  const handleMouseLeave = useCallback(() => {
    if (stateRef.current.mousePos !== null) {
      stateRef.current.mousePos = null;
      stateRef.current.dirty = true;
      onMouseMove?.(null);
    }
  }, [onMouseMove]);

  return (
    <div ref={containerRef} className={`w-full h-full relative ${className}`}>
      <canvas
        ref={canvasRef}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        className="w-full h-full cursor-crosshair block"
      />
    </div>
  );
}

// Memo: sadece data veya onMouseMove değişirse re-render
export const MonteCarloCanvas = memo(MonteCarloCanvasInner);
