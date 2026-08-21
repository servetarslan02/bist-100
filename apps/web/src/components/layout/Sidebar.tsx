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
    group: "CORE",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/radar", label: "Market Radar", icon: Radar },
      { href: "/map", label: "Market Map", icon: Map },
      { href: "/events", label: "Event Center", icon: Zap },
    ],
  },
  {
    group: "INTELLIGENCE",
    items: [
      { href: "/opportunities", label: "Opportunities", icon: Target },
      { href: "/asset", label: "Asset Intel", icon: LineChart },
      { href: "/world", label: "World Intel", icon: Globe },
      { href: "/research", label: "AI Research", icon: FlaskConical },
    ],
  },
  {
    group: "PORTFOLIO",
    items: [
      { href: "/portfolio", label: "Portfolio", icon: Briefcase },
      { href: "/scenario", label: "Scenario Lab", icon: TestTube },
      { href: "/strategy", label: "Strategy", icon: TrendingUp },
    ],
  },
  {
    group: "MODELS",
    items: [
      { href: "/models", label: "Model Center", icon: Cpu },
      { href: "/learning", label: "Learning Lab", icon: Activity },
    ],
  },
  {
    group: "SYSTEM",
    items: [
      { href: "/data", label: "Data Center", icon: Database },
      { href: "/alerts", label: "Alert Center", icon: Bell },
      { href: "/system", label: "System Health", icon: Activity },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      style={{ background: "var(--color-bg-secondary)", borderRight: "1px solid var(--color-border-subtle)" }}
      className="w-[220px] flex flex-col h-screen sticky top-0 overflow-hidden"
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
              Intelligence
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
            Live
          </span>
          <span className="text-[10px] font-data ml-auto" style={{ color: "var(--color-text-faint)" }}>
            {new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
      </div>
    </aside>
  );
}
