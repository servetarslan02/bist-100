"use client";

import { useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useIstanbulClock } from "@/lib/time";
import { useGlobalSyncStatus } from "@/lib/api";
import { 
  Clock, Wifi, WifiOff, Globe, Sparkles, ShieldCheck, 
  Activity, RefreshCw, Layers, ChevronRight, Bell
} from "lucide-react";

const ROUTE_NAMES: Record<string, { title: string; category: string }> = {
  "/": { title: "Genel Bakış & Piyasa Radarı", category: "ÇEKİRDEK" },
  "/radar": { title: "BIST Tüm Hisseler Canlı Radar", category: "PİYASA" },
  "/map": { title: "Sektörel Isı Haritası", category: "PİYASA" },
  "/portfolio": { title: "Canlı Portföy & T+2 Takas Defteri", category: "PORTFÖY" },
  "/strategy": { title: "Strateji & Backtest Analizi", category: "PORTFÖY" },
  "/opportunities": { title: "Otonom Fırsatlar & Sinyaller", category: "İSTİHBARAT" },
  "/events": { title: "KAP Bildirimleri & Haber Akışı", category: "İSTİHBARAT" },
  "/research": { title: "AI Piyasa Araştırma Raporları", category: "İSTİHBARAT" },
  "/world": { title: "Küresel Makro & Dünya Piyasaları", category: "İSTİHBARAT" },
  "/alerts": { title: "Canlı Sistem & Risk Alarmları", category: "İSTİHBARAT" },
  "/asset": { title: "Detaylı Varlık & Hisse Analizi", category: "İSTİHBARAT" },
  "/models": { title: "Model Merkezi & Tahminleme", category: "MODELLER" },
  "/learning": { title: "Sürekli Öğrenme Laboratuvarı", category: "MODELLER" },
  "/data": { title: "Veri Kaynakları & Akış Hattı", category: "SİSTEM" },
  "/scenario": { title: "Senaryo & Stres Simülasyonu", category: "SİSTEM" },
  "/system": { title: "Sistem Sağlığı & Telemetri", category: "SİSTEM" },
};

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const clock = useIstanbulClock();
  const { secondsAgo } = useGlobalSyncStatus();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const routeInfo = ROUTE_NAMES[pathname] || { 
    title: pathname.replace("/", "").toUpperCase() || "ALPHA BIST", 
    category: "SİSTEM" 
  };

  const isLive = secondsAgo < 15;

  return (
    <header 
      className="h-14 border-b border-zinc-800/80 bg-zinc-950/60 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-40 select-none flex-shrink-0"
      style={{ borderBottomColor: "var(--color-border-subtle)" }}
    >
      {/* Sol: Aktif Sayfa Breadcrumb & Kategori */}
      <div className="flex items-center gap-2.5">
        <span className="text-[10px] font-bold uppercase tracking-widest text-emerald-400/90 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
          {routeInfo.category}
        </span>
        <ChevronRight size={12} className="text-zinc-600" />
        <h2 className="text-xs font-semibold text-zinc-200 tracking-tight">
          {routeInfo.title}
        </h2>
      </div>

      {/* Sağ: Eşitlenmiş İstanbul Saati, BİST Seans Durumu ve Canlılık Bildirimi */}
      <div className="flex items-center gap-3">
        {/* İnternet Eşitlenmiş İstanbul Saati */}
        {mounted ? (
          <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-zinc-900/90 border border-zinc-800 shadow-sm text-[11px] font-mono">
            <Clock size={12} className="text-emerald-400 animate-pulse" />
            <span className="font-bold text-emerald-400 tracking-wider">
              {clock.time}
            </span>
            <span className="text-[9px] font-sans font-bold text-zinc-400">TSİ (İSTANBUL)</span>
            <span className="text-zinc-700">·</span>
            <span className="text-[10px] font-sans text-zinc-300">
              {clock.date}
            </span>
            <span className="text-zinc-700">|</span>
            <span className={`text-[10px] font-sans font-bold px-1.5 py-0.2 rounded ${
              clock.isMarketOpen 
                ? "bg-emerald-500/20 text-emerald-400" 
                : "bg-zinc-800 text-zinc-400"
            }`}>
              {clock.marketStatus}
            </span>
          </div>
        ) : (
          <div className="px-3 py-1 rounded-lg bg-zinc-900/50 border border-zinc-800/60 text-[11px] font-mono text-zinc-500">
            --:--:-- TSİ (Yükleniyor...)
          </div>
        )}

        {/* Canlı Motor Nabzı */}
        <div 
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-bold border transition-colors ${
            isLive 
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
              : "bg-amber-500/10 border-amber-500/30 text-amber-400"
          }`}
          title={`Son senkronizasyon: ${secondsAgo} saniye önce`}
        >
          <div className={`w-1.5 h-1.5 rounded-full ${isLive ? "bg-emerald-400 animate-ping" : "bg-amber-400"}`} />
          <span>{isLive ? "CANLI AKIŞ" : `${secondsAgo}s ÖNCE`}</span>
        </div>
      </div>
    </header>
  );
}
