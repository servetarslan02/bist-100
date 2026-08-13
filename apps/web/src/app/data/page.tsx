"use client";

interface DataSource {
  name: string;
  type: string;
  status: "ACTIVE" | "DELAYED" | "UNAVAILABLE";
  latency: string;
  lastUpdate: string;
  records: string;
  description: string;
}

const DATA_SOURCES: DataSource[] = [
  { name: "yfinance", type: "MARKET", status: "ACTIVE", latency: "15min", lastUpdate: "2 sec ago", records: "800+ stocks", description: "BIST delayed market data (free)" },
  { name: "KAP", type: "CORPORATE", status: "ACTIVE", latency: "Real-time", lastUpdate: "5 min ago", records: "742 companies", description: "Company disclosures, financial reports" },
  { name: "TCMB EVDS", type: "MACRO", status: "ACTIVE", latency: "Daily", lastUpdate: "1 hour ago", records: "145 categories", description: "Interest rates, inflation, FX reserves" },
  { name: "NewsAPI", type: "NEWS", status: "DELAYED", latency: "~5 min", lastUpdate: "3 min ago", records: "50 articles/cycle", description: "Financial news aggregation" },
  { name: "Alpha Vantage", type: "GLOBAL", status: "ACTIVE", latency: "15min", lastUpdate: "10 min ago", records: "Global indices", description: "S&P500, Nasdaq, DAX, Gold, Oil" },
  { name: "RSS Feeds", type: "NEWS", status: "ACTIVE", latency: "~10 min", lastUpdate: "8 min ago", records: "3 sources", description: "Dünya, ParaAnaliz, Borsa Gündem" },
];

const STATUS_COLORS: Record<string, { dot: string; text: string }> = {
  ACTIVE: { dot: "bg-emerald-500", text: "text-emerald-400" },
  DELAYED: { dot: "bg-amber-500", text: "text-amber-400" },
  UNAVAILABLE: { dot: "bg-red-500", text: "text-red-400" },
};

export default function DataCenter() {
  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Data Center</h1>
        <p className="text-[11px] text-zinc-600">Data sources • quality monitoring • pipeline health</p>
      </div>

      {/* Data Sources */}
      <div className="space-y-2">
        {DATA_SOURCES.map(source => {
          const statusConfig = STATUS_COLORS[source.status];
          return (
            <div key={source.name} className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3 hover:border-zinc-700/60 transition-colors">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${statusConfig.dot}`} />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] font-semibold text-zinc-200">{source.name}</span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">{source.type}</span>
                    </div>
                    <p className="text-[10px] text-zinc-600 mt-0.5">{source.description}</p>
                  </div>
                </div>
                <div className="text-right">
                  <div className="flex items-center gap-3 text-[10px]">
                    <div>
                      <p className="text-zinc-600">Latency</p>
                      <p className="font-mono text-zinc-400">{source.latency}</p>
                    </div>
                    <div>
                      <p className="text-zinc-600">Records</p>
                      <p className="font-mono text-zinc-400">{source.records}</p>
                    </div>
                    <div>
                      <p className="text-zinc-600">Last Update</p>
                      <p className="font-mono text-zinc-400">{source.lastUpdate}</p>
                    </div>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded ${statusConfig.text} ${
                      source.status === "ACTIVE" ? "bg-emerald-950" :
                      source.status === "DELAYED" ? "bg-amber-950" : "bg-red-950"
                    }`}>
                      {source.status}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Pipeline Stats */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
        <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Pipeline Statistics</h2>
        <div className="grid grid-cols-4 gap-4 text-[11px]">
          <div>
            <p className="text-zinc-600">Total Events Today</p>
            <p className="font-mono text-zinc-200">~1.2M</p>
          </div>
          <div>
            <p className="text-zinc-600">Events/sec (avg)</p>
            <p className="font-mono text-zinc-200">~4,800</p>
          </div>
          <div>
            <p className="text-zinc-600">Dropped Events</p>
            <p className="font-mono text-emerald-400">0</p>
          </div>
          <div>
            <p className="text-zinc-600">Data Completeness</p>
            <p className="font-mono text-zinc-200">99.99%</p>
          </div>
        </div>
      </div>
    </div>
  );
}
