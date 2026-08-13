"use client";

interface Discovery {
  id: string;
  timestamp: string;
  title: string;
  description: string;
  confidence: number;
  status: "INVESTIGATING" | "CONFIRMED" | "DISMISSED";
  evidence: string[];
  category: string;
}

const DISCOVERIES: Discovery[] = [
  {
    id: "18421",
    timestamp: "2026-08-14T10:32",
    title: "Bankacılık sektöründe olağandışı çapraz ayrışma",
    description: "BIST bankacılık endeksi içinde AKBNK ve GARAN arasında son 3 günde olağandışı bir göreceli güç farkı tespit edildi.",
    confidence: 87,
    status: "INVESTIGATING",
    evidence: ["17 değişken analiz edildi", "2,841 tarihsel benzer durum", "6 bağımsız kaynak doğruladı"],
    category: "SECTOR",
  },
  {
    id: "18420",
    timestamp: "2026-08-14T09:15",
    title: "Enerji sektöründe momentum paterni",
    description: "TUPRS, PETKM ve AKENR'de benzer momentum yapısı gözlemleniyor. Geçmişte bu pattern %68 olasılıkla pozitif devam etmiş.",
    confidence: 72,
    status: "CONFIRMED",
    evidence: ["Volume anomaly tespit edildi", "Sektör göreceli güç artıyor", "KAP olayları pozitif"],
    category: "MOMENTUM",
  },
  {
    id: "18419",
    timestamp: "2026-08-13T16:45",
    title: "Makro risk değişim sinyali",
    description: "TCMB faiz kararı sonrası piyasa rejimi değişimi belirtileri. VIX artışı ve USD güçlenmesi eş zamanlı.",
    confidence: 91,
    status: "CONFIRMED",
    evidence: ["VIX +15%", "USD/TRY +1.2%", "BIST breadth daralıyor"],
    category: "MACRO",
  },
];

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  INVESTIGATING: { bg: "bg-amber-950", text: "text-amber-400" },
  CONFIRMED: { bg: "bg-emerald-950", text: "text-emerald-400" },
  DISMISSED: { bg: "bg-zinc-800", text: "text-zinc-500" },
};

export default function AIResearch() {
  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">AI Research</h1>
        <p className="text-[11px] text-zinc-600">Discovery log • pattern detection • evidence analysis</p>
      </div>

      <div className="space-y-3">
        {DISCOVERIES.map(d => {
          const statusConfig = STATUS_COLORS[d.status];
          return (
            <div key={d.id} className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4 hover:border-zinc-700/60 transition-colors cursor-pointer">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] font-mono text-zinc-600">#{d.id}</span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded ${statusConfig.bg} ${statusConfig.text}`}>
                      {d.status}
                    </span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">{d.category}</span>
                  </div>
                  <h3 className="text-[13px] font-medium text-zinc-200 mt-1">{d.title}</h3>
                </div>
                <div className="text-right">
                  <p className="text-[9px] text-zinc-600">Confidence</p>
                  <p className={`text-sm font-mono font-semibold ${
                    d.confidence >= 80 ? "text-emerald-400" : d.confidence >= 60 ? "text-amber-400" : "text-zinc-400"
                  }`}>
                    {d.confidence}%
                  </p>
                </div>
              </div>

              <p className="text-[11px] text-zinc-500 mb-3">{d.description}</p>

              <div className="flex items-center gap-3">
                <span className="text-[9px] text-zinc-600">{d.timestamp}</span>
                <span className="text-[9px] text-zinc-700">•</span>
                <span className="text-[9px] text-zinc-600">Evidence:</span>
                {d.evidence.map((e, i) => (
                  <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">{e}</span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
