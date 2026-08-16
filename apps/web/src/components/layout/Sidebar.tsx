"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  {
    group: "CORE",
    items: [
      { href: "/", label: "Overview", icon: "◉" },
      { href: "/radar", label: "Market Radar", icon: "◎" },
      { href: "/map", label: "Market Map", icon: "◫" },
      { href: "/events", label: "Event Center", icon: "⚡" },
    ],
  },
  {
    group: "INTELLIGENCE",
    items: [
      { href: "/opportunities", label: "Opportunities", icon: "◈" },
      { href: "/asset", label: "Asset Intel", icon: "◉" },
      { href: "/world", label: "World Intel", icon: "⊕" },
      { href: "/research", label: "AI Research", icon: "◎" },
    ],
  },
  {
    group: "PORTFOLIO",
    items: [
      { href: "/portfolio", label: "Portfolio", icon: "▦" },
      { href: "/scenario", label: "Scenario Lab", icon: "◧" },
      { href: "/strategy", label: "Strategy", icon: "◨" },
    ],
  },
  {
    group: "MODELS",
    items: [
      { href: "/models", label: "Model Center", icon: "⬡" },
      { href: "/learning", label: "Learning Lab", icon: "⬢" },
    ],
  },
  {
    group: "SYSTEM",
    items: [
      { href: "/data", label: "Data Center", icon: "▤" },
      { href: "/alerts", label: "Alert Center", icon: "⚑" },
      { href: "/system", label: "System Health", icon: "⚙" },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-[200px] bg-zinc-950 border-r border-zinc-800/60 flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-zinc-800/60">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center">
            <span className="text-emerald-400 text-xs font-bold">A</span>
          </div>
          <div>
            <h1 className="text-sm font-semibold text-zinc-100 tracking-tight">ALPHA</h1>
            <p className="text-[9px] text-zinc-600 uppercase tracking-widest">BIST Intelligence</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {NAV_ITEMS.map((group) => (
          <div key={group.group} className="mb-3">
            <p className="text-[9px] uppercase tracking-widest text-zinc-600 font-medium px-2 mb-1">
              {group.group}
            </p>
            {group.items.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded text-[13px] transition-colors ${
                    isActive
                      ? "bg-zinc-800/80 text-zinc-100"
                      : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/40"
                  }`}
                >
                  <span className="text-[11px] w-4 text-center opacity-60">{item.icon}</span>
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Status */}
      <div className="px-3 py-3 border-t border-zinc-800/60">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-[10px] text-zinc-500 uppercase tracking-wider">Live</span>
        </div>
        <p className="text-[10px] text-zinc-600 mt-1">
          {new Date().toLocaleTimeString("tr-TR")}
        </p>
      </div>
    </aside>
  );
}
