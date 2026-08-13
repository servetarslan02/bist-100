"use client";

interface Strategy {
  name: string;
  type: string;
  status: "ACTIVE" | "PAUSED" | "WATCH";
  description: string;
  signals: number;
  winRate: number;
  avgReturn: number;
}

const STRATEGIES: Strategy[] = [
  { name: "Momentum", type: "MOMENTUM", status: "ACTIVE", description: "Kısa-orta vadeli momentum sinyalleri", signals: 12, winRate: 64, avgReturn: 3.2 },
  { name: "Breakout", type: "BREAKOUT", status: "ACTIVE", description: "Fiyat sıkışması sonrası kırılım", signals: 8, winRate: 58, avgReturn: 4.1 },
  { name: "Mean Reversion", type: "MEAN_REVERSION", status: "PAUSED", description: "Ortalama dönüş stratejisi", signals: 0, winRate: 52, avgReturn: 1.8 },
  { name: "Event Driven", type: "EVENT_DRIVEN", status: "ACTIVE", description: "KAP/haber bazlı strateji", signals: 5, winRate: 71, avgReturn: 5.4 },
  { name: "SPEC", type: "SPEC", status: "WATCH", description: "Olağandışı hareket tespiti", signals: 3, winRate: 68, avgReturn: 6.2 },
  { name: "Value", type: "VALUE", status: "ACTIVE", description: "Fundamental değer odaklı", signals: 15, winRate: 60, avgReturn: 2.8 },
  { name: "Defensive", type: "DEFENSIVE", status: "ACTIVE", description: "Korunma odaklı strateji", signals: 4, winRate: 75, avgReturn: 1.2 },
];

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  ACTIVE: { bg: "bg-emerald-950", text: "text-emerald-400" },
  PAUSED: { bg: "bg-amber-950", text: "text-amber-400" },
  WATCH: { bg: "bg-zinc-800", text: "text-zinc-400" },
};

export default function StrategyCenter() {
  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Strategy Center</h1>
        <p className="text-[11px] text-zinc-600">Trading strategies • regime-adaptive • auto-toggle</p>
      </div>

      {/* Strategy Grid */}
      <div className="grid grid-cols-2 gap-3">
        {STRATEGIES.map(strategy => {
          const statusConfig = STATUS_COLORS[strategy.status];
          return (
            <div key={strategy.name} className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3 hover:border-zinc-700/60 transition-colors">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-zinc-200">{strategy.name}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">{strategy.type}</span>
                </div>
                <span className={`text-[9px] px-1.5 py-0.5 rounded ${statusConfig.bg} ${statusConfig.text}`}>
                  {strategy.status}
                </span>
              </div>

              <p className="text-[11px] text-zinc-600 mb-3">{strategy.description}</p>

              <div className="grid grid-cols-3 gap-2">
                <div>
                  <p className="text-[9px] text-zinc-600">Signals</p>
                  <p className="text-sm font-mono text-zinc-300">{strategy.signals}</p>
                </div>
                <div>
                  <p className="text-[9px] text-zinc-600">Win Rate</p>
                  <p className={`text-sm font-mono ${strategy.winRate >= 60 ? "text-emerald-400" : "text-zinc-400"}`}>
                    {strategy.winRate}%
                  </p>
                </div>
                <div>
                  <p className="text-[9px] text-zinc-600">Avg Return</p>
                  <p className="text-sm font-mono text-emerald-400">+{strategy.avgReturn}%</p>
                </div>
              </div>

              {/* Mini performance bar */}
              <div className="mt-2 flex items-center gap-1">
                {Array.from({ length: 20 }, (_, i) => {
                  const isActive = i < strategy.winRate / 5;
                  return (
                    <div
                      key={i}
                      className={`h-1 flex-1 rounded-sm ${isActive ? "bg-emerald-500/60" : "bg-zinc-800"}`}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Regime-Strategy Matrix */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
        <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Regime-Strategy Matrix</h2>
        <div className="text-[11px] text-zinc-500">
          <p>Strategies automatically adjust based on market regime:</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div className="flex items-center gap-2">
              <span className="text-emerald-400">●</span>
              <span>TRENDING-UP → Momentum + Breakout active</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-amber-400">●</span>
              <span>RANGE → Mean Reversion + Value active</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-red-400">●</span>
              <span>RISK-OFF → Defensive active, others paused</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-purple-400">●</span>
              <span>HIGH-VOL → SPEC + Event Driven active</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
