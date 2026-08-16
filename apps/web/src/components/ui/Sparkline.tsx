"use client";

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fillColor?: string;
  lineWidth?: number;
}

export function Sparkline({
  data,
  width = 120,
  height = 32,
  color = "#10b981",
  fillColor,
  lineWidth = 1.5,
}: SparklineProps) {
  if (!data || data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  });

  const path = `M${points.join(" L")}`;
  const fillPath = `${path} L${width},${height} L0,${height} Z`;

  const isPositive = data[data.length - 1] >= data[0];
  const lineColor = color || (isPositive ? "#10b981" : "#ef4444");
  const fill = fillColor || (isPositive ? "rgba(16,185,129,0.08)" : "rgba(239,68,68,0.08)");

  return (
    <svg width={width} height={height} className="overflow-visible">
      <path d={fillPath} fill={fill} />
      <path d={path} fill="none" stroke={lineColor} strokeWidth={lineWidth} strokeLinecap="round" strokeLinejoin="round" />
      {/* End dot */}
      <circle
        cx={(data.length - 1) / (data.length - 1) * width}
        cy={height - ((data[data.length - 1] - min) / range) * (height - 4) - 2}
        r={2}
        fill={lineColor}
      />
    </svg>
  );
}
