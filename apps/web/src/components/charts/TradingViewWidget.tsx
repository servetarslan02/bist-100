"use client";

import { useEffect, useRef, memo } from "react";
import { ExternalLink } from "lucide-react";

interface TradingViewWidgetProps {
  symbol: string;
  height?: number | string;
  theme?: "dark" | "light";
  onFallbackToLocal?: () => void;
}

function TradingViewWidgetInner({
  symbol,
  height = 500,
  theme = "dark",
  onFallbackToLocal,
}: TradingViewWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Sembol biçimlendirmesi: BIST:THYAO formatı
  const cleanSym = symbol.toUpperCase().replace(".IS", "").replace("BIST:", "").trim();
  const tvSymbol = `BIST:${cleanSym}`;
  const tvDirectUrl = `https://tr.tradingview.com/chart/?symbol=BIST:${cleanSym}`;

  useEffect(() => {
    const currentContainer = containerRef.current;
    if (!currentContainer) return;

    currentContainer.innerHTML = "";

    // TradingView Advanced Chart Widget Container
    const widgetContainer = document.createElement("div");
    widgetContainer.className = "tradingview-widget-container";
    widgetContainer.style.height = "100%";
    widgetContainer.style.width = "100%";

    const widgetDiv = document.createElement("div");
    widgetDiv.className = "tradingview-widget-container__widget";
    widgetDiv.style.height = "calc(100% - 32px)";
    widgetDiv.style.width = "100%";
    widgetContainer.appendChild(widgetDiv);

    // Modern TradingView Advanced Chart Embed Script
    const script = document.createElement("script");
    script.type = "text/javascript";
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval: "D",
      timezone: "Europe/Istanbul",
      theme: theme,
      style: "1",
      locale: "tr",
      enable_publishing: false,
      allow_symbol_change: true,
      calendar: false,
      hide_volume: false,
      support_host: "https://www.tradingview.com",
    });

    widgetContainer.appendChild(script);
    currentContainer.appendChild(widgetContainer);

    return () => {
      currentContainer.innerHTML = "";
    };
  }, [symbol, theme, tvSymbol]);

  return (
    <div className="relative w-full rounded-xl overflow-hidden border border-zinc-800/80 bg-zinc-950 flex flex-col"
         style={{ height: typeof height === "number" ? `${height}px` : height }}>
      
      {/* Üst Bilgi & Hızlı Geçiş Barı */}
      <div className="flex items-center justify-between px-4 py-2 bg-zinc-900/90 border-b border-zinc-800/60 text-xs">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="font-bold text-zinc-200">TradingView Gömülü Grafik: {tvSymbol}</span>
        </div>

        <div className="flex items-center gap-3">
          {onFallbackToLocal && (
            <button
              onClick={onFallbackToLocal}
              className="text-[11px] text-amber-400 hover:text-amber-300 font-medium underline underline-offset-2 cursor-pointer"
            >
              Grafik Açılmıyorsa Yerel BIST Motoruna Geç
            </button>
          )}
          <a
            href={tvDirectUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white text-[11px] font-semibold transition-colors"
          >
            <span>TradingView'da Aç</span>
            <ExternalLink size={12} />
          </a>
        </div>
      </div>

      {/* Widget Konteyneri */}
      <div ref={containerRef} className="w-full flex-1 min-h-0" />
    </div>
  );
}

export const TradingViewWidget = memo(TradingViewWidgetInner);

