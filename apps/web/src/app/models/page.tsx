"use client";

import { useState, useMemo } from "react";
import { usePolling } from "@/lib/api";
import {
  Cpu, Activity, CheckCircle2, TrendingUp, BarChart2, ShieldCheck,
  ExternalLink, Layers, Award, RefreshCw, Sliders, Filter
} from "lucide-react";
import { SkeletonList } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

interface ModelRegistryItem {
  id: string;
  model_id?: string;
  name: string;
  type: string;
  role: string;
  version: string;
  status: "CHAMPION" | "CHALLENGER" | "EVALUATION";
  metrics: {
    ic: number;
    r2: number;
    sharpe: number;
    latency_ms: number;
  };
  features_count: number;
  last_trained: string;
  regime?: string;
}

interface FeatureImportanceItem {
  feature: string;
  importance: number;
  normalized_pct: number;
}

interface LearningStateData {
  learning_loop?: Record<string, any>;
  retrain_needed?: boolean;
  retrain_reason?: string;
  canonical_features_count?: number;
  calibration_status?: string;
}

export default function ModelCenterPage() {
  const [activeTab, setActiveTab] = useState<"models" | "features" | "matrix">("models");
  const [statusFilter, setStatusFilter] = useState<"ALL" | "CHAMPION" | "CHALLENGER" | "EVALUATION">("ALL");

  // 1. Kayıtlı Modeller
  const { data: modelsData, loading: modelsLoading, refetch: refetchModels } = usePolling<{ models: ModelRegistryItem[] }>(
    "/models/list",
    15000
  );

  // 2. Öznitelik Önem Düzeyleri (Feature Importance)
  const { data: featData, loading: featLoading, refetch: refetchFeatures } = usePolling<{ top_features: FeatureImportanceItem[] }>(
    "/models/feature-importance",
    30000
  );

  // 3. Otonom Öğrenme Döngüsü Durumu
  const { data: learnData } = usePolling<LearningStateData>(
    "/models/learning-state",
    20000
  );

  // Yeniden Eğitim Aksiyonu
  const [retraining, setRetraining] = useState(false);
  const [retrainMsg, setRetrainMsg] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const models: ModelRegistryItem[] = useMemo(() => modelsData?.models || [], [modelsData]);
  const features: FeatureImportanceItem[] = useMemo(() => featData?.top_features || [], [featData]);

  // Filtrelenmiş Modeller
  const filteredModels = useMemo(() => {
    if (statusFilter === "ALL") return models;
    return models.filter(m => m.status === statusFilter);
  }, [models, statusFilter]);

  // Şampiyon Model
  const championModel = useMemo(() => {
    return models.find(m => m.status === "CHAMPION") || models[0];
  }, [models]);

  const handleTriggerRetrain = async () => {
    setRetraining(true);
    setRetrainMsg(null);
    try {
      const res = await fetch("/api/v1/models/retrain?force=true", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setRetrainMsg({
          text: data.message || "Otonom yeniden eğitim döngüsü tetiklendi ve modeller güncellendi.",
          type: "success",
        });
        refetchModels();
        refetchFeatures();
      } else {
        throw new Error(data.detail || `Hata kodu: ${res.status}`);
      }
    } catch (e: any) {
      setRetrainMsg({
        text: e.message || "Yeniden eğitim tetiklenirken hata oluştu.",
        type: "error",
      });
    } finally {
      setRetraining(false);
      setTimeout(() => setRetrainMsg(null), 6000);
    }
  };

  return (
    <ErrorBoundary name="models">
      <div className="relative min-h-screen pb-12 overflow-hidden" style={{ background: "var(--color-bg-primary)" }}>
        {/* Ambient Radial Glow */}
        <div 
          className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[900px] h-[300px] opacity-15 blur-[120px] rounded-full"
          style={{ background: "radial-gradient(ellipse, #00e5a0 0%, #00c8ff 40%, transparent 70%)" }}
        />

        <div className="relative max-w-7xl mx-auto p-3.5 md:p-5 lg:p-6 space-y-3.5">

          {/* 1. ULTRA KOMPAKT HEADER & KONTROL ŞERİDİ */}
          <div className="rounded-xl px-4 py-3 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-3">
            
            {/* Sol: Başlık ve Canlı İntel Rozetleri */}
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="flex items-center gap-2">
                <Cpu size={18} className="text-emerald-400 shrink-0" />
                <h1 className="text-lg font-extrabold text-white tracking-tight">
                  Model Merkezi
                </h1>
              </div>

              <div className="h-3.5 w-px bg-white/[0.1] hidden sm:block" />

              {/* Kompakt Canlı Rozetler */}
              <div className="flex flex-wrap items-center gap-1.5 text-xs font-data">
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-semibold">
                  <Award size={11} />
                  <span>Şampiyon: {championModel?.name || "LightGBM"}</span>
                  <span className="text-xs text-emerald-400 font-mono">({championModel?.version || "v3.0.1"})</span>
                </span>

                <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                  {championModel?.features_count || 70} Faktör
                </span>

                <span className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-white/[0.03] border border-white/[0.06] text-zinc-300">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span>{championModel?.metrics?.latency_ms ?? 1.2} ms</span>
                </span>
              </div>
            </div>

            {/* Sağ: Sekmeler ve Aksiyon Butonları */}
            <div className="flex flex-wrap items-center gap-2">
              {/* Sekme Seçici */}
              <div className="flex bg-zinc-950/80 p-0.5 rounded-lg border border-white/[0.08] text-xs font-semibold">
                <button
                  onClick={() => setActiveTab("models")}
                  className={`px-3 py-1 rounded-md transition-all cursor-pointer ${
                    activeTab === "models"
                      ? "bg-emerald-500/20 text-emerald-300 font-bold border border-emerald-500/30 shadow-sm"
                      : "text-zinc-400 hover:text-white"
                  }`}
                >
                  Modeller ({models.length})
                </button>
                <button
                  onClick={() => setActiveTab("features")}
                  className={`px-3 py-1 rounded-md transition-all cursor-pointer ${
                    activeTab === "features"
                      ? "bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-500/30 shadow-sm"
                      : "text-zinc-400 hover:text-white"
                  }`}
                >
                  Öznitelikler (15)
                </button>
                <button
                  onClick={() => setActiveTab("matrix")}
                  className={`px-3 py-1 rounded-md transition-all cursor-pointer ${
                    activeTab === "matrix"
                      ? "bg-purple-500/20 text-purple-300 font-bold border border-purple-500/30 shadow-sm"
                      : "text-zinc-400 hover:text-white"
                  }`}
                >
                  Matris
                </button>
              </div>

              {/* Butonlar */}
              <button
                onClick={handleTriggerRetrain}
                disabled={retraining}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-emerald-400 to-teal-500 text-zinc-950 shadow-md shadow-emerald-500/20 active:scale-95 cursor-pointer disabled:opacity-50"
                title="Otonom yeniden eğitimi ve hot-reload tetikle"
              >
                <RefreshCw size={12} className={retraining ? "animate-spin" : ""} />
                <span>{retraining ? "Eğitiliyor..." : "⚡ Eğit"}</span>
              </button>

              <a
                href="http://localhost:5000"
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-zinc-900 border border-white/[0.08] text-zinc-400 hover:text-white hover:border-white/[0.2] transition-colors"
                title="MLflow Deney Takip Paneli"
              >
                <ExternalLink size={12} />
                <span>MLflow</span>
              </a>
            </div>
          </div>

          {/* Bildirim Şeridi */}
          {retrainMsg && (
            <div className={`p-2.5 rounded-xl border text-xs font-medium flex items-center justify-between transition-all ${
              retrainMsg.type === "success" 
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300" 
                : "bg-rose-500/10 border-rose-500/30 text-rose-300"
            }`}>
              <div className="flex items-center gap-2">
                <CheckCircle2 size={15} />
                <span>{retrainMsg.text}</span>
              </div>
              <button onClick={() => setRetrainMsg(null)} className="text-zinc-400 hover:text-white text-xs cursor-pointer">✕</button>
            </div>
          )}

          {/* ============================================================ */}
          {/* SEKME 1: MODELLER & ENSEMBLE KARTLARI */}
          {/* ============================================================ */}
          {activeTab === "models" && (
            <div className="space-y-3">
              {/* Filtre Butonları */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-1">
                  <span className="text-zinc-500 mr-1 flex items-center gap-1 text-xs">
                    <Filter size={11} />
                    Filtre:
                  </span>
                  {(["ALL", "CHAMPION", "CHALLENGER", "EVALUATION"] as const).map((st) => (
                    <button
                      key={st}
                      onClick={() => setStatusFilter(st)}
                      className={`px-2.5 py-0.5 rounded-md text-xs font-medium transition-all cursor-pointer ${
                        statusFilter === st
                          ? "bg-zinc-800 text-white font-semibold border border-white/[0.12]"
                          : "text-zinc-500 hover:text-zinc-300"
                      }`}
                    >
                      {st === "ALL" ? `Tümü (${models.length})` : st === "CHAMPION" ? "Şampiyon (1)" : st === "CHALLENGER" ? "Challenger" : "Değerlendirme"}
                    </button>
                  ))}
                </div>

                <span className="text-xs text-zinc-500 font-data">
                  {models[0]?.last_trained ? `Son Eğitim: ${new Date(models[0].last_trained).toLocaleDateString("tr-TR")}` : "Canlı Model Havuzu"}
                </span>
              </div>

              {modelsLoading && models.length === 0 && <SkeletonList count={3} />}

              {/* Model Kartları Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {filteredModels.map((model) => {
                  const isChamp = model.status === "CHAMPION";
                  return (
                    <div
                      key={model.id}
                      className="rounded-xl p-4 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-md space-y-3 hover:border-white/[0.15] transition-all relative overflow-hidden"
                    >
                      {/* Üst Satır */}
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2.5">
                          <div
                            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                            style={{ background: isChamp ? "rgba(16,185,129,0.12)" : "rgba(6,182,212,0.12)" }}
                          >
                            {isChamp ? <Award size={16} className="text-emerald-400" /> : <Cpu size={16} className="text-cyan-400" />}
                          </div>
                          <div>
                            <div className="flex items-center gap-1.5">
                              <h3 className="text-sm font-bold text-white">{model.name}</h3>
                              <span className="text-xs font-mono px-1.5 py-0.2 rounded bg-zinc-950 border border-white/[0.08] text-zinc-400">
                                {model.version}
                              </span>
                            </div>
                            <p className="text-xs text-zinc-400">{model.role} · {model.type}</p>
                          </div>
                        </div>

                        <span
                          className={`text-xs font-bold px-2 py-0.5 rounded-full shrink-0 ${
                            isChamp
                              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                              : model.status === "CHALLENGER"
                              ? "bg-cyan-500/10 text-cyan-300 border border-cyan-500/30"
                              : "bg-purple-500/10 text-purple-300 border border-purple-500/30"
                          }`}
                        >
                          {isChamp ? "🏆 ŞAMPİYON" : model.status === "CHALLENGER" ? "CHALLENGER" : "EVALUATION"}
                        </span>
                      </div>

                      {/* 4 Metrik Kutusu */}
                      <div className="grid grid-cols-4 gap-1.5 text-xs font-data">
                        <div className="p-2 rounded-lg bg-zinc-950/60 border border-white/[0.04]">
                          <span className="text-xs uppercase tracking-wider text-zinc-500 block">Bilgi (IC)</span>
                          <span className="text-xs font-extrabold text-emerald-400">
                            {model.metrics?.ic >= 0 ? "+" : ""}{model.metrics?.ic.toFixed(3)}
                          </span>
                        </div>
                        <div className="p-2 rounded-lg bg-zinc-950/60 border border-white/[0.04]">
                          <span className="text-xs uppercase tracking-wider text-zinc-500 block">R² Oranı</span>
                          <span className="text-xs font-extrabold text-cyan-400">
                            %{((model.metrics?.r2 ?? 0) * 100).toFixed(1)}
                          </span>
                        </div>
                        <div className="p-2 rounded-lg bg-zinc-950/60 border border-white/[0.04]">
                          <span className="text-xs uppercase tracking-wider text-zinc-500 block">Sharpe</span>
                          <span className="text-xs font-extrabold text-white">
                            {model.metrics?.sharpe?.toFixed(2) ?? "1.00"}
                          </span>
                        </div>
                        <div className="p-2 rounded-lg bg-zinc-950/60 border border-white/[0.04]">
                          <span className="text-xs uppercase tracking-wider text-zinc-500 block">Gecikme</span>
                          <span className="text-xs font-extrabold text-amber-400">
                            {model.metrics?.latency_ms ?? 2.0} ms
                          </span>
                        </div>
                      </div>

                      {/* Alt Özet */}
                      <div className="flex items-center justify-between text-xs text-zinc-500 pt-1 border-t border-white/[0.04]">
                        <span>Öznitelik: <b className="text-zinc-300 font-data">{model.features_count} Faktör</b></span>
                        <span>Rejim: <b className="text-zinc-300 font-data">{model.regime || "Tüm Piyasa"}</b></span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ============================================================ */}
          {/* SEKME 2: ÖZNİTELİK ÖNEM DÜZEYLERİ (FEATURE IMPORTANCE) */}
          {/* ============================================================ */}
          {activeTab === "features" && (
            <div className="rounded-xl p-4 border border-white/[0.08] bg-zinc-900/40 backdrop-blur-xl shadow-lg space-y-3">
              <div className="flex items-center justify-between border-b border-white/[0.06] pb-2.5">
                <div className="flex items-center gap-2">
                  <Sliders size={15} className="text-cyan-400" />
                  <h2 className="text-xs font-bold text-white uppercase tracking-wider">
                    Şampiyon Model Öznitelik Ağırlıkları (İlk 15 Faktör)
                  </h2>
                </div>
                <span className="text-xs text-zinc-500">
                  LambdaMART Sıralama & Seçim Ağırlıkları
                </span>
              </div>

              {featLoading && features.length === 0 ? (
                <div className="py-8 text-center text-xs text-zinc-500">Öznitelik ağırlıkları yükleniyor...</div>
              ) : (
                <div className="space-y-2 pt-1">
                  {features.map((item, idx) => (
                    <div key={item.feature} className="space-y-1 group">
                      <div className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2">
                          <span className="w-4 text-xs font-mono text-zinc-500">#{idx + 1}</span>
                          <span className="font-data font-bold text-zinc-200 group-hover:text-cyan-400 transition-colors text-xs">
                            {item.feature}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 font-data text-xs">
                          <span className="text-zinc-400">Ağırlık: {item.importance.toFixed(4)}</span>
                          <span className="font-bold text-cyan-400 w-10 text-right">%{item.normalized_pct.toFixed(1)}</span>
                        </div>
                      </div>

                      {/* İlerleme Çubuğu */}
                      <div className="h-1.5 w-full rounded-full bg-zinc-950 border border-white/[0.05] overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{
                            width: `${item.normalized_pct}%`,
                            background: idx === 0 
                              ? "linear-gradient(90deg, #10b981, #06b6d4)" 
                              : idx < 4 
                              ? "linear-gradient(90deg, #06b6d4, #3b82f6)" 
                              : "linear-gradient(90deg, #6366f1, #8b5cf6)",
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="p-3 rounded-lg bg-zinc-950/60 border border-white/[0.06] text-xs text-zinc-400 flex items-start gap-2 mt-3">
                <ShieldCheck size={16} className="text-emerald-400 shrink-0 mt-0.5" />
                <p>
                  <b>Sıfır Veri Sızıntısı Prensibi:</b> Tüm öznitelikler (t-1) kapanış barlarıyla hesaplanır. Purged & Embargo (5G) çapraz doğrulama ile test edilmiştir.
                </p>
              </div>
            </div>
          )}

          {/* ============================================================ */}
          {/* SEKME 3: PERFORMANS KARŞILAŞTIRMA MATRİSİ */}
          {/* ============================================================ */}
          {activeTab === "matrix" && (
            <div className="rounded-xl border border-white/[0.08] overflow-hidden bg-zinc-900/40 backdrop-blur-xl shadow-lg">
              <div className="p-3 border-b border-white/[0.06] bg-white/[0.01] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <BarChart2 size={15} className="text-purple-400" />
                  <h2 className="text-xs font-bold text-white uppercase tracking-wider">
                    Model Kıyaslama Matrisi (Benchmark)
                  </h2>
                </div>
                <span className="text-xs text-zinc-500">Walk-Forward CV Sonuçları</span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.06] text-xs font-bold text-zinc-400 uppercase tracking-wider bg-white/[0.01]">
                      <th className="py-2.5 px-3">Model Adı</th>
                      <th className="py-2.5 px-2">Statü</th>
                      <th className="py-2.5 px-2 text-right">Sharpe</th>
                      <th className="py-2.5 px-2 text-right">IC</th>
                      <th className="py-2.5 px-2 text-right">R²</th>
                      <th className="py-2.5 px-2 text-right">Gecikme</th>
                      <th className="py-2.5 px-3">Rol</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04] font-data">
                    {models.map((m) => {
                      const isChamp = m.status === "CHAMPION";
                      return (
                        <tr key={m.id} className="hover:bg-white/[0.02] transition-colors">
                          <td className="py-2.5 px-3 font-bold text-white flex items-center gap-1.5">
                            {isChamp && <Award size={13} className="text-emerald-400 shrink-0" />}
                            <span>{m.name}</span>
                            <span className="text-xs font-mono px-1 py-0.2 rounded bg-zinc-800 text-zinc-400">
                              {m.version}
                            </span>
                          </td>
                          <td className="py-2.5 px-2">
                            <span className={`text-xs font-bold px-1.5 py-0.2 rounded-full ${
                              isChamp ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-cyan-500/10 text-cyan-300"
                            }`}>
                              {m.status}
                            </span>
                          </td>
                          <td className="py-2.5 px-2 text-right font-extrabold text-white">
                            {m.metrics?.sharpe?.toFixed(2) ?? "1.00"}
                          </td>
                          <td className="py-2.5 px-2 text-right font-semibold text-emerald-400">
                            +{m.metrics?.ic?.toFixed(3) ?? "0.010"}
                          </td>
                          <td className="py-2.5 px-2 text-right text-cyan-400">
                            %{((m.metrics?.r2 ?? 0) * 100).toFixed(1)}
                          </td>
                          <td className="py-2.5 px-2 text-right text-amber-400">
                            {m.metrics?.latency_ms ?? 2.0} ms
                          </td>
                          <td className="py-2.5 px-3 text-zinc-400 font-sans text-xs">
                            {m.role}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

        </div>
      </div>
    </ErrorBoundary>
  );
}
