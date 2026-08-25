"""
ALPHA BIST — Outcome Tracker v1.0

Tahmin sonuçlarını otomatik takip eder:
- Her prediction için bekleme süresi (5 gün default)
- Süre dolduğunda gerçek fiyatı çek
- Outcome kaydet
- Learning system'a bildir

Bu modül learning'in çalışması için KRİTİK.
"""

from typing import Dict, List, Any
from datetime import datetime, timezone, timedelta
from collections import deque
import structlog

logger = structlog.get_logger()


class OutcomeTracker:
    """Tahmin sonuçlarını otomatik takip eder."""

    # Tahmin bekleme süreleri (iş günü)
    HORIZON_DAYS = {
        "1-5D": 5,
        "1-4W": 20,
        "1-6M": 60,
        "6-24M": 120,
    }

    def __init__(self):
        self._pending: deque = deque(maxlen=5000)  # Sonuç bekleyen tahminler
        self._checked_today: set = set()

    def add_prediction(self, prediction: Dict):
        """Yeni tahmin ekle — outcome takibi başlat."""
        ticker = prediction.get("ticker", "")
        predicted_direction = prediction.get("predicted_direction", "")
        entry_price = prediction.get("feature_snapshot", {}).get("price", 0)
        prediction_id = prediction.get("prediction_id", "")

        if not ticker or not prediction_id:
            return

        # Bekleme süresi (default 5 gün)
        horizon = prediction.get("horizon", "1-5D")
        wait_days = self.HORIZON_DAYS.get(horizon, 5)

        self._pending.append({
            "prediction_id": prediction_id,
            "ticker": ticker,
            "predicted_direction": predicted_direction,
            "entry_price": entry_price,
            "entry_time": prediction.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "check_after": (datetime.now(timezone.utc) + timedelta(days=wait_days)).isoformat(),
            "horizon": horizon,
            "checked": False,
        })
        if len(self._pending) > 1000:
            self._pending = self._pending[-1000:]

        logger.debug("Outcome tracking started",
                     ticker=ticker, prediction_id=prediction_id,
                     check_after=f"{wait_days} days")

    async def check_pending_outcomes(self, learning_system, price_fetcher) -> List[Dict]:
        """Bekleyen tahminleri kontrol et ve outcome kaydet.

        Args:
            learning_system: IntegratedLearningSystem instance
            price_fetcher: async def get_price(ticker) -> float

        Returns:
            Kaydedilen outcome'lar
        """
        now = datetime.now(timezone.utc)
        results = []

        for pending in self._pending:
            if pending["checked"]:
                continue

            # Zamanı geldi mi?
            check_after = datetime.fromisoformat(pending["check_after"])
            if check_after.tzinfo is None:
                check_after = check_after.replace(tzinfo=timezone.utc)
            if now < check_after:
                continue

            # Bugün zaten kontrol edildi mi?
            if pending["prediction_id"] in self._checked_today:
                continue

            ticker = pending["ticker"]
            prediction_id = pending["prediction_id"]

            try:
                # Güncel fiyatı çek
                current_price = await price_fetcher(ticker)

                if current_price and current_price > 0:
                    entry_price = pending.get("entry_price", 0)

                    if entry_price and entry_price > 0:
                        # Outcome kaydet
                        learning_system.record_outcome(
                            ticker=ticker,
                            actual_price=current_price,
                            entry_price=entry_price,
                            holding_days=self._calculate_holding_days(pending["entry_time"]),
                            outcome_type="auto",
                        )

                        pending["checked"] = True
                        self._checked_today.add(prediction_id)

                        actual_return = (current_price / entry_price - 1) * 100
                        results.append({
                            "prediction_id": prediction_id,
                            "ticker": ticker,
                            "entry_price": entry_price,
                            "actual_price": current_price,
                            "actual_return": round(actual_return, 2),
                            "predicted_direction": pending["predicted_direction"],
                        })

                        logger.info("Outcome recorded",
                                   ticker=ticker,
                                   entry=entry_price,
                                   actual=current_price,
                                   return_pct=round(actual_return, 2))
                    else:
                        # Giriş fiyatı yoksa fiyatı kaydet ve sonraki kontrole bekle
                        pending["entry_price"] = current_price
                        logger.debug("Entry price set", ticker=ticker, price=current_price)
                else:
                    logger.warning("Could not fetch price for outcome", ticker=ticker)

            except Exception as e:
                logger.warning("Outcome check failed", ticker=ticker, error=str(e))

        # Eski kayıtları temizle (30 günden eski)
        cutoff = (now - timedelta(days=30)).isoformat()
        self._pending = [p for p in self._pending
                        if not p["checked"] or p.get("entry_time", "") > cutoff]

        # Günlük sayacı sıfırla (yeni gün)
        # (Basit implementasyon - her saat sıfırla)
        if len(self._checked_today) > 100:
            self._checked_today.clear()

        return results

    def _calculate_holding_days(self, entry_time_str: str) -> int:
        """Tutma süresi hesapla."""
        try:
            entry = datetime.fromisoformat(entry_time_str)
            if entry.tzinfo is None:
                entry = entry.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return max(0, (now - entry).days)
        except Exception:
            return 0

    def get_pending_count(self) -> int:
        """Bekleyen tahmin sayısı."""
        return len([p for p in self._pending if not p["checked"]])

    def get_stats(self) -> Dict[str, Any]:
        """İstatistikler."""
        total = len(self._pending)
        checked = len([p for p in self._pending if p["checked"]])
        return {
            "total_tracked": total,
            "checked": checked,
            "pending": total - checked,
        }


# Singleton
outcome_tracker = OutcomeTracker()
