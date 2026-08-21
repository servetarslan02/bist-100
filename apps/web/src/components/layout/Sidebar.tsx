"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Radar, Map, Zap,
  Target, LineChart, Globe, FlaskConical,
  Briefcase, TestTube, TrendingUp,
  Cpu, Database, Bell, Activity,
  ChevronRight
} from "lucide-react";

const NAV_ITEMS = [
  {
    group: "ÇEKİRDEK",
    items: [
      { href: "/", label: "Genel Bakış", icon: LayoutDashboard },
      { href: "/radar", label: "Piyasa Radarı", icon: Radar },
      { href: "/map", label: "Piyasa Haritası", icon: Map },
      { href: "/events", label: "Olay Merkezi", icon: Zap },
    ],
  },
  {
    group: "İSTİHBARAT & ANALİZ",
    items: [
      { href: "/opportunities", label: "Fırsatlar", icon: Target },
      { href: "/asset", label: "Varlık Analizi", icon: LineChart },
      { href: "/world", label: "Küresel Durum", icon: Globe },
      { href: "/research", label: "Yapay Zeka Analiz", icon: FlaskConical },
    ],
  },
  {
    group: "PORTFÖY & İŞLEM",
    items: [
      { href: "/portfolio", label: "Portföy", icon: Briefcase },
      { href: "/scenario", label: "Senaryo Testi", icon: TestTube },
      { href: "/strategy", label: "Stratejiler", icon: TrendingUp },
    ],
  },
  {
    group: "MODELLER & ML",
    items: [
      { href: "/models", label: "Model Merkezi", icon: Cpu },
      { href: "/learning", label: "Öğrenme Laboratuvarı", icon: Activity },
    ],
  },
  {
    group: "SİSTEM & VERİ",
    items: [
      { href: "/data", label: "Veri Merkezi", icon: Database },
      { href: "/alerts", label: "Alarm Merkezi", icon: Bell },
      { href: "/system", label: "Sistem Sağlığı", icon: Activity },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      style={{ background: "var(--color-bg-secondary)", borderRight: "1px solid var(--color-border-subtle)" }}
      className="w-[220px] flex flex-col h-screen sticky top-0 overflow-hidden select-none"
    >
      {/* Logo */}
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
              Kantitatif İstihbarat
            </p>
          </div>
        </div>
      </div>

      {/* Navigation */}
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

      {/* Footer */}
      <div className="px-4 py-3" style={{ borderTop: "1px solid var(--color-border-subtle)" }}>
        <div className="flex items-center gap-2">
          <div
            className="w-1.5 h-1.5 rounded-full live-dot flex-shrink-0"
            style={{ background: "var(--color-accent-green)" }}
          />
          <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--color-text-muted)" }}>
            CANLI
          </span>
          <span className="text-[10px] font-data ml-auto" style={{ color: "var(--color-text-faint)" }}>
            {new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
      </div>
    </aside>
  );
}
