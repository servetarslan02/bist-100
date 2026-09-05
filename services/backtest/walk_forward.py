"""
ALPHA BIST — Walk-Forward Validation v3.0 (DEPRECATED)

.. deprecated:: 5.0
    Bu modül geriye dönük uyumluluk için tutulmaktadır.
    Yeni geliştirmeler için ``walk_forward_engine.WalkForwardEngineV5`` kullanınız.

ROADMAP v3.0 FAZ 1, 4:
- Purge: Train sonu → test başı arası aralık (varsayılan 5 gün)
- Embargo: Test sonu → bir sonraki train arası aralık (varsayılan 5 gün)
- Data leakage koruması (Sıfır veri sızıntısı)
- Precision@K, IC, Deflated Sharpe ve stabilite metrikleri
"""

from __future__ import annotations

import math
import threading
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# =====================================================================
# SABİTLER (MAGIC NUMBER TEMİZLİĞİ)
# =====================================================================
DEFAULT_PURGE_DAYS: int = 5
DEFAULT_EMBARGO_DAYS: int = 5
DEFAULT_TRAIN_DAYS: int = 252
DEFAULT_TEST_DAYS: int = 63
DEFAULT_STEP_DAYS: int = 21
ANNUALIZATION_FACTOR: int = 252
MIN_OBSERVATIONS_FOR_IC: int = 10
MIN_OBSERVATIONS_FOR_DEFLATED_SHARPE: int = 30


@dataclass
class WalkForwardFold:
    """
    Tek bir walk-forward doğrulama katmanının (fold) parametre ve performans sonuçları.

    Attributes:
        fold_id: Katman sıra numarası (1-indeksli).
        train_start: Eğitim periyodu başlangıç tarihi (YYYY-AA-GG).
        train_end: Eğitim periyodu bitiş tarihi.
        test_start: Sınama periyodu başlangıç tarihi.
        test_end: Sınama periyodu bitiş tarihi.
        purge_start: Sızıntı engelleme (purge) başlangıç tarihi.
        purge_end: Sızıntı engelleme (purge) bitiş tarihi.
        embargo_start: Ambargo periyodu başlangıç tarihi.
        embargo_end: Ambargo periyodu bitiş tarihi.
        train_samples: Eğitim seti örnek sayısı.
        test_samples: Sınama seti örnek sayısı.
        train_return: Eğitim dönemi toplam getirisi.
        test_return: Sınama dönemi kümülatif getirisi.
        sharpe: Yıllıklandırılmış Sharpe oranı.
        max_drawdown: Maksimum tepe-dip kayıp yüzdesi.
        win_rate: Kazançlı işlem oranı.
        precision_at_5: En yüksek skorlu ilk 5 tahminin başarı oranı.
        precision_at_10: En yüksek skorlu ilk 10 tahminin başarı oranı.
        precision_at_20: En yüksek skorlu ilk 20 tahminin başarı oranı.
        ic: Tahmin skorları ile gerçekleşen getiriler arasındaki korelasyon (Information Coefficient).
        deflated_sharpe: Çoklu test düzeltmesi uygulanmış Sharpe oranı.
        trades: Gerçekleştirilen toplam işlem/tahmin adedi.
    """

    fold_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    purge_start: str
    purge_end: str
    embargo_start: str
    embargo_end: str
    train_samples: int
    test_samples: int
    # Metrikler
    train_return: float = 0.0
    test_return: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    precision_at_20: float = 0.0
    ic: float = 0.0
    deflated_sharpe: float = 0.0
    trades: int = 0

    def __repr__(self) -> str:
        return (
            f"WalkForwardFold(id={self.fold_id}, train={self.train_start}..{self.train_end}, "
            f"test={self.test_start}..{self.test_end}, test_ret={self.test_return:.2%}, sharpe={self.sharpe:.2f})"
        )


@dataclass
class WalkForwardResult:
    """
    Tüm katmanların birleştirilmiş walk-forward doğrulama sonuçları ve özeti.

    Attributes:
        total_folds: Toplam katman adedi.
        avg_test_return: Katmanlar ortalaması test getirisi.
        avg_test_sharpe: Ortalama sınama Sharpe oranı.
        avg_test_drawdown: Ortalama maksimum düşüş.
        avg_win_rate: Ortalama kazanma oranı.
        avg_precision_at_5: Ortalama Precision@5 değeri.
        avg_precision_at_10: Ortalama Precision@10 değeri.
        avg_precision_at_20: Ortalama Precision@20 değeri.
        avg_ic: Ortalama Information Coefficient.
        stability_score: Katmanlar arası getiri tutarlılık skoru [0.0, 1.0].
        worst_fold_return: En kötü katmanın getirisi.
        best_fold_return: En iyi katmanın getirisi.
        deflated_sharpe: Portföy geneli deflated Sharpe oranı.
        folds: Katman bazlı ayrıntılı sonuç listesi.
        summary: Yürütme ve yapılandırma özet parametreleri.
    """

    total_folds: int
    avg_test_return: float
    avg_test_sharpe: float
    avg_test_drawdown: float
    avg_win_rate: float
    avg_precision_at_5: float
    avg_precision_at_10: float
    avg_precision_at_20: float
    avg_ic: float
    stability_score: float
    worst_fold_return: float
    best_fold_return: float
    deflated_sharpe: float
    folds: list[WalkForwardFold]
    summary: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"WalkForwardResult(folds={self.total_folds}, avg_ret={self.avg_test_return:.2%}, "
            f"avg_sharpe={self.avg_test_sharpe:.2f}, stability={self.stability_score:.2f})"
        )


class WalkForwardEngine:
    """
    Purge ve embargo korumalı Walk-Forward Doğrulama Motoru (v3.0).

    Zaman serisi modellerinde veri sızıntısını (look-ahead bias) engellemek için
    eğitim ve test pencereleri arasında aralıklar (purge ve embargo) bırakır.
    İş parçacığı güvenli (thread-safe) çalışır.
    """

    def __init__(
        self,
        purge_days: int = DEFAULT_PURGE_DAYS,
        embargo_days: int = DEFAULT_EMBARGO_DAYS,
        train_days: int = DEFAULT_TRAIN_DAYS,
        test_days: int = DEFAULT_TEST_DAYS,
        step_days: int = DEFAULT_STEP_DAYS,
        expanding_window: bool = True,
        _warn: bool = True,
    ) -> None:
        """
        WalkForwardEngine doğrulama motorunu ilklendirir ve sınır parametrelerini doğrular.

        Args:
            purge_days: Eğitim sonu ile test başı arasındaki aralık gün sayısı (>= 0).
            embargo_days: Test sonu ile sonraki eğitim arasındaki aralık gün sayısı (>= 0).
            train_days: Eğitim penceresi uzunluğu (iş günü, > 0).
            test_days: Test penceresi uzunluğu (iş günü, > 0).
            step_days: Pencerelerin ileri kaydırılma periyodu (iş günü, > 0).
            expanding_window: True ise eğitim başlangıcı sabit tutularak pencere genişletilir,
                              False ise kayan pencere (rolling window) kullanılır.
            _warn: Doğrudan başlatmalarda kullanımdan kaldırma uyarısı verilsin mi.

        Raises:
            ValueError: Gün değerleri geçerli aralıkta olmadığında.
        """
        if purge_days < 0 or embargo_days < 0:
            raise ValueError(f"Purge ({purge_days}) ve embargo ({embargo_days}) gün sayıları negatif olamaz.")
        if train_days <= 0 or test_days <= 0 or step_days <= 0:
            raise ValueError(
                f"Train ({train_days}), test ({test_days}) ve step ({step_days}) gün sayıları pozitif olmalıdır."
            )

        if _warn:
            warnings.warn(
                "walk_forward.WalkForwardEngine kullanımdan kaldırılmıştır (deprecated). "
                "Lütfen 'services.backtest.walk_forward_engine.WalkForwardEngineV5' sınıfını kullanın.",
                DeprecationWarning,
                stacklevel=2,
            )

        self.purge_days: int = purge_days
        self.embargo_days: int = embargo_days
        self.train_days: int = train_days
        self.test_days: int = test_days
        self.step_days: int = step_days
        self.expanding_window: bool = expanding_window
        self._lock: threading.Lock = threading.Lock()

        logger.info(
            "WalkForwardEngine v3.0 ilklendirildi (purge=%d, embargo=%d, train=%d, test=%d, step=%d, expanding=%s)",
            purge_days,
            embargo_days,
            train_days,
            test_days,
            step_days,
            expanding_window,
        )

    def create_folds(
        self,
        dates: list[str],
        train_days: int | None = None,
        test_days: int | None = None,
        step_days: int | None = None,
        purge_days: int | None = None,
        embargo_days: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Tarih serisi üzerinde purge ve embargo aralıklarına tam uyumlu katman pencerelerini oluşturur.

        Args:
            dates: Sıralı iş günü tarih dizisi (YYYY-AA-GG formatında).
            train_days: İsteğe bağlı eğitim penceresi uzunluğu (varsayılan: self.train_days).
            test_days: İsteğe bağlı test penceresi uzunluğu (varsayılan: self.test_days).
            step_days: İsteğe bağlı adım periyodu (varsayılan: self.step_days).
            purge_days: İsteğe bağlı purge aralığı (varsayılan: self.purge_days).
            embargo_days: İsteğe bağlı embargo aralığı (varsayılan: self.embargo_days).

        Returns:
            list[dict[str, Any]]: Her katman için başlangıç ve bitiş indeks tarihlerini içeren sözlük listesi.
        """
        if not dates:
            return []

        # Parametre çözümlemeleri
        eff_train = train_days if (train_days is not None and train_days > 0) else self.train_days
        eff_test = test_days if (test_days is not None and test_days > 0) else self.test_days
        eff_step = step_days if (step_days is not None and step_days > 0) else self.step_days
        eff_purge = purge_days if (purge_days is not None and purge_days >= 0) else self.purge_days
        eff_embargo = embargo_days if (embargo_days is not None and embargo_days >= 0) else self.embargo_days

        # Tarihlerin sıralı olduğundan emin olunur
        sorted_dates = sorted(list(dict.fromkeys(dates)))
        total_len = len(sorted_dates)
        min_required = eff_train + eff_purge + eff_test

        if total_len < min_required:
            return []

        folds: list[dict[str, Any]] = []
        i = 0

        while i + eff_train + eff_purge + eff_test <= total_len:
            # Train penceresi
            train_start_idx = 0 if self.expanding_window else i
            train_end_idx = i + eff_train - 1

            # Purge gap (train sonu → test başı)
            purge_start_idx = train_end_idx + 1
            purge_end_idx = train_end_idx + eff_purge

            # Test penceresi
            test_start_idx = purge_end_idx + 1
            test_end_idx = min(test_start_idx + eff_test - 1, total_len - 1)

            # Embargo gap (test sonu → sonraki train)
            embargo_start_idx = test_end_idx + 1
            embargo_end_idx = test_end_idx + eff_embargo

            if test_end_idx >= total_len:
                break

            folds.append(
                {
                    "train_start": sorted_dates[train_start_idx],
                    "train_end": sorted_dates[train_end_idx],
                    "purge_start": (
                        sorted_dates[purge_start_idx] if purge_start_idx < total_len else sorted_dates[-1]
                    ),
                    "purge_end": (
                        sorted_dates[purge_end_idx] if purge_end_idx < total_len else sorted_dates[-1]
                    ),
                    "test_start": sorted_dates[test_start_idx],
                    "test_end": sorted_dates[test_end_idx],
                    "embargo_start": (
                        sorted_dates[embargo_start_idx] if embargo_start_idx < total_len else sorted_dates[-1]
                    ),
                    "embargo_end": (
                        sorted_dates[embargo_end_idx] if embargo_end_idx < total_len else sorted_dates[-1]
                    ),
                }
            )

            i += eff_step

        return folds

    def _extract_returns_from_price_data(
        self,
        price_data: dict[str, Any],
    ) -> dict[str, dict[str, float]]:
        """
        Farklı biçimlerde iletilen geriye uyumlu price_data sözlüğünden getiri haritası üretir.

        Args:
            price_data: {ticker: [{date, close}]} veya {date: {ticker: return}} yapısındaki fiyat verisi.

        Returns:
            dict[str, dict[str, float]]: {date: {ticker: return}} getiri haritası.
        """
        actual_returns: dict[str, dict[str, float]] = {}

        if not isinstance(price_data, dict):
            return actual_returns

        # Senaryo 1: Zaten {date: {ticker: return}} biçiminde
        sample_key = next(iter(price_data.keys()), None)
        if sample_key and isinstance(price_data[sample_key], dict):
            for d, t_dict in price_data.items():
                if isinstance(t_dict, dict):
                    actual_returns[str(d)] = {str(k): float(v) for k, v in t_dict.items() if isinstance(v, (int, float))}
            return actual_returns

        # Senaryo 2: {ticker: [{date, close}, ...]} biçiminde
        for ticker, rows in price_data.items():
            if not isinstance(rows, list):
                continue
            sorted_rows = sorted(rows, key=lambda x: str(x.get("date", "")))
            prev_close = None
            for row in sorted_rows:
                d = str(row.get("date", ""))
                close = row.get("close")
                if d and close is not None and isinstance(close, (int, float)) and close > 0:
                    if prev_close is not None and prev_close > 0:
                        ret = (close - prev_close) / prev_close
                        if d not in actual_returns:
                            actual_returns[d] = {}
                        actual_returns[d][str(ticker)] = float(ret)
                    prev_close = float(close)

        return actual_returns

    def run_walk_forward(
        self,
        predictions: list[dict[str, Any]] | None = None,
        actual_returns: dict[str, dict[str, float]] | None = None,
        dates: list[str] | None = None,
        signals: list[dict[str, Any]] | None = None,
        price_data: dict[str, Any] | None = None,
        train_days: int | None = None,
        test_days: int | None = None,
        step_days: int | None = None,
    ) -> WalkForwardResult:
        """
        Model tahminleri ve gerçekleşen getiriler üzerinde walk-forward simülasyonunu çalıştırır.

        Args:
            predictions: Model tahmin listesi [{'date': str, 'ticker': str, 'score': float, ...}].
            actual_returns: Gerçekleşen getiri haritası {date: {ticker: return}}.
            dates: İsteğe bağlı tarih listesi (belirtilmezse tahminlerden çıkarılır).
            signals: Geriye uyumluluk için sinyal listesi.
            price_data: Geriye uyumluluk için fiyat serisi (actual_returns yoksa kullanılır).
            train_days: Geçici eğitim penceresi yapılandırma ezmesi (override).
            test_days: Geçici test penceresi yapılandırma ezmesi (override).
            step_days: Geçici adım penceresi yapılandırma ezmesi (override).

        Returns:
            WalkForwardResult: Birleştirilmiş katman ve performans metrikleri nesnesi.
        """
        with self._lock:
            # Yapılandırma ezmeleri (thread-safe yerel değişkenler)
            cur_train_days = train_days if train_days is not None else self.train_days
            cur_test_days = test_days if test_days is not None else self.test_days
            cur_step_days = step_days if step_days is not None else self.step_days

            # Kalıcı alanları da koruma amacıyla senkronize et
            if train_days is not None:
                self.train_days = train_days
            if test_days is not None:
                self.test_days = test_days
            if step_days is not None:
                self.step_days = step_days

        # price_data fallback
        resolved_returns: dict[str, dict[str, float]] = actual_returns or {}
        if not resolved_returns and price_data is not None:
            resolved_returns = self._extract_returns_from_price_data(price_data)

        # signals → predictions dönüştürme (geriye uyumluluk)
        resolved_preds: list[dict[str, Any]] = list(predictions) if predictions is not None else []
        if not resolved_preds and signals is not None:
            resolved_preds = []
            for s in signals:
                d = str(s.get("date", ""))
                ticker = str(s.get("ticker", "TEST"))
                pnl_pct = float(s.get("pnl_pct", 0.0))
                resolved_preds.append(
                    {
                        "date": d,
                        "ticker": ticker,
                        "score": float(s.get("score", 50.0)),
                        "predicted_return": pnl_pct,
                    }
                )
                if d and d not in resolved_returns:
                    resolved_returns[d] = {}
                if d:
                    resolved_returns[d][ticker] = (pnl_pct / 100.0) if pnl_pct else 0.0

        if dates is None:
            dates = sorted(list({str(p.get("date", "")) for p in resolved_preds if p.get("date")}))

        min_len = cur_train_days + self.purge_days + cur_test_days
        if len(dates) < min_len:
            logger.warning("Walk-forward analizi için yeterli tarih verisi bulunamadı (mevcut=%d, asgari=%d)", len(dates), min_len)
            return self._empty_result()

        folds = self.create_folds(
            dates,
            train_days=cur_train_days,
            test_days=cur_test_days,
            step_days=cur_step_days,
        )
        if not folds:
            return self._empty_result()

        fold_results: list[WalkForwardFold] = []

        for fold_id, fold in enumerate(folds, 1):
            train_preds = [
                p for p in resolved_preds if fold["train_start"] <= str(p.get("date", "")) <= fold["train_end"]
            ]
            test_preds = [
                p for p in resolved_preds if fold["test_start"] <= str(p.get("date", "")) <= fold["test_end"]
            ]

            train_metrics = self._calculate_fold_metrics(
                train_preds, resolved_returns, fold["train_start"], fold["train_end"]
            )
            test_metrics = self._calculate_fold_metrics(
                test_preds, resolved_returns, fold["test_start"], fold["test_end"]
            )

            fold_result = WalkForwardFold(
                fold_id=fold_id,
                train_start=fold["train_start"],
                train_end=fold["train_end"],
                test_start=fold["test_start"],
                test_end=fold["test_end"],
                purge_start=fold["purge_start"],
                purge_end=fold["purge_end"],
                embargo_start=fold["embargo_start"],
                embargo_end=fold["embargo_end"],
                train_samples=len(train_preds),
                test_samples=len(test_preds),
                train_return=round(float(train_metrics.get("return", 0.0)), 4),
                test_return=round(float(test_metrics.get("return", 0.0)), 4),
                sharpe=round(float(test_metrics.get("sharpe", 0.0)), 4),
                max_drawdown=round(float(test_metrics.get("max_drawdown", 0.0)), 4),
                win_rate=round(float(test_metrics.get("win_rate", 0.0)), 4),
                precision_at_5=round(float(test_metrics.get("precision_at_5", 0.0)), 4),
                precision_at_10=round(float(test_metrics.get("precision_at_10", 0.0)), 4),
                precision_at_20=round(float(test_metrics.get("precision_at_20", 0.0)), 4),
                ic=round(float(test_metrics.get("ic", 0.0)), 4),
                deflated_sharpe=round(float(test_metrics.get("deflated_sharpe", 0.0)), 4),
                trades=int(test_metrics.get("trades", 0)),
            )
            fold_results.append(fold_result)

        return self._aggregate_results(fold_results)

    def _calculate_fold_metrics(
        self,
        predictions: list[dict[str, Any]],
        actual_returns: dict[str, dict[str, float]],
        start_date: str,
        end_date: str,
    ) -> dict[str, float]:
        """
        Belirli bir katman (fold) için Sharpe, Drawdown, Precision@K ve IC metriklerini hesaplar.

        Args:
            predictions: Katman içerisindeki tahmin kayıtları.
            actual_returns: Gerçekleşen getiri haritası.
            start_date: Katman başlangıç tarihi.
            end_date: Katman bitiş tarihi.

        Returns:
            dict[str, float]: Hesaplanan performans metrikleri sözlüğü.
        """
        if not predictions:
            return {}

        date_groups: dict[str, list[dict[str, Any]]] = {}
        for p in predictions:
            d = str(p.get("date", ""))
            if d:
                date_groups.setdefault(d, []).append(p)

        returns: list[float] = []
        win_count: int = 0
        total_count: int = 0
        all_scores: list[float] = []
        all_actuals: list[float] = []

        precision_at_k: dict[int, list[float]] = {5: [], 10: [], 20: []}

        for date, preds in date_groups.items():
            if date not in actual_returns:
                continue

            day_actuals = actual_returns[date]

            # Skora göre azalan sırala
            preds_sorted = sorted(preds, key=lambda x: float(x.get("score", 0.0)), reverse=True)

            # Top K precision
            for k in (5, 10, 20):
                top_k = preds_sorted[:k]
                if top_k:
                    correct = sum(1 for p in top_k if float(day_actuals.get(str(p.get("ticker", "")), 0.0)) > 0.0)
                    precision_at_k[k].append(float(correct) / float(len(top_k)))

            # Tüm tahminler için getiri ve skorlar
            for p in preds:
                ticker = str(p.get("ticker", ""))
                score = float(p.get("score", 0.0))
                actual = float(day_actuals.get(ticker, 0.0))

                returns.append(actual)
                all_scores.append(score)
                all_actuals.append(actual)

                if actual > 0.0:
                    win_count += 1
                total_count += 1

        if not returns:
            return {}

        clean_returns = np.array([r for r in returns if math.isfinite(r)], dtype=np.float64)
        if len(clean_returns) == 0:
            return {}

        total_return = float(np.sum(clean_returns))
        win_rate = float(win_count) / float(total_count) if total_count > 0 else 0.0

        # Sharpe Oranı
        ret_std = float(np.std(clean_returns))
        sharpe = (float(np.mean(clean_returns)) / ret_std * math.sqrt(ANNUALIZATION_FACTOR)) if ret_std > 1e-12 else 0.0
        if not math.isfinite(sharpe):
            sharpe = 0.0

        # Max Drawdown
        clipped_ret = np.clip(clean_returns, -0.9999, 10.0)
        cumulative = np.cumprod(1.0 + clipped_ret)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (peak - cumulative) / np.maximum(np.abs(peak), 1e-10)
        max_dd = float(np.max(drawdown) * 100.0) if len(drawdown) > 0 else 0.0
        if not math.isfinite(max_dd):
            max_dd = 0.0

        # IC (Information Coefficient)
        ic = 0.0
        if len(all_scores) >= MIN_OBSERVATIONS_FOR_IC and len(all_actuals) >= MIN_OBSERVATIONS_FOR_IC:
            try:
                arr_scores = np.array(all_scores, dtype=np.float64)
                arr_actuals = np.array(all_actuals, dtype=np.float64)
                valid_mask = np.isfinite(arr_scores) & np.isfinite(arr_actuals)
                if np.sum(valid_mask) >= MIN_OBSERVATIONS_FOR_IC:
                    arr_scores = arr_scores[valid_mask]
                    arr_actuals = arr_actuals[valid_mask]
                    if float(np.std(arr_scores)) > 1e-12 and float(np.std(arr_actuals)) > 1e-12:
                        corr = np.corrcoef(arr_scores, arr_actuals)[0, 1]
                        if math.isfinite(corr):
                            ic = float(corr)
            except Exception as e:
                logger.debug("IC hesaplamasında nümerik istisna: %s", e)
                ic = 0.0

        # Deflated Sharpe
        deflated_sharpe = self._deflated_sharpe(sharpe, len(clean_returns), max(1, len(date_groups)))

        return {
            "return": total_return,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "precision_at_5": float(np.mean(precision_at_k[5])) if precision_at_k[5] else 0.0,
            "precision_at_10": float(np.mean(precision_at_k[10])) if precision_at_k[10] else 0.0,
            "precision_at_20": float(np.mean(precision_at_k[20])) if precision_at_k[20] else 0.0,
            "ic": ic,
            "deflated_sharpe": deflated_sharpe,
            "trades": float(total_count),
        }

    def _deflated_sharpe(self, sharpe: float, n_obs: int, n_trials: int = 1) -> float:
        """
        Bailey & López de Prado (2014) metodolojisiyle Deflated Sharpe Oranı hesaplar.

        Çoklu test ve aşırı uyum (overfitting) etkisini cezalandırarak gerçekçi Sharpe oranını tahmin eder.

        Args:
            sharpe: Yıllıklandırılmış standart Sharpe oranı.
            n_obs: Gözlem sayısı (iş günü adedi).
            n_trials: Denenen alternatif strateji veya katman adedi.

        Returns:
            float: Cezalandırılmış pozitif Sharpe oranı (alt sınır 0.0).
        """
        if n_obs < MIN_OBSERVATIONS_FOR_DEFLATED_SHARPE or sharpe <= 0.0 or n_trials < 1:
            return 0.0

        daily_sharpe = sharpe / math.sqrt(ANNUALIZATION_FACTOR)
        se = math.sqrt((1.0 + 0.5 * daily_sharpe**2) / float(n_obs))

        if n_trials > 1:
            adjusted_sharpe = daily_sharpe - se * math.sqrt(2.0 * math.log(float(n_trials)))
        else:
            adjusted_sharpe = daily_sharpe

        result = max(0.0, adjusted_sharpe * math.sqrt(ANNUALIZATION_FACTOR))
        return float(result) if math.isfinite(result) else 0.0

    def _aggregate_results(self, folds: list[WalkForwardFold]) -> WalkForwardResult:
        """
        Katman bazlı ayrıntılı sonuçları birleştirerek portföy genel metriklerini hesaplar.

        Args:
            folds: Katman sonuç listesi.

        Returns:
            WalkForwardResult: Özet sonuç nesnesi.
        """
        if not folds:
            return self._empty_result()

        test_returns = [f.test_return for f in folds if math.isfinite(f.test_return)]
        test_sharpes = [f.sharpe for f in folds if math.isfinite(f.sharpe)]
        test_win_rates = [f.win_rate for f in folds if math.isfinite(f.win_rate)]
        test_drawdowns = [f.max_drawdown for f in folds if math.isfinite(f.max_drawdown)]
        precisions_5 = [f.precision_at_5 for f in folds if math.isfinite(f.precision_at_5)]
        precisions_10 = [f.precision_at_10 for f in folds if math.isfinite(f.precision_at_10)]
        precisions_20 = [f.precision_at_20 for f in folds if math.isfinite(f.precision_at_20)]
        ics = [f.ic for f in folds if math.isfinite(f.ic)]

        mean_ret = float(np.mean(test_returns)) if test_returns else 0.0
        std_ret = float(np.std(test_returns)) if test_returns else 0.0
        denom = abs(mean_ret) + 0.01
        cv = std_ret / denom if denom > 0.0 else 1.0
        stability = max(0.0, min(1.0, 1.0 - cv))
        if not math.isfinite(stability):
            stability = 0.0

        total_sharpe = float(np.mean(test_sharpes)) if test_sharpes else 0.0
        total_trades = sum(f.trades for f in folds)
        deflated = self._deflated_sharpe(total_sharpe, total_trades, len(folds))

        return WalkForwardResult(
            total_folds=len(folds),
            avg_test_return=round(mean_ret, 4),
            avg_test_sharpe=round(total_sharpe, 4),
            avg_test_drawdown=round(float(np.mean(test_drawdowns)) if test_drawdowns else 0.0, 4),
            avg_win_rate=round(float(np.mean(test_win_rates)) if test_win_rates else 0.0, 4),
            avg_precision_at_5=round(float(np.mean(precisions_5)) if precisions_5 else 0.0, 4),
            avg_precision_at_10=round(float(np.mean(precisions_10)) if precisions_10 else 0.0, 4),
            avg_precision_at_20=round(float(np.mean(precisions_20)) if precisions_20 else 0.0, 4),
            avg_ic=round(float(np.mean(ics)) if ics else 0.0, 4),
            stability_score=round(stability, 4),
            worst_fold_return=round(float(min(test_returns)) if test_returns else 0.0, 4),
            best_fold_return=round(float(max(test_returns)) if test_returns else 0.0, 4),
            deflated_sharpe=round(deflated, 4),
            folds=folds,
            summary={
                "purge_days": self.purge_days,
                "embargo_days": self.embargo_days,
                "train_days": self.train_days,
                "test_days": self.test_days,
                "step_days": self.step_days,
                "total_predictions": total_trades,
            },
        )

    def _empty_result(self) -> WalkForwardResult:
        """
        Veri yetersizliği veya boş giriş durumunda sıfırlanmış boş sonuç nesnesi döndürür.

        Returns:
            WalkForwardResult: Sıfırlanmış metrik değerleri içeren boş sonuç nesnesi.
        """
        return WalkForwardResult(
            total_folds=0,
            avg_test_return=0.0,
            avg_test_sharpe=0.0,
            avg_test_drawdown=0.0,
            avg_win_rate=0.0,
            avg_precision_at_5=0.0,
            avg_precision_at_10=0.0,
            avg_precision_at_20=0.0,
            avg_ic=0.0,
            stability_score=0.0,
            worst_fold_return=0.0,
            best_fold_return=0.0,
            deflated_sharpe=0.0,
            folds=[],
            summary={
                "purge_days": self.purge_days,
                "embargo_days": self.embargo_days,
                "train_days": self.train_days,
                "test_days": self.test_days,
                "step_days": self.step_days,
                "total_predictions": 0,
            },
        )

    def __repr__(self) -> str:
        return (
            f"WalkForwardEngine(purge={self.purge_days}, embargo={self.embargo_days}, "
            f"train={self.train_days}, test={self.test_days}, step={self.step_days}, "
            f"expanding={self.expanding_window})"
        )


# Singleton (Geriye dönük uyumluluk için tembel başlatma/mevcut tutma, import anında uyarı vermez)
walk_forward_engine: WalkForwardEngine = WalkForwardEngine(_warn=False)

__all__ = [
    "ANNUALIZATION_FACTOR",
    "DEFAULT_EMBARGO_DAYS",
    "DEFAULT_PURGE_DAYS",
    "DEFAULT_STEP_DAYS",
    "DEFAULT_TEST_DAYS",
    "DEFAULT_TRAIN_DAYS",
    "WalkForwardEngine",
    "WalkForwardFold",
    "WalkForwardResult",
    "walk_forward_engine",
]
