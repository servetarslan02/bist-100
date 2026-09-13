"""
ALPHA BIST -- Strategy Diagnostician (Oez-Ogrenme ve Parametre Iyilestirme Motoru)

Kapali Geri Bildirim Dongusu:
  Tamamlanan Islemler -> Kayip Pattern Analizi -> Parametre Duzeltmesi -> FrozenParams Guncelleme

Bu modul sistemin "hatalardan ders cikarma" motorudur.
ML modelleri sinyal tahmini ogrenir; bu modul STRATEJI PARAMETRELERINI ogrenir.

Tespit ettigi sorunlar ve otomatik uyguladigi duzeltmeler:
  1. Hard stop cikisi cok fazla        -> hard_stop_pct genislet
  2. ATR trailing erkenden kapatti     -> trailing_atr_mult artir
  3. Max hold siniri erken kesti       -> max_hold_days uzat
  4. Win rate dustu                    -> min_score esiklerini sikistir
  5. BEAR rejimde sistematik kayip     -> o rejim icin min_score artir
  6. Kisa tutma suresi komisyon yuttu  -> min_hold_days artir

Guvenlik Sinirlari:
  - Her parametre icin alt ve ust sinir
  - Bir gunde max %20 parametre degisimi
  - En az 15 tamamlanmis islem olmadan parametre degistirmez
  - Her degisikligi DuckDB ye yazar, tam denetim izi
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import duckdb
import orjson
import structlog

logger = structlog.get_logger(__name__)

__all__ = ["StrategyDiagnostician", "strategy_diagnostician"]

# ============================================================
# PARAMETRE GUVENLI SINIRLAR
# Bu sinirlar disina asla cikilmaz
# ============================================================
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "hard_stop_pct":       (-14.0, -4.0),
    "trailing_atr_mult":   (1.5,   5.0),
    "min_atr_pct":         (2.0,   9.0),
    "min_hold_days":       (8,     35),
    "max_hold_days":       (40,    120),
    "min_score_BULL":      (0.05,  0.28),
    "min_score_BEAR":      (0.15,  0.45),
    "min_score_SIDEWAYS":  (0.10,  0.38),
    "min_score_HIGHVOL":   (0.12,  0.42),
    "min_score_LOWVOL":    (0.05,  0.28),
    "max_alloc_pct":       (0.08,  0.25),
    "min_cash_buffer_pct": (0.05,  0.50),
    "take_profit_rr_mult": (1.5,   4.5),
}

MAX_SINGLE_STEP_CHANGE: float = 0.20   # Bir gunde max %20 degisim
MIN_TRADES_REQUIRED: int = 15          # Bu kadar islem olmadan degistirme
LOOKBACK_TRADES: int = 50             # Son kac isleme bakilacak
HARD_STOP_RATIO_THRESHOLD: float = 0.38  # Hard stop cikis orani esigi
WIN_RATE_LOW_THRESHOLD: float = 0.30     # Win rate kritik alt esigi
SHORT_HOLD_CHURN_THRESHOLD: float = 0.38 # Kisa tutma orani esigi
GIVEBACK_THRESHOLD: float = 0.45         # Zirve kar erimesi esigi


class StrategyDiagnostician:
    """Tamamlanan islemleri analiz edip strateji parametrelerini otomatik iyilestiren motor.

    Her gunluk dongude run_daily_diagnosis() cagirilir.
    Tespit edilen sorunlar FROZEN_PARAMS a yansitilir.
    Tum degisiklikler DuckDB audit tablosuna yazilir.

    Attributes:
        db_path: Audit ve parametre gecmisinin saklandigi DuckDB dosya yolu.
    """

    def __init__(self, db_path: str = "data/strategy_diagnosis.duckdb") -> None:
        """Diagnostician motorunu ilklendirir ve DuckDB semasini hazirlar.

        Args:
            db_path: Audit ve parametre gecmisinin saklanacagi DuckDB dosyasi.
        """
        self.db_path = db_path
        self._mem_conn: duckdb.DuckDBPyConnection | None = None
        if self.db_path == ":memory:":
            self._mem_conn = duckdb.connect(":memory:")
        else:
            dir_name = os.path.dirname(self.db_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
        self._init_db()

    def __repr__(self) -> str:
        """Sinifin metinsel temsilini dondurur."""
        return f"StrategyDiagnostician(db={self.db_path!r})"

    def _ensure_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Tablo şemalarının eksiksiz mevcut olduğunu doğrular."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS diagnosis_log (
                id              INTEGER,
                diagnosis_date  VARCHAR NOT NULL,
                param_name      VARCHAR NOT NULL,
                old_value       DOUBLE NOT NULL,
                new_value       DOUBLE NOT NULL,
                reason          VARCHAR NOT NULL,
                metric_value    DOUBLE,
                trade_count     INTEGER,
                created_at      VARCHAR NOT NULL
            );
            CREATE TABLE IF NOT EXISTS current_params (
                param_name   VARCHAR PRIMARY KEY,
                param_value  DOUBLE NOT NULL,
                updated_at   VARCHAR NOT NULL,
                update_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS diagnosis_summary (
                summary_date      VARCHAR NOT NULL,
                total_trades      INTEGER,
                win_rate          DOUBLE,
                hard_stop_ratio   DOUBLE,
                avg_hold_days     DOUBLE,
                short_hold_ratio  DOUBLE,
                changes_made      INTEGER,
                created_at        VARCHAR NOT NULL
            );
            CREATE TABLE IF NOT EXISTS param_checkpoints (
                checkpoint_id   VARCHAR PRIMARY KEY,
                created_at      VARCHAR NOT NULL,
                total_trades    INTEGER,
                win_rate        DOUBLE,
                avg_pnl         DOUBLE,
                sharpe_proxy    DOUBLE,
                is_best         BOOLEAN DEFAULT FALSE,
                params_json     VARCHAR NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sector_diagnostics (
                diagnosis_date  VARCHAR NOT NULL,
                sector          VARCHAR NOT NULL,
                trades_count    INTEGER,
                win_rate        DOUBLE,
                total_pnl       DOUBLE,
                is_quarantined  BOOLEAN DEFAULT FALSE,
                created_at      VARCHAR NOT NULL
            );
            CREATE TABLE IF NOT EXISTS what_if_simulations (
                sim_date        VARCHAR NOT NULL,
                param_name      VARCHAR NOT NULL,
                old_value       DOUBLE NOT NULL,
                candidate_value DOUBLE NOT NULL,
                old_sim_pnl     DOUBLE NOT NULL,
                new_sim_pnl     DOUBLE NOT NULL,
                approved        BOOLEAN NOT NULL,
                reason          VARCHAR NOT NULL,
                created_at      VARCHAR NOT NULL
            );
        """)

    def _init_db(self) -> None:
        """DuckDB audit ve parametre gecmisi tablolarini olusturur."""
        try:
            conn = self._get_conn()
            self._ensure_schema(conn)
            if conn != self._mem_conn:
                conn.close()
            logger.info("StrategyDiagnostician DB hazir", db=self.db_path)
        except Exception as exc:
            logger.warning("Diagnosis DB acilamadi, bellek moduna geciliyor", hata=str(exc))
            if self._mem_conn is None:
                self._mem_conn = duckdb.connect(":memory:")
                self._ensure_schema(self._mem_conn)

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        """Thread-safe DuckDB baglantisi dondurur."""
        if self.db_path == ":memory:":
            if self._mem_conn is None:
                self._mem_conn = duckdb.connect(":memory:")
                self._ensure_schema(self._mem_conn)
            return self._mem_conn
        try:
            conn = duckdb.connect(self.db_path)
            self._ensure_schema(conn)
            return conn
        except Exception:
            try:
                # Eger dosya kilitliyse salt-okunur modda ac
                return duckdb.connect(self.db_path, read_only=True)
            except Exception:
                if self._mem_conn is None:
                    self._mem_conn = duckdb.connect(":memory:")
                    self._ensure_schema(self._mem_conn)
                return self._mem_conn

    # ============================================================
    # ANA GIRIS NOKTASI
    # ============================================================

    def run_daily_diagnosis(
        self,
        trades: list[dict[str, Any]],
        current_params: dict[str, Any],
        equity_curve: list[dict[str, Any]] | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        """Gunluk teshis dongusunu calistirip parametre onerileri uretir.

        Bu metot gunluk pipeline dongusunde otomatik cagrilmalidir.
        Tamamlanan islemlerdeki sistematik hatalari tespit eder ve
        FROZEN_PARAMS uzerinde guvenli sinirlar dahilinde duzeltmeler yapar.

        Args:
            trades: Tamamlanmis islem kayitlari listesi.
            current_params: Mevcut FROZEN_PARAMS sozlugu.
            equity_curve: Equity egrisi (isteğe bagli).
            date: Teshis tarihi (varsayilan: bugun).

        Returns:
            Yapilan degisiklikler ve teshis ozeti sozlugu.
        """
        diagnosis_date = date or datetime.now(UTC).strftime("%Y-%m-%d")

        if len(trades) < MIN_TRADES_REQUIRED:
            logger.info(
                "Teshis atlandir -- yeterli islem yok",
                trade_count=len(trades),
                min_required=MIN_TRADES_REQUIRED,
            )
            return {"status": "SKIPPED", "reason": f"Yetersiz islem ({len(trades)}/{MIN_TRADES_REQUIRED})", "changes": []}

        recent = trades[-LOOKBACK_TRADES:]
        metrics = self._compute_metrics(recent, current_params)

        logger.info(
            "Strateji teshisi basladi",
            date=diagnosis_date,
            trade_count=len(recent),
            win_rate=round(metrics.get("win_rate", 0), 3),
            hard_stop_ratio=round(metrics.get("hard_stop_ratio", 0), 3),
            avg_hold_days=round(metrics.get("avg_hold_days", 0), 1),
        )

        # 1. KONTROL: KRİTİK PERFORMANS DÜŞÜŞÜNDE OTOMATİK ROLLBACK
        rollback_applied = self._check_and_apply_rollback(metrics, current_params, diagnosis_date)
        if rollback_applied:
            return {
                "status": "ROLLBACK_APPLIED",
                "date": diagnosis_date,
                "metrics": metrics,
                "changes": [{"param": "ROLLBACK", "old": "CURRENT", "new": "BEST_CHECKPOINT"}],
                "change_count": 1,
            }

        # 2. SEKTÖREL PERFORMANS & MODEL KÖRLÜĞÜ ANALİZİ
        sector_results = self._diagnose_sectors(recent, diagnosis_date)

        changes: list[dict[str, Any]] = []
        changes.extend(self._diagnose_hard_stop(metrics, current_params))
        changes.extend(self._diagnose_trailing_exit(metrics, current_params))
        changes.extend(self._diagnose_max_hold(metrics, current_params))
        changes.extend(self._diagnose_win_rate(metrics, current_params))
        changes.extend(self._diagnose_churn(metrics, current_params))
        changes.extend(self._diagnose_regime_loss(metrics, current_params))
        changes.extend(self._diagnose_giveback(metrics, current_params))
        changes.extend(self._diagnose_position_sizing(metrics, current_params))
        changes.extend(self._diagnose_cash_buffer(metrics, current_params))

        # 3. ADAY PARAMETRE DEĞİŞİKLİKLERİ & WHAT-IF MİKRO-SİMÜLASYONU
        applied: list[dict[str, Any]] = []
        for ch in changes:
            result = self._apply_safe_change(ch, current_params, diagnosis_date, len(recent), recent_trades=recent)
            if result:
                applied.append(result)

        self._save_summary(diagnosis_date, metrics, len(applied))
        # 4. CHECKPOINT KAYDI
        self._save_checkpoint(diagnosis_date, metrics, current_params)

        if applied:
            logger.info(
                "Strateji parametreleri otomatik guncellendi (What-If onayli)",
                degisiklik_sayisi=len(applied),
                degisiklikler=[f"{c['param']}: {c['old']}-->{c['new']}" for c in applied],
            )
        else:
            logger.info("Teshis tamamlandi -- parametre degisikligi gerekmedi veya What-If reddetti", date=diagnosis_date)

        return {
            "status": "OK",
            "date": diagnosis_date,
            "metrics": metrics,
            "changes": applied,
            "change_count": len(applied),
            "sector_report": sector_results,
        }

    def run_daily_check(
        self,
        trades: list[dict[str, Any]],
        current_params: dict[str, Any],
        equity_curve: list[dict[str, Any]] | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        """run_daily_diagnosis için takma ad (alias)."""
        return self.run_daily_diagnosis(trades=trades, current_params=current_params, equity_curve=equity_curve, date=date)

    # ============================================================
    # METRIK HESAPLAMA
    # ============================================================

    def _compute_metrics(self, trades: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
        """Son islemlerden teshis metriklerini hesaplar.

        Args:
            trades: Islem kayitlari listesi.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Teshis metrik sozlugu.
        """
        n = len(trades)
        if n == 0:
            return {}

        wins = sum(1 for t in trades if self._pnl(t) > 0)
        win_rate = wins / n

        exit_reasons: dict[str, int] = {}
        for t in trades:
            reason = (t.get("exit_reason") or t.get("close_reason") or "UNKNOWN").upper()
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        hard_stop_count = sum(
            v for k, v in exit_reasons.items()
            if any(x in k for x in ("HARD", "STOP", "SL", "HARD_STOP"))
        )
        trail_count = sum(
            v for k, v in exit_reasons.items()
            if any(x in k for x in ("TRAIL", "ATR", "TRAILING"))
        )
        max_hold_count = sum(
            v for k, v in exit_reasons.items()
            if any(x in k for x in ("MAX_HOLD", "TIME", "EXPIRE", "TIMEOUT"))
        )

        hard_stop_ratio = hard_stop_count / n
        trail_exit_ratio = trail_count / n
        max_hold_exit_ratio = max_hold_count / n

        hold_days_list: list[float] = []
        for t in trades:
            hd = t.get("hold_days") or t.get("holding_days") or t.get("days_held")
            if hd is None:
                et = str(t.get("entry_time") or t.get("entry_date", ""))[:10]
                xt = str(t.get("exit_time") or t.get("exit_date", ""))[:10]
                if len(et) == 10 and len(xt) == 10:
                    try:
                        hd = (datetime.fromisoformat(xt) - datetime.fromisoformat(et)).days
                    except Exception:
                        hd = None
            if hd is not None and float(hd) >= 0:
                hold_days_list.append(float(hd))

        avg_hold_days = sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0.0
        min_hold_param = float(params.get("min_hold_days", 12))
        short_hold_ratio = (
            sum(1 for h in hold_days_list if h < min_hold_param) / len(hold_days_list)
            if hold_days_list else 0.0
        )

        # ATR trail sonrasi hisse devam etti mi?
        trail_trades = [t for t in trades if (t.get("exit_reason") or "").upper() in ("ATR_TRAIL", "TRAILING", "TRAIL")]
        avg_post_trail_gain = (
            sum(t.get("post_exit_return_pct", 0.0) for t in trail_trades) / len(trail_trades)
            if trail_trades else 0.0
        )

        # Rejim bazli win rate
        regime_counts: dict[str, int] = {}
        regime_wins: dict[str, int] = {}
        for t in trades:
            r = (t.get("market_regime") or t.get("regime") or "UNKNOWN").upper()
            regime_counts[r] = regime_counts.get(r, 0) + 1
            if self._pnl(t) > 0:
                regime_wins[r] = regime_wins.get(r, 0) + 1
        regime_win_rates = {r: regime_wins.get(r, 0) / c for r, c in regime_counts.items()}

        # Kâr geri verme (Profit giveback) oranı: Zirvede görülen kâr ile realize kâr farkı
        giveback_ratios: list[float] = []
        for t in trades:
            realized = self._pnl(t)
            peak = float(t.get("peak_pnl") or t.get("max_favorable_excursion") or t.get("peak_return_pct") or 0.0)
            if peak > 1.0:
                peak = peak / 100.0
            if peak > 0.03:  # En az %3 kâr görmüş işlemler
                giveback = max(0.0, (peak - realized) / peak)
                giveback_ratios.append(giveback)
        avg_giveback_ratio = sum(giveback_ratios) / len(giveback_ratios) if giveback_ratios else 0.0

        # Ardışık zarar serisi (Consecutive losses)
        consec_losses = 0
        for t in reversed(trades):
            if self._pnl(t) < 0:
                consec_losses += 1
            else:
                break

        avg_pnl = sum(self._pnl(t) for t in trades) / n if n > 0 else 0.0

        return {
            "n": n,
            "win_rate": win_rate,
            "hard_stop_ratio": hard_stop_ratio,
            "hard_stop_count": hard_stop_count,
            "trail_exit_ratio": trail_exit_ratio,
            "max_hold_exit_ratio": max_hold_exit_ratio,
            "avg_hold_days": avg_hold_days,
            "short_hold_ratio": short_hold_ratio,
            "exit_reasons": exit_reasons,
            "avg_post_trail_gain": avg_post_trail_gain,
            "regime_win_rates": regime_win_rates,
            "regime_counts": regime_counts,
            "avg_giveback_ratio": avg_giveback_ratio,
            "consecutive_losses": consec_losses,
            "avg_pnl": avg_pnl,
        }

    @staticmethod
    def _pnl(trade: dict[str, Any]) -> float:
        """Islemden realize edilen PnL i dondurur."""
        for key in ("realized_pnl", "pnl", "profit_loss", "return_pct"):
            v = trade.get(key)
            if v is not None:
                return float(v)
        ep = trade.get("entry_price", 0)
        xp = trade.get("exit_price", 0)
        if ep and xp and float(ep) > 0:
            return (float(xp) - float(ep)) / float(ep)
        return 0.0

    # ============================================================
    # TESHIS KURALLARI
    # ============================================================

    def _diagnose_hard_stop(self, metrics: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
        """Hard stop cikisi orani cok yuksekse stop-loss u genislet.

        Args:
            metrics: Hesaplanan teshis metrikleri.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Onerilen parametre degisikligi listesi.
        """
        ratio = metrics.get("hard_stop_ratio", 0.0)
        if ratio < HARD_STOP_RATIO_THRESHOLD:
            return []
        current = float(params.get("hard_stop_pct", -6.5))
        new_val = current * (1.0 + 0.10)   # daha negatif = genislet
        return [{"param": "hard_stop_pct", "old": current, "new": new_val,
                 "reason": f"Hard stop cikis orani %{ratio*100:.1f} > esik -- stop genisletildi",
                 "metric": ratio}]

    def _diagnose_trailing_exit(self, metrics: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
        """ATR trailing erkenden kapatti, hisse devam ettiyse mult artir.

        Args:
            metrics: Hesaplanan teshis metrikleri.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Onerilen parametre degisikligi listesi.
        """
        post_gain = metrics.get("avg_post_trail_gain", 0.0)
        trail_ratio = metrics.get("trail_exit_ratio", 0.0)
        if trail_ratio < 0.10 or post_gain < 0.02:
            return []
        current = float(params.get("trailing_atr_mult", 2.5))
        new_val = current * 1.10
        return [{"param": "trailing_atr_mult", "old": current, "new": new_val,
                 "reason": f"ATR trail sonrasi ort +%{post_gain*100:.1f} kalan getiri -- mult artirildi",
                 "metric": post_gain}]

    def _diagnose_max_hold(self, metrics: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
        """Max hold siniri sik tetikleniyorsa tutma suresini uzat.

        Args:
            metrics: Hesaplanan teshis metrikleri.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Onerilen parametre degisikligi listesi.
        """
        ratio = metrics.get("max_hold_exit_ratio", 0.0)
        if ratio < 0.25:
            return []
        current = float(params.get("max_hold_days", 65))
        new_val = current * 1.10
        return [{"param": "max_hold_days", "old": current, "new": new_val,
                 "reason": f"Max hold cikis orani %{ratio*100:.1f} -- kazananlar daha uzun tutulacak",
                 "metric": ratio}]

    def _diagnose_win_rate(self, metrics: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
        """Win rate kritik esigin altina dustuyse giris kalitesini yukalt.

        Args:
            metrics: Hesaplanan teshis metrikleri.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Onerilen parametre degisikligi listesi.
        """
        win_rate = metrics.get("win_rate", 1.0)
        if win_rate >= WIN_RATE_LOW_THRESHOLD:
            return []
        changes = []
        for regime, score in (params.get("min_score") or {}).items():
            r_short = regime.replace("_TREND", "").replace("_MARKET", "").replace("_RANGE", "").replace("_VOLATILITY", "")
            changes.append({"param": f"min_score_{r_short}", "regime": regime,
                            "old": float(score), "new": float(score) * 1.15,
                            "reason": f"Win rate %{win_rate*100:.1f} < esik -- giris kalitesi artirildi",
                            "metric": win_rate})
        return changes

    def _diagnose_churn(self, metrics: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
        """Kisa tutma suresi komisyon yutuyorsa min_hold_days artir.

        Args:
            metrics: Hesaplanan teshis metrikleri.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Onerilen parametre degisikligi listesi.
        """
        short_ratio = metrics.get("short_hold_ratio", 0.0)
        if short_ratio < SHORT_HOLD_CHURN_THRESHOLD:
            return []
        current = float(params.get("min_hold_days", 12))
        new_val = current * 1.15
        return [{"param": "min_hold_days", "old": current, "new": new_val,
                 "reason": f"Islemlerin %{short_ratio*100:.1f} i min_hold altinda -- churn azaltildi",
                 "metric": short_ratio}]

    def _diagnose_regime_loss(self, metrics: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
        """Belirli bir rejimde sistematik kayip varsa o rejim min_score unu sikistir.

        Args:
            metrics: Hesaplanan teshis metrikleri.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Onerilen parametre degisikligi listesi.
        """
        regime_win_rates = metrics.get("regime_win_rates", {})
        regime_counts = metrics.get("regime_counts", {})
        MAP = {"BULL_TREND": "BULL", "BEAR_MARKET": "BEAR", "SIDEWAYS_RANGE": "SIDEWAYS",
               "HIGH_VOLATILITY": "HIGHVOL", "LOW_VOLATILITY": "LOWVOL"}
        changes = []
        for regime, wr in regime_win_rates.items():
            if regime_counts.get(regime, 0) < 8 or wr >= 0.35:
                continue
            short_key = MAP.get(regime, regime.split("_")[0])
            min_scores = params.get("min_score") or {}
            current = float(min_scores.get(regime, 0.15))
            changes.append({"param": f"min_score_{short_key}", "regime": regime,
                            "old": current, "new": current * 1.20,
                            "reason": f"Rejim {regime}: win rate %{wr*100:.1f} ({regime_counts.get(regime,0)} islem) -- giris esigi sikistirildi",
                            "metric": wr})
        return changes

    def _diagnose_giveback(self, metrics: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
        """Kârda olan işlemlerin zirveden büyük geri çekilme yaşaması durumunda trailing stop veya TP çarpanını sıkılaştır.

        Args:
            metrics: Hesaplanan teshis metrikleri.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Onerilen parametre degisikligi listesi.
        """
        gb = metrics.get("avg_giveback_ratio", 0.0)
        if gb < GIVEBACK_THRESHOLD:
            return []
        changes = []
        current_trail = float(params.get("trailing_atr_mult", 2.5))
        new_trail = current_trail * 0.90  # %10 daralt
        changes.append({
            "param": "trailing_atr_mult",
            "old": current_trail,
            "new": new_trail,
            "reason": f"Ortalama kar geri verme orani %{gb*100:.1f} > %{GIVEBACK_THRESHOLD*100:.0f} -- trailing stop sikilastirildi",
            "metric": gb,
        })
        current_tp = float(params.get("take_profit_rr_mult", 2.5))
        new_tp = current_tp * 0.90
        changes.append({
            "param": "take_profit_rr_mult",
            "old": current_tp,
            "new": new_tp,
            "reason": f"Zirve kar erimesi %{gb*100:.1f} -- hedef kar alma carpani sikilastirildi",
            "metric": gb,
        })
        return changes

    def _diagnose_position_sizing(self, metrics: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
        """Arka arkaya zararlar veya rejim riski anında tek hisse pozisyon tavanını küçült, başarı anında genişlet.

        Args:
            metrics: Hesaplanan teshis metrikleri.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Onerilen parametre degisikligi listesi.
        """
        consec_losses = metrics.get("consecutive_losses", 0)
        win_rate = metrics.get("win_rate", 0.5)
        current_alloc = float(params.get("max_alloc_pct", 0.20))

        # Defansif daralma
        if consec_losses >= 3 or win_rate < 0.32:
            new_alloc = current_alloc * 0.85  # %15 daralt
            return [{
                "param": "max_alloc_pct",
                "old": current_alloc,
                "new": new_alloc,
                "reason": f"Ardisik zarar: {consec_losses}, Win rate: %{win_rate*100:.1f} -- tek hisse pozisyon tavani kucultuldu",
                "metric": float(consec_losses),
            }]
        # Ofansif genişleme
        elif win_rate >= 0.58 and metrics.get("avg_pnl", 0.0) > 0.02 and current_alloc < 0.20:
            new_alloc = current_alloc * 1.15  # %15 artır
            return [{
                "param": "max_alloc_pct",
                "old": current_alloc,
                "new": new_alloc,
                "reason": f"Guclu performans: Win rate %{win_rate*100:.1f}, Avg PnL %{metrics.get('avg_pnl',0)*100:.1f} -- pozisyon tavani genisletildi",
                "metric": win_rate,
            }]
        return []

    def _diagnose_cash_buffer(self, metrics: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
        """Kötü piyasa koşullarında asgari nakit tamponunu artırarak sermayeyi koru.

        Args:
            metrics: Hesaplanan teshis metrikleri.
            params: Mevcut FROZEN_PARAMS.

        Returns:
            Onerilen parametre degisikligi listesi.
        """
        win_rate = metrics.get("win_rate", 0.5)
        current_cash = float(params.get("min_cash_buffer_pct", 0.10))
        regime_counts = metrics.get("regime_counts", {})
        bear_ratio = regime_counts.get("BEAR_MARKET", 0) / max(1, metrics.get("n", 1))

        # Ayı piyasası veya düşük win rate durumunda nakit kalkanı yükseltilir
        if (bear_ratio > 0.40 or win_rate < 0.35) and current_cash < 0.35:
            new_cash = current_cash * 1.30  # Nakit tamponunu artır
            return [{
                "param": "min_cash_buffer_pct",
                "old": current_cash,
                "new": new_cash,
                "reason": f"Risk Korumasi: Ayi orani %{bear_ratio*100:.1f}, Win rate %{win_rate*100:.1f} -- nakit kalkani guclendirildi",
                "metric": win_rate,
            }]
        elif bear_ratio == 0 and win_rate >= 0.52 and current_cash > 0.10:
            new_cash = current_cash * 0.85  # Nakit tamponunu normale çek
            return [{
                "param": "min_cash_buffer_pct",
                "old": current_cash,
                "new": new_cash,
                "reason": f"Yuksek Guven: Piyasa pozitif, Win rate %{win_rate*100:.1f} -- nakit kalkani serbest birakildi",
                "metric": win_rate,
            }]
        return []

    # ============================================================
    # GUVENLI SINIR + WHAT-IF TESTI + UYGULAMA
    # ============================================================

    def _apply_safe_change(
        self,
        change: dict[str, Any],
        params: dict[str, Any],
        date: str,
        n_trades: int,
        recent_trades: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Parametre degisikligini guvenli sinirlar ve What-If mikro-simulasyonu icerisinde uygular.

        Args:
            change: Teshis kuralinin onerdigi degisiklik.
            params: Mevcut FROZEN_PARAMS (in-place guncellenir).
            date: Teshis tarihi.
            n_trades: Analiz edilen islem sayisi.
            recent_trades: Karsiolgusal mikro-simulasyon icin son islemler.

        Returns:
            Uygulanan degisiklik sozlugu veya None.
        """
        param = change["param"]
        old_val = float(change["old"])
        new_val = float(change["new"])

        # Guvenli sinir
        bounds = PARAM_BOUNDS.get(param)
        if bounds:
            new_val = max(bounds[0], min(bounds[1], new_val))
        elif param.startswith("min_score_"):
            # Rejim skor eşikleri asla 0.35 üzerine çıkamaz (İşlem felcini ve aşırı nakit tutmayı önler)
            new_val = max(0.05, min(0.35, new_val))

        # Max adim siniri
        if old_val != 0:
            max_step = abs(old_val) * MAX_SINGLE_STEP_CHANGE
            if abs(new_val - old_val) > max_step:
                direction = 1.0 if new_val > old_val else -1.0
                new_val = old_val + direction * max_step

        if abs(new_val - old_val) < 1e-5:
            return None

        # ------------------------------------------------------------
        # KARŞIOLGUSAL TEST (WHAT-IF MİKRO-SİMÜLATÖRÜ)
        # Değişiklik geriye dönük son işlemlerde test edilir.
        # Eğer zararı büyütüyorsa KESİNLİKLE REDDEDİLİR!
        # ------------------------------------------------------------
        what_if_res = None
        if recent_trades:
            what_if_res = self._run_what_if_simulation(change, params, recent_trades, date, candidate_val=new_val)
            if not what_if_res.get("approved", True):
                logger.warning(
                    "Parametre degisikligi What-If mikro-simulasyonunu gecemedi, REDDEDILDI",
                    param=param,
                    eski=round(old_val, 4),
                    aday=round(new_val, 4),
                    sebep=what_if_res.get("reason"),
                )
                return None

        # FROZEN_PARAMS guncelle (in-place)
        regime = change.get("regime")
        if regime and "min_score" in param:
            ms = params.get("min_score")
            if isinstance(ms, dict):
                matched = False
                for r_key in list(ms.keys()):
                    if r_key == regime or regime in r_key or r_key in regime:
                        ms[r_key] = round(new_val, 4)
                        matched = True
                if not matched:
                    ms[regime] = round(new_val, 4)
        elif param in params:
            params[param] = int(round(new_val)) if isinstance(params[param], int) else round(new_val, 4)

        self._log_change(date, param, old_val, new_val, change.get("reason", ""), change.get("metric"), n_trades)
        logger.warning(
            "Strateji parametresi otomatik degistirildi",
            param=param, eski=round(old_val, 4), yeni=round(new_val, 4),
            sebep=change.get("reason", ""),
        )
        return {
            "param": param,
            "old": round(old_val, 4),
            "new": round(new_val, 4),
            "reason": change.get("reason", ""),
            "what_if": what_if_res,
        }

    def _run_what_if_simulation(
        self,
        candidate_change: dict[str, Any],
        params: dict[str, Any],
        recent_trades: list[dict[str, Any]],
        date: str,
        candidate_val: float,
    ) -> dict[str, Any]:
        """Aday parametre değişikliğini son işlemler üzerinde geriye dönük mikro-simülasyonla test eder."""
        param = candidate_change["param"]
        old_val = float(candidate_change["old"])
        new_val = candidate_val

        actual_pnl = sum(self._pnl(t) for t in recent_trades)
        simulated_pnl = 0.0

        for t in recent_trades:
            orig_pnl = self._pnl(t)
            reason = str(t.get("exit_reason", "")).upper()

            if param == "hard_stop_pct":
                if any(x in reason for x in ("HARD", "STOP")):
                    post_ret = float(t.get("post_exit_return_pct", 0.0))
                    # Eğer hisse stop vurulduktan sonra yukarı döndüyse geniş stop kurtarır
                    if post_ret > abs(new_val - old_val):
                        sim_trade_pnl = orig_pnl + (post_ret / 100.0)
                    else:
                        # Düşüş sürdüyse daha geniş stop zararı büyütür
                        sim_trade_pnl = orig_pnl - (abs(new_val - old_val) / 100.0)
                else:
                    sim_trade_pnl = orig_pnl

            elif param == "trailing_atr_mult":
                if any(x in reason for x in ("TRAIL", "ATR")):
                    post_ret = float(t.get("post_exit_return_pct", 0.0))
                    if post_ret > 0:
                        sim_trade_pnl = orig_pnl + (post_ret * 0.5) / 100.0
                    else:
                        sim_trade_pnl = orig_pnl
                else:
                    sim_trade_pnl = orig_pnl

            elif param == "min_hold_days":
                hd = float(t.get("hold_days", t.get("days_held", 5)))
                if hd < new_val and orig_pnl < 0:
                    sim_trade_pnl = orig_pnl * 0.7  # Erken churn azaltması
                else:
                    sim_trade_pnl = orig_pnl

            elif "min_score" in param:
                score = float(t.get("score", t.get("entry_score", 0.0)))
                target_thresh = new_val if new_val > 1.0 else new_val * 100.0
                if 0 < score < target_thresh:
                    # Yeni baraj altında kalıp elenen işlem
                    sim_trade_pnl = 0.0 if orig_pnl < 0 else (orig_pnl * 0.5)
                else:
                    sim_trade_pnl = orig_pnl

            elif param == "max_alloc_pct":
                # Pozisyon boyutu tavanı değiştiğinde:
                # Yeni tavan daha düşükse (defansif daralma), zararlı işlemlerdeki sermaye riski küçülür
                alloc_ratio = new_val / max(0.01, old_val)
                if new_val < old_val:
                    # Defansif küçülmede kayıplar küçülür
                    sim_trade_pnl = orig_pnl * alloc_ratio if orig_pnl < 0 else orig_pnl * 0.95
                else:
                    sim_trade_pnl = orig_pnl * alloc_ratio

            elif param == "min_cash_buffer_pct":
                # Nakit kalkanı artırıldığında marjinal zayıf işlemler elenir
                score = float(t.get("score", t.get("entry_score", 50.0)))
                if new_val > old_val and score < 55.0 and orig_pnl < 0:
                    sim_trade_pnl = 0.0  # Nakit tamponu zararlı marjinal işlemi engelledi
                else:
                    sim_trade_pnl = orig_pnl

            elif param == "take_profit_rr_mult":
                # Hedef kâr çarpanı sıkılaştırıldığında kârın erimesi önlenir
                peak = float(t.get("peak_pnl") or t.get("max_favorable_excursion") or t.get("peak_return_pct") or 0.0)
                if peak > 1.0:
                    peak = peak / 100.0
                if peak > 0.04 and orig_pnl < (peak * 0.6):
                    sim_trade_pnl = peak * 0.75  # Zirveye yakın kâr realize edilmiş olurdu
                else:
                    sim_trade_pnl = orig_pnl
            else:
                sim_trade_pnl = orig_pnl

            simulated_pnl += sim_trade_pnl

        # Onay kriteri:
        # Defansif risk parametreleri (max_alloc_pct küçülmesi veya min_cash artışı) sermayeyi korumak içindir
        is_defensive_risk = (param == "max_alloc_pct" and new_val < old_val) or (param == "min_cash_buffer_pct" and new_val > old_val)
        if is_defensive_risk:
            # Defansif risk müdahalesinde zararlı işlemlerin etkisi hafifletildiği için onaylanır
            approved = True
        else:
            approved = simulated_pnl >= actual_pnl or (actual_pnl < 0 and simulated_pnl > actual_pnl)

        reason_text = (
            f"What-If mikro-simulasyonu basarili: Sim PnL {simulated_pnl:.2f} >= Mevcut {actual_pnl:.2f}"
            if approved
            else f"What-If mikro-simulasyonu REDDETTI: Zarar artiyor (Sim PnL: {simulated_pnl:.2f} < Mevcut: {actual_pnl:.2f})"
        )

        self._log_what_if(date, param, old_val, new_val, actual_pnl, simulated_pnl, approved, reason_text)
        return {
            "approved": approved,
            "actual_pnl": round(actual_pnl, 4),
            "simulated_pnl": round(simulated_pnl, 4),
            "reason": reason_text,
        }

    def _log_what_if(
        self, date: str, param: str, old: float, new: float, actual: float, sim: float, approved: bool, reason: str
    ) -> None:
        """What-If simülasyon sonucunu DuckDB'ye kaydeder."""
        conn = None
        try:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO what_if_simulations (sim_date, param_name, old_value, candidate_value, old_sim_pnl, new_sim_pnl, approved, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [date, param, old, new, actual, sim, approved, reason, datetime.now(UTC).isoformat()]
            )
        except Exception as exc:
            logger.warning("What-If sim kaydi basarisiz", hata=str(exc))
        finally:
            if conn is not None and conn != self._mem_conn:
                conn.close()

    def _diagnose_sectors(self, trades: list[dict[str, Any]], date: str) -> dict[str, Any]:
        """Sektörel performans ve model körlüğü teşhisi yapar."""
        try:
            from services.ingestion.bist_universe import bist_universe
            sector_map = getattr(bist_universe, "SECTOR_MAPPING", {})
        except Exception:
            sector_map = {}

        sector_stats: dict[str, dict[str, Any]] = {}
        for t in trades:
            tk = t.get("ticker", "")
            sec = t.get("sector") or sector_map.get(tk, "DIGER")
            if sec not in sector_stats:
                sector_stats[sec] = {"trades": 0, "wins": 0, "pnl": 0.0}
            sector_stats[sec]["trades"] += 1
            pnl = self._pnl(t)
            sector_stats[sec]["pnl"] += pnl
            if pnl > 0:
                sector_stats[sec]["wins"] += 1

        quarantined = []
        for sec, stat in sector_stats.items():
            cnt = stat["trades"]
            wr = stat["wins"] / cnt if cnt > 0 else 0.0
            is_quar = cnt >= 4 and wr < 0.25 and stat["pnl"] < 0
            if is_quar:
                quarantined.append(sec)
            self._log_sector(date, sec, cnt, wr, stat["pnl"], is_quar)

        if quarantined:
            logger.warning("Model korlugu / Sektor karantinasi tespit edildi", karantina_sektorler=quarantined)

        return {"sector_stats": sector_stats, "quarantined_sectors": quarantined}

    def _log_sector(self, date: str, sector: str, count: int, win_rate: float, pnl: float, is_quar: bool) -> None:
        """Sektörel teşhis kaydını DuckDB'ye yazar."""
        conn = None
        try:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO sector_diagnostics (diagnosis_date, sector, trades_count, win_rate, total_pnl, is_quarantined, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [date, sector, count, win_rate, pnl, is_quar, datetime.now(UTC).isoformat()]
            )
        except Exception as exc:
            logger.warning("Sektor log kaydi basarisiz", hata=str(exc))
        finally:
            if conn is not None and conn != self._mem_conn:
                conn.close()

    def _save_checkpoint(self, date: str, metrics: dict[str, Any], params: dict[str, Any]) -> None:
        """Mevcut parametre durumunu değerlendirme metriğiyle birlikte checkpoint olarak saklar."""
        wr = metrics.get("win_rate", 0.5)
        pnl = sum(self._pnl(t) for t in metrics.get("trades", [])) if "trades" in metrics else 0.0
        sharpe_proxy = (wr * 2.0 - 1.0)

        conn = None
        try:
            conn = self._get_conn()
            best_row = conn.execute("SELECT MAX(sharpe_proxy) FROM param_checkpoints").fetchone()
            max_sharpe = best_row[0] if best_row and best_row[0] is not None else -999.0
            is_best = sharpe_proxy > max_sharpe

            chk_id = f"chk_{date}_{int(datetime.now(UTC).timestamp())}"
            conn.execute(
                """
                INSERT INTO param_checkpoints (checkpoint_id, created_at, total_trades, win_rate, avg_pnl, sharpe_proxy, is_best, params_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [chk_id, date, metrics.get("n", 0), wr, pnl, sharpe_proxy, is_best, orjson.dumps(params).decode("utf-8")]
            )
        except Exception as exc:
            logger.warning("Checkpoint kaydedilemedi", hata=str(exc))
        finally:
            if conn is not None and conn != self._mem_conn:
                conn.close()

    def _check_and_apply_rollback(self, metrics: dict[str, Any], current_params: dict[str, Any], date: str) -> bool:
        """Performans kritik derecede bozulduysa en iyi bilinen checkpoint'e otomatik geri döner."""
        wr = metrics.get("win_rate", 1.0)
        n = metrics.get("n", 0)
        if wr < 0.20 and n >= 15:
            conn = None
            try:
                conn = self._get_conn()
                best_chk = conn.execute(
                    "SELECT checkpoint_id, params_json, win_rate, sharpe_proxy FROM param_checkpoints WHERE is_best = TRUE ORDER BY sharpe_proxy DESC LIMIT 1"
                ).fetchone()
                if best_chk:
                    best_id, p_json, best_wr, _ = best_chk
                    if best_wr > wr + 0.15:
                        restored = orjson.loads(p_json)
                        for k, v in restored.items():
                            current_params[k] = v
                        logger.critical(
                            "OTOMATIK GERI ALMA (ROLLBACK) TETIKLENDI!",
                            mevcut_win_rate=wr,
                            geri_donulen_checkpoint=best_id,
                            checkpoint_win_rate=best_wr,
                        )
                        self._log_change(date, "ROLLBACK_ALL", 0.0, 1.0, f"Rollback to best checkpoint {best_id} (WR: {best_wr:.2f})", wr, n)
                        return True
            except Exception as exc:
                logger.warning("Rollback denetimi basarisiz", hata=str(exc))
            finally:
                if conn is not None and conn != self._mem_conn:
                    conn.close()
        return False

    def _log_change(self, date: str, param: str, old: float, new: float, reason: str, metric: float | None, n: int) -> None:
        """Parametre degisikligini DuckDB audit tablosuna kaydeder.

        Args:
            date: Teshis tarihi.
            param: Parametre adi.
            old: Eski deger.
            new: Yeni deger.
            reason: Degisiklik gerekcesi.
            metric: Tetikleyici metrik degeri.
            n: Islem sayisi.
        """
        conn = None
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO diagnosis_log (diagnosis_date,param_name,old_value,new_value,reason,metric_value,trade_count,created_at) VALUES (?,?,?,?,?,?,?,?)",
                [date, param, old, new, reason, metric, n, datetime.now(UTC).isoformat()]
            )
            conn.execute(
                "INSERT INTO current_params (param_name,param_value,updated_at,update_count) VALUES (?,?,?,1) ON CONFLICT (param_name) DO UPDATE SET param_value=excluded.param_value,updated_at=excluded.updated_at,update_count=current_params.update_count+1",
                [param, new, datetime.now(UTC).isoformat()]
            )
        except Exception as exc:
            logger.warning("Diagnosis log kaydedilemedi", hata=str(exc))
        finally:
            if conn is not None and conn != self._mem_conn:
                conn.close()

    def _save_summary(self, date: str, metrics: dict[str, Any], n_changes: int) -> None:
        """Gunluk teshis ozetini DuckDB ye kaydeder.

        Args:
            date: Teshis tarihi.
            metrics: Hesaplanan metrikler.
            n_changes: Uygulanan degisiklik sayisi.
        """
        conn = None
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO diagnosis_summary (summary_date,total_trades,win_rate,hard_stop_ratio,avg_hold_days,short_hold_ratio,changes_made,created_at) VALUES (?,?,?,?,?,?,?,?)",
                [date, metrics.get("n",0), metrics.get("win_rate",0.0), metrics.get("hard_stop_ratio",0.0),
                 metrics.get("avg_hold_days",0.0), metrics.get("short_hold_ratio",0.0), n_changes, datetime.now(UTC).isoformat()]
            )
        except Exception as exc:
            logger.warning("Diagnosis summary kaydedilemedi", hata=str(exc))
        finally:
            if conn is not None and conn != self._mem_conn:
                conn.close()

    def load_persisted_params(self, base_params: dict[str, Any]) -> dict[str, Any]:
        """DuckDB'de saklanan ogrenilmis parametreleri base_params uzerine uygular.

        Args:
            base_params: Varsayilan veya mevcut parametre sozlugu.

        Returns:
            Guncellenmis parametre sozlugu.
        """
        conn = None
        try:
            conn = self._get_conn()
            rows = conn.execute("SELECT param_name, param_value FROM current_params").fetchall()
            for param_name, param_val in rows:
                if "min_score" in param_name:
                    regime_part = param_name.replace("min_score_", "")
                    ms = base_params.get("min_score")
                    if isinstance(ms, dict):
                        matched = False
                        for r_key in list(ms.keys()):
                            if r_key == regime_part or regime_part in r_key or r_key in regime_part:
                                ms[r_key] = round(float(param_val), 4)
                                matched = True
                        if not matched:
                            ms[regime_part] = round(float(param_val), 4)
                elif param_name in base_params:
                    if isinstance(base_params[param_name], int):
                        base_params[param_name] = int(round(param_val))
                    else:
                        base_params[param_name] = round(float(param_val), 4)
            logger.info("Ogrenilmis parametreler yuklendi", adet=len(rows))
        except Exception as exc:
            logger.debug("Ogrenilmis parametreler alinamadi", hata=str(exc))
        finally:
            if conn is not None and conn != self._mem_conn:
                conn.close()
        return base_params

    def get_param_history(self, param_name: str, last_n: int = 30) -> list[dict[str, Any]]:
        """Bir parametrenin degisim gecmisini dondurur.

        Args:
            param_name: Parametre adi.
            last_n: Son kac degisiklige bakilacagi.

        Returns:
            Parametre degisim kayitlari listesi.
        """
        conn = None
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT diagnosis_date,old_value,new_value,reason,metric_value FROM diagnosis_log WHERE param_name=? ORDER BY rowid DESC LIMIT ?",
                [param_name, last_n]
            ).fetchall()
            return [{"date": r[0], "old": r[1], "new": r[2], "reason": r[3], "metric": r[4]} for r in rows]
        except Exception as exc:
            logger.warning("Param gecmisi alinamadi", param=param_name, hata=str(exc))
            return []
        finally:
            if conn is not None and conn != self._mem_conn:
                conn.close()

    def get_quarantined_sectors(self) -> set[str]:
        """En son teşhis döngüsünde karantinaya alınmış sektörleri döndürür.

        Returns:
            Karantinadaki sektör adları kümesi.
        """
        conn = None
        try:
            conn = self._get_conn()
            # En güncel teşhis tarihini bul
            latest_date_row = conn.execute("SELECT MAX(diagnosis_date) FROM sector_diagnostics").fetchone()
            if not latest_date_row or not latest_date_row[0]:
                return set()
            latest_date = latest_date_row[0]
            rows = conn.execute(
                "SELECT sector FROM sector_diagnostics WHERE diagnosis_date = ? AND is_quarantined = TRUE",
                [latest_date]
            ).fetchall()
            return {r[0] for r in rows}
        except Exception as exc:
            logger.warning("Karantina sektorleri alinamadi", hata=str(exc))
            return set()
        finally:
            if conn is not None and conn != self._mem_conn:
                conn.close()

    def get_diagnosis_report(self, last_n_days: int = 30) -> dict[str, Any]:
        """Son N gunluk kapsamli teshis ozetini dondurur.
        What-If mikro-simülasyonları, sektör karantinası ve checkpoint geçmişini de içerir.

        Args:
            last_n_days: Kac gunluk ozet istenildigi.

        Returns:
            Teshis raporu sozlugu.
        """
        conn = None
        try:
            conn = self._get_conn()
            summaries = conn.execute(
                "SELECT summary_date,total_trades,win_rate,hard_stop_ratio,avg_hold_days,short_hold_ratio,changes_made FROM diagnosis_summary ORDER BY summary_date DESC LIMIT ?",
                [last_n_days]
            ).fetchall()
            changes = conn.execute(
                "SELECT param_name,COUNT(*) as cnt,MIN(old_value),MAX(new_value) FROM diagnosis_log GROUP BY param_name ORDER BY cnt DESC"
            ).fetchall()

            # 1. Son 20 What-If mikro-simülasyonu
            what_if_rows = conn.execute(
                """
                SELECT sim_date, param_name, old_value, candidate_value, old_sim_pnl, new_sim_pnl, approved, reason, created_at
                FROM what_if_simulations
                ORDER BY created_at DESC LIMIT 20
                """
            ).fetchall()
            what_if_list = [
                {
                    "sim_date": r[0],
                    "param_name": r[1],
                    "old_value": float(r[2]),
                    "candidate_value": float(r[3]),
                    "old_sim_pnl": float(r[4]),
                    "new_sim_pnl": float(r[5]),
                    "approved": bool(r[6]),
                    "reason": r[7],
                    "created_at": r[8],
                }
                for r in what_if_rows
            ]

            # 2. En güncel sektör teşhisi ve karantina listesi
            latest_sec_date_row = conn.execute("SELECT MAX(diagnosis_date) FROM sector_diagnostics").fetchone()
            sector_list = []
            quarantined_sectors = []
            if latest_sec_date_row and latest_sec_date_row[0]:
                sec_rows = conn.execute(
                    """
                    SELECT sector, trades_count, win_rate, total_pnl, is_quarantined, diagnosis_date
                    FROM sector_diagnostics
                    WHERE diagnosis_date = ?
                    ORDER BY total_pnl ASC
                    """,
                    [latest_sec_date_row[0]]
                ).fetchall()
                for r in sec_rows:
                    is_quar = bool(r[4])
                    sec_item = {
                        "sector": r[0],
                        "trades_count": int(r[1]),
                        "win_rate": round(float(r[2]), 4),
                        "total_pnl": round(float(r[3]), 4),
                        "is_quarantined": is_quar,
                        "date": r[5],
                    }
                    sector_list.append(sec_item)
                    if is_quar:
                        quarantined_sectors.append(r[0])

            # 3. Son Checkpoint'ler ve En İyi Durum
            chk_rows = conn.execute(
                """
                SELECT checkpoint_id, created_at, total_trades, win_rate, avg_pnl, sharpe_proxy, is_best
                FROM param_checkpoints
                ORDER BY created_at DESC LIMIT 10
                """
            ).fetchall()
            checkpoints = [
                {
                    "checkpoint_id": r[0],
                    "created_at": r[1],
                    "total_trades": int(r[2]),
                    "win_rate": round(float(r[3]), 4),
                    "avg_pnl": round(float(r[4]), 4),
                    "sharpe_proxy": round(float(r[5]), 4),
                    "is_best": bool(r[6]),
                }
                for r in chk_rows
            ]

            return {
                "summaries": [{"date": r[0],"trades": r[1],"win_rate": r[2],"hard_stop_ratio": r[3],"avg_hold": r[4],"short_hold": r[5],"changes": r[6]} for r in summaries],
                "param_change_counts": [{"param": r[0],"count": r[1],"min": r[2],"max": r[3]} for r in changes],
                "what_if_simulations": what_if_list,
                "sector_diagnostics": sector_list,
                "quarantined_sectors": quarantined_sectors,
                "checkpoints": checkpoints,
            }
        except Exception as exc:
            logger.warning("Teshis raporu alinamadi", hata=str(exc))
            return {}
        finally:
            if conn is not None and conn != self._mem_conn:
                conn.close()


strategy_diagnostician = StrategyDiagnostician()
