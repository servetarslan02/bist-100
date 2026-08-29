"use client";

import { useIstanbulClock, ISTANBUL_TIMEZONE } from "@/lib/time";
import { Clock, Globe, Zap, ShieldCheck } from "lucide-react";
import { useState, useEffect } from "react";

export function Header() {
  const clock = useIstanbulClock();
  const [worldOpen, setWorldOpen] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Dünyanın diğer finans merkezleri için anlık saat hesaplaması
  const now = new Date();
  const nyTime = now.toLocaleTimeString("tr-TR", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
  const londonTime = now.toLocaleTimeString("tr-TR", { timeZone: "Europe/London", hour: "2-digit", minute: "2-digit" });
  const tokyoTime = now.toLocaleTimeString("tr-TR", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit" });

  return (
    <header
      className="h-14 px-6 flex items-center justify-between sticky top-0 z-40 select-none backdrop-blur-md"
      style={{
        background: "rgba(13, 16, 23, 0.85)",
        borderBottom: "1px solid var(--color-border-subtle)",
      }}
    >
      {/* Sol: BIST Piyasa Durumu & Tarih */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full flex-shrink-0 ${
              clock.isMarketOpen
                ? "bg-emerald-400 animate-pulse shadow-[0_0_8px_#00e5a0]"
                : "bg-zinc-500 shadow-[0_0_6px_rgba(255,255,255,0.2)]"
            }`}
          />
          <span
            className="text-[11px] font-bold uppercase tracking-wider"
            style={{
              color: clock.isMarketOpen ? "var(--color-accent-green)" : "var(--color-text-muted)",
            }}
          >
            {clock.marketStatus}
          </span>
        </div>

        <div className="hidden md:flex items-center gap-2 text-[11px] text-zinc-400 border-l border-zinc-800 pl-4">
          <span>{mounted ? `${clock.date}, ${clock.dayName}` : "Yükleniyor..."}</span>
        </div>
      </div>

      {/* Sağ: Eşitlenmiş Türkiye / İstanbul Saati & Dünya Saatleri */}
      <div className="flex items-center gap-3">
        {/* Canlı Eşitlenmiş TR/İstanbul Saati */}
        <div
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg border transition-all"
          style={{
            background: "rgba(0, 229, 160, 0.04)",
            borderColor: "rgba(0, 229, 160, 0.25)",
            boxShadow: "0 0 12px rgba(0, 229, 160, 0.05)",
          }}
          title="Tüm sistem Türkiye / İstanbul (Europe/Istanbul - TSI UTC+3) saatine eşitlenmiştir."
        >
          <Clock size={13} className="text-emerald-400 animate-spin-slow" />
          <div className="flex items-baseline gap-1.5 font-mono">
            <span className="text-[10px] font-semibold text-zinc-400">TSI:</span>
            <span className="text-sm font-bold tracking-wider text-emerald-400">
              {mounted ? clock.time : "--:--:--"}
            </span>
          </div>
          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-500/30">
            TR
          </span>
        </div>

        {/* Dünya Piyasaları Saat Menüsü */}
        <div className="relative">
          <button
            onClick={() => setWorldOpen(!worldOpen)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-zinc-800 hover:border-zinc-700 bg-zinc-900/60 text-zinc-300 hover:text-white transition-all text-xs font-medium"
            title="Küresel Finans Merkezleri Saatleri"
          >
            <Globe size={13} className="text-cyan-400" />
            <span className="hidden sm:inline text-[11px]">Küresel Saatler</span>
          </button>

          {worldOpen && (
            <div
              className="absolute right-0 mt-2 w-56 p-3 rounded-xl border border-zinc-800 shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-150"
              style={{ background: "#11141c" }}
            >
              <p className="text-[10px] uppercase font-bold tracking-wider text-zinc-400 mb-2.5 pb-1.5 border-b border-zinc-800 flex items-center justify-between">
                <span>Borsa Merkezleri</span>
                <span className="text-emerald-400">TSI UTC+3</span>
              </p>
              <div className="flex flex-col gap-2 text-xs font-mono">
                <div className="flex items-center justify-between py-1 px-1.5 rounded bg-emerald-950/20 border border-emerald-500/20">
                  <span className="text-zinc-200 flex items-center gap-1.5">
                    <span>🇹🇷</span> İstanbul (BIST)
                  </span>
                  <span className="font-bold text-emerald-400">{mounted ? clock.time : "--:--:--"}</span>
                </div>
                <div className="flex items-center justify-between py-1 px-1.5 text-zinc-400">
                  <span className="flex items-center gap-1.5">
                    <span>🇬🇧</span> Londra (LSE)
                  </span>
                  <span>{londonTime}</span>
                </div>
                <div className="flex items-center justify-between py-1 px-1.5 text-zinc-400">
                  <span className="flex items-center gap-1.5">
                    <span>🇺🇸</span> New York (NYSE)
                  </span>
                  <span>{nyTime}</span>
                </div>
                <div className="flex items-center justify-between py-1 px-1.5 text-zinc-400">
                  <span className="flex items-center gap-1.5">
                    <span>🇯🇵</span> Tokyo (TSE)
                  </span>
                  <span>{tokyoTime}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
