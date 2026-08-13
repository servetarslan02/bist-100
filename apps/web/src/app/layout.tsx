import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ALPHA BIST — Market Intelligence",
  description: "BIST Market Intelligence & Quant Engine",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr">
      <body className="bg-alpha-bg text-alpha-text antialiased">
        <div className="flex h-screen">
          {/* Sidebar */}
          <aside className="w-56 bg-alpha-surface border-r border-alpha-border flex flex-col">
            <div className="p-4 border-b border-alpha-border">
              <h1 className="text-lg font-bold text-alpha-accent">ALPHA BIST</h1>
              <p className="text-xs text-alpha-muted">Market Intelligence v1.0</p>
            </div>

            <nav className="flex-1 overflow-y-auto p-2">
              <div className="mb-4">
                <p className="text-xs text-alpha-muted uppercase px-2 mb-1">Core</p>
                <NavLink href="/" label="Overview" />
                <NavLink href="/radar" label="Market Radar" />
                <NavLink href="/map" label="Market Map" />
                <NavLink href="/events" label="Event Center" />
              </div>

              <div className="mb-4">
                <p className="text-xs text-alpha-muted uppercase px-2 mb-1">Intelligence</p>
                <NavLink href="/opportunities" label="Opportunities" />
                <NavLink href="/asset" label="Asset Intelligence" />
                <NavLink href="/world" label="World Intelligence" />
                <NavLink href="/research" label="AI Research" />
              </div>

              <div className="mb-4">
                <p className="text-xs text-alpha-muted uppercase px-2 mb-1">Portfolio</p>
                <NavLink href="/portfolio" label="Portfolio" />
                <NavLink href="/scenario" label="Scenario Lab" />
                <NavLink href="/strategy" label="Strategy Center" />
              </div>

              <div className="mb-4">
                <p className="text-xs text-alpha-muted uppercase px-2 mb-1">Models</p>
                <NavLink href="/models" label="Model Center" />
                <NavLink href="/learning" label="Learning Lab" />
              </div>

              <div className="mb-4">
                <p className="text-xs text-alpha-muted uppercase px-2 mb-1">System</p>
                <NavLink href="/data" label="Data Center" />
                <NavLink href="/alerts" label="Alert Center" />
                <NavLink href="/system" label="System Health" />
              </div>
            </nav>

            <div className="p-3 border-t border-alpha-border">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-alpha-accent live-indicator" />
                <span className="text-xs text-alpha-muted">LIVE</span>
              </div>
            </div>
          </aside>

          {/* Main content */}
          <main className="flex-1 overflow-y-auto">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}

function NavLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      className="block px-2 py-1.5 text-sm text-alpha-muted hover:text-alpha-text hover:bg-alpha-border rounded transition-colors"
    >
      {label}
    </a>
  );
}
