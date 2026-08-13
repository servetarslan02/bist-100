"use client";

interface LearningMetric {
  label: string;
  value: string;
  trend: "up" | "down" | "neutral";
  detail: string;
}

const METRICS: LearningMetric[] = [
  { label: "Prediction Accuracy", value: "68.4%", trend: "up", detail: "+2.1% vs last week" },
  { label: "Sharpe Ratio", value: "1.38", trend: "up", detail: "Walk-forward validated" },
  { label: "Max Drawdown", value: "-12.4%", trend: "down", detail: "Within risk limits" },
  { label: "Win Rate", value: "64.2%", trend: "up", detail: "234/364 trades" },
  { label: "Profit Factor", value: "1.82", trend: "up", detail: "Gross profit / Gross loss" },
  { label: "Model Confidence", value: "0.91", trend: "neutral", detail: "Calibration: 0.89" },
];

const RECENT_OUTCOMES = [
  { ticker: "THYAO", predicted: "+4.2%", actual: "+5.1%", correct: true, date: "2026-08-09" },
  { ticker: "ASELS", predicted: "+3.8%", actual: "-1.2%", correct: false, date: "2026-08-08" },
  { ticker: "AKBNK", predicted: "-2.1%", actual: "-3.4%", correct: true, date: "2026-08-07" },
  { ticker: "TUPRS", predicted: "+6.0%", actual: "+4.8%", correct: true, date: "2026-08-06" },
  { ticker: "EREGL", predicted: "+1.5%", actual: "+2.1%", correct: true, date: "2026-08-05" },
];

export default function LearningLab() {
  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Learning Lab</h1>
        <p className="text-[11px] text-zinc-600">Model performance • prediction tracking • continuous learning</p>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-3 gap-3">
        {METRICS.map(m => (
          <div key={m.label} className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
            <p className="text-[9px] uppercase tracking-wider text-zinc-600">{m.label}</p>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-lg font-mono font-semibold text-zinc-200">{m.value}</span>
              <span className={`text-[10px] ${
                m.trend === "up" ? "text-emerald-400" : m.trend === "down" ? "text-red-400" : "text-zinc-500"
              }`}>
                {m.trend === "up" ? "↑" : m.trend === "down" ? "↓" : "→"}
              </span>
            </div>
            <p className="text-[9px] text-zinc-600 mt-0.5">{m.detail}</p>
          </div>
        ))}
      </div>

      {/* Recent Outcomes */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg overflow-hidden">
        <div className="px-4 py-2.5 border-b border-zinc-800/60">
          <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium">Recent Prediction Outcomes</h2>
        </div>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800/40 bg-zinc-950/50">
              <th className="text-left py-1.5 px-3 font-medium">DATE</th>
              <th className="text-left py-1.5 px-3 font-medium">TICKER</th>
              <th className="text-right py-1.5 px-3 font-medium">PREDICTED</th>
              <th className="text-right py-1.5 px-3 font-medium">ACTUAL</th>
              <th className="text-center py-1.5 px-3 font-medium">RESULT</th>
            </tr>
          </thead>
          <tbody>
            {RECENT_OUTCOMES.map((o, i) => (
              <tr key={i} className="border-b border-zinc-800/20">
                <td className="py-1.5 px-3 text-zinc-500 font-mono">{o.date}</td>
                <td className="py-1.5 px-3 font-semibold text-zinc-200">{o.ticker}</td>
                <td className="py-1.5 px-3 text-right font-mono text-zinc-400">{o.predicted}</td>
                <td className={`py-1.5 px-3 text-right font-mono ${o.correct ? "text-emerald-400" : "text-red-400"}`}>
                  {o.actual}
                </td>
                <td className="py-1.5 px-3 text-center">
                  <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                    o.correct ? "bg-emerald-950 text-emerald-400" : "bg-red-950 text-red-400"
                  }`}>
                    {o.correct ? "✓ CORRECT" : "✗ WRONG"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Learning Pipeline */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
        <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Learning Pipeline</h2>
        <div className="flex items-center gap-2 text-[10px] overflow-x-auto pb-2">
          {["Predictions", "Outcomes", "Error Analysis", "Dataset", "Retrain", "Validation", "Walk-Forward", "Paper Trade", "Champion"].map((step, i) => (
            <div key={step} className="flex items-center gap-2 shrink-0">
              <div className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700/50 text-zinc-400 whitespace-nowrap">
                {step}
              </div>
              {i < 8 && <span className="text-zinc-700">→</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
