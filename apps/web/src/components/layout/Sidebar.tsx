"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Radar, Target, LineChart,
  Briefcase, Cpu, Activity, Database,
  ChevronRight, Zap, Globe, Bell, Radio, Layers,
  Map, TrendingUp, Sparkles
} from "lucide-react";

const NAV_ITEMS = [
  {
    group: "ÇEKİRDEK",
    items: [
      { href: "/", label: "Genel Bakış", icon: LayoutDashboard },
      { href: "/radar", label: "Piyasa Radarı", icon: Radar },
      { href: "/map", label: "Sektör Isı Haritası", icon: Map },
    ],
  },
  {
    group: "İSTİHBARAT & HABER",
    items: [
      { href: "/opportunities", label: "Otonom Fırsatlar", icon: Target },
      { href: "/events", label: "KAP & Haber Akışı", icon: Zap },
      { href: "/research", label: "AI Araştırma Raporları", icon: Sparkles },
      { href: "/world", label: "Küresel Makro & Dünya", icon: Globe },
      { href: "/alerts", label: "Canlı Alarmlar", icon: Bell },
      { href: "/asset", label: "Varlık Analizi", icon: LineChart },
    ],
  },
  {
    group: "PORTFÖY & İŞLEM",
    items: [
      { href: "/portfolio", label: "Canlı Portföy", icon: Briefcase },
      { href: "/strategy", label: "Strateji & Backtest", icon: TrendingUp },
    ],
  },
  {
    group: "MODELLER & ML",
    items: [
      { href: "/models", label: "Model Merkezi", icon: Cpu },
      { href: "/learning", label: "Öğrenme Lab", icon: Activity },
    ],
  },
  {
    group: "VERİ & SİSTEM",
    items: [
      { href: "/data", label: "Veri Kaynakları", icon: Radio },
      { href: "/scenario", label: "Senaryo & Stres", icon: Layers },
      { href: "/system", label: "Sistem Sağlığı", icon: Database },
    ],
  },
];

import { useGlobalSyncStatus } from "@/lib/api";

export function Sidebar() {
  const pathname = usePathname();
  const { lastSync, secondsAgo } = useGlobalSyncStatus();

  return (
    <aside
      style={{ background: "var(--color-bg-secondary)", borderRight: "1px solid var(--color-border-subtle)" }}
      className="w-[220px] flex flex-col h-screen sticky top-0 overflow-hidden select-none"
    >
      <div className="px-5 py-5" style={{ borderBottom: "1px solid var(--color-border-subtle)" }}>
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{
              background: "linear-gradient(135deg, rgba(0,229,160,0.2) 0%, rgba(0,200,255,0.1) 100%)",
              border: "1px solid rgba(0,229,160,0.3)",
              boxShadow: "0 0 16px rgba(0,229,160,0.1)"
            }}
          >
            <span className="text-sm font-bold gradient-text">A</span>
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight" style={{ color: "var(--color-text-primary)" }}>
              ALPHA BIST
            </h1>
            <p className="text-[10px] uppercase tracking-widest" style={{ color: "var(--color-text-muted)" }}>
              CANLI SİSTEM
            </p>
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-3 px-2">
        {NAV_ITEMS.map((group) => (
          <div key={group.group} className="mb-4">
            <p
              className="text-[9px] uppercase tracking-widest font-semibold px-3 mb-1.5"
              style={{ color: "var(--color-text-faint)" }}
            >
              {group.group}
            </p>
            {group.items.map((item) => {
              const isActive = pathname === item.href;
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={true}
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] mb-0.5 transition-all duration-150 group ${
                    isActive ? "nav-active" : "hover:bg-white/5"
                  }`}
                  style={{
                    color: isActive ? "var(--color-accent-green)" : "var(--color-text-secondary)",
                    borderLeft: isActive ? undefined : "2px solid transparent",
                  }}
                >
                  <Icon
                    size={14}
                    className="flex-shrink-0"
                    style={{ opacity: isActive ? 1 : 0.6 }}
                  />
                  <span className="flex-1 font-medium">{item.label}</span>
                  {isActive && (
                    <ChevronRight size={11} style={{ opacity: 0.5 }} />
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="px-4 py-3" style={{ borderTop: "1px solid var(--color-border-subtle)" }}>
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full flex-shrink-0 ${
              secondsAgo < 10
                ? "bg-emerald-400 animate-pulse shadow-[0_0_8px_#00e5a0]"
                : secondsAgo < 25
                ? "bg-amber-400 shadow-[0_0_8px_#ffaa00]"
                : "bg-rose-500 shadow-[0_0_8px_#ff4466]"
            }`}
          />
          <span
            className="text-[10px] font-bold uppercase tracking-wider"
            style={{
              color:
                secondsAgo < 10
                  ? "var(--color-accent-green)"
                  : secondsAgo < 25
                  ? "#ffaa00"
                  : "#ff4466",
            }}
          >
            CANLI MOTOR
          </span>
        </div>
      </div>
    </aside>
  );
}
