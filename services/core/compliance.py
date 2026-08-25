"""
ALPHA BIST — SPK Compliance

Sermaye Piyasası Kurulu uyumluluk:
- %5 bildirim yükümlülüğü
- Manipülasyon kontrolü
- İçerden bilgi ticareti kontrolü
- Algoritmik trading bildirimi
"""

from typing import Dict, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class ComplianceResult:
    notification_required: bool = False
    violation: bool = False
    action: str = ""        # "OK", "NOTIFY", "BLOCK"
    reason: str = ""
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "notification_required": self.notification_required,
            "violation": self.violation,
            "action": self.action,
            "reason": self.reason,
        }


class ComplianceChecker:
    """SPK uyumluluk kontrolü."""

    # %5 bildirim eşiği
    NOTIFICATION_THRESHOLD = 0.05   # %5
    # %10 zorunlu teklif eşiği
    MANDATORY_BID_THRESHOLD = 0.10  # %10
    # %20 engelleme azınlığı
    BLOCKING_MINORITY = 0.20        # %20

    def check_spk_compliance(
        self,
        action: str,
        ticker: str,
        amount: float,
        portfolio_value: float,
        current_position_pct: float = 0,
    ) -> ComplianceResult:
        """SPK uyumluluk kontrolü.

        Args:
            action: "BUY" veya "SELL"
            ticker: Hisse kodu
            amount: İşlem tutarı
            portfolio_value: Portföy değeri
            current_position_pct: Mevcut pozisyon yüzdesi (0-1)
        """
        details = {
            "ticker": ticker,
            "action": action,
            "amount": amount,
            "portfolio_value": portfolio_value,
        }

        if portfolio_value <= 0:
            return ComplianceResult(action="OK")

        # Yeni pozisyon yüzdesi
        if action == "BUY":
            new_position_pct = current_position_pct + (amount / portfolio_value)
        else:
            new_position_pct = max(0, current_position_pct - (amount / portfolio_value))

        # %10 zorunlu teklif (önce kontrol et — daha kritik)
        if new_position_pct >= self.MANDATORY_BID_THRESHOLD and current_position_pct < self.MANDATORY_BID_THRESHOLD:
            return ComplianceResult(
                notification_required=True,
                violation=True,
                action="BLOCK",
                reason=f"SPK %10 zorunlu teklif eşiği: {new_position_pct*100:.1f}%",
                details={**details, "new_position_pct": new_position_pct},
            )

        # %5 bildirim yükümlülüğü
        if action == "BUY":
            if new_position_pct >= self.NOTIFICATION_THRESHOLD and current_position_pct < self.NOTIFICATION_THRESHOLD:
                return ComplianceResult(
                    notification_required=True,
                    action="NOTIFY",
                    reason=f"SPK %5 bildirim yükümlülüğü: {new_position_pct*100:.1f}%",
                    details={**details, "new_position_pct": new_position_pct},
                )
        else:
            # SELL: pozisyon azalırken de kontrol et
            if current_position_pct >= self.NOTIFICATION_THRESHOLD and new_position_pct < self.NOTIFICATION_THRESHOLD:
                return ComplianceResult(
                    notification_required=True,
                    action="NOTIFY",
                    reason=f"SPK %5 bildirim altına düşüş: {new_position_pct*100:.1f}%",
                    details={**details, "new_position_pct": new_position_pct},
                )

        return ComplianceResult(action="OK", details=details)


# Singleton
compliance_checker = ComplianceChecker()
