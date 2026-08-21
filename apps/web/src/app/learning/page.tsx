"use client";

import { useState } from "react";
import {
  Activity, RefreshCw, Zap, TrendingUp, AlertTriangle, CheckCircle2,
  Cpu, Layers, BarChart2
} from "lucide-react";

export default function LearningLabPage() {
  const [training, setTraining] = useState(false);

  return (
    <div className="p-5 space-y-5 fade-in min-h-screen" style={{ background: "var(--color-bg-primary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold gradient-text">Öğrenme & Adaptasyon Laboratuvarı</h1>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--color-text-muted)" }}>
            Online Model Drift Takibi · Otomatik Yeniden Eğitim (Retraining) · Veri Dağılım Sapması (PSI)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setTraining(true); setTimeout(() => setTraining(false), 800); }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20 cursor-pointer"
          >
            <RefreshCw size={13} className={training ? "animate-spin" : ""} />
            {training ? "Yeniden Eğitiliyor..." : "Drift Kontrolü & Retrain"}
          </button>
        </div>
      </div>

      {/* Summary Drift Cards */}
      <div className="grid grid-cols-4 gap-3">
        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #00e5a030" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500">Konsept Kayması (Concept Drift)</p>
          <p className="text-2xl font-bold font-data text-emerald-400">%2.1 (Stabil)</p>
          <p className="text-[10px] text-zinc-500">Kritik Eşik: %15.0</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #00c8ff30" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500">Öznitelik Kayması (PSI Skoru)</p>
          <p className="text-2xl font-bold font-data text-cyan-400">0.042 (Düşük)</p>
          <p className="text-[10px] text-zinc-500">Normal Aralık: &lt; 0.10</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #ffaa0030" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500">Son Eğitim Döngüsü</p>
          <p className="text-2xl font-bold font-data text-amber-400">3 Saat Önce</p>
          <p className="text-[10px] text-zinc-500">Batch Periyodu: 6 Saat</p>
        </div>

        <div
          className="rounded-xl p-4 space-y-1.5"
          style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)", borderTop: "1px solid #9966ff30" }}
        >
          <p className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500">Model Doğruluk Skoru</p>
          <p className="text-2xl font-bold font-data text-purple-400">%89.4</p>
          <p className="text-[10px] text-zinc-500">Son 30 Günlük Out-of-Sample</p>
        </div>
      </div>

      {/* Retraining Pipeline Status */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}
      >
        <div className="px-5 py-3 border-b border-zinc-800/40 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Cpu size={14} className="text-emerald-400" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-200">
              Sürekli Öğrenme ve Model Güncelleme Boru Hattı (Continuous Training)
            </h2>
          </div>
          <span className="text-[10px] font-bold text-emerald-400 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
            BORU HATTI AKTİF
          </span>
        </div>

        <div className="p-5 space-y-4">
          {[
            { step: "1. Veri Hazırlığı & Öznitelik Mühendisliği", desc: "ClickHouse üzerinden son 252 günlük 148 adet teknik ve makro indikatör çıkarıldı.", status: "Tamamlandı", time: "14:02" },
            { step: "2. Veri Doğrulama & Drift Kontrolü", desc: "Population Stability Index (PSI) testi çalıştırıldı. Anlamlı sapma tespit edilmedi.", status: "Tamamlandı", time: "14:05" },
            { step: "3. Hyperparameter Fine-Tuning & Eğitim", desc: "Optuna ile LightGBM ve CatBoost modelleri 5-fold cross validation ile optimize edildi.", status: "Tamamlandı", time: "14:18" },
            { step: "4. Backtest Doğrulama & Shadow Deployment", desc: "Yeni model gölge modda canlı piyasa verisiyle test ediliyor.", status: "Aktif Test", time: "14:25" },
          ].map((item, idx) => (
            <div key={idx} className="flex items-start justify-between p-3 rounded-lg bg-zinc-900/60 border border-zinc-800/40">
              <div className="flex items-start gap-3">
                <CheckCircle2 size={16} className="text-emerald-400 mt-0.5 flex-shrink-0" />
                <div>
                  <h4 className="text-xs font-bold text-zinc-200">{item.step}</h4>
                  <p className="text-[11px] text-zinc-500 mt-0.5">{item.desc}</p>
                </div>
              </div>
              <div className="text-right">
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">{item.status}</span>
                <span className="text-[9px] font-data text-zinc-600 block mt-1">{item.time}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
