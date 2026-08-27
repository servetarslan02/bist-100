"""
ALPHA BIST — TCMB Features v2.0

TCMB para politikası feature'ları:
- policy_rate: Politika faizi
- real_rate: Reel faiz (faiz - enflasyon)
- rate_surprise: Faiz sürprizi (beklenti vs gerçek)
- policy_stance: Para politikası duruşu (sıkı/gevşek/nötr)
- rate_change: Faiz değişimi
- rate_differential: ABD faiz farkı
- wacf: Ağırlıklı ortalama fonlama maliyeti

Refactor: Config-driven, error handling, logging
"""

from typing import Any

import structlog

logger = structlog.get_logger()


def compute_tcmb_features(tcmb_data: dict[str, Any]) -> dict[str, float]:
    """TCMB faiz ve para politikası feature'ları.

    Args:
        tcmb_data: {
            "policy_rate": float,        # Politika faizi
            "inflation": float,          # Enflasyon (CPI YoY)
            "actual_rate": float,        # Gerçekleşen faiz
            "expected_rate": float,       # Beklenti faiz
            "us_rate": float,            # ABD faizi
            "wacf": float,               # Ağırlıklı ortalama fonlama maliyeti
            "rate_change": float,        # Son faiz değişimi
            "corridor_upper": float,     # Koridor üst
            "corridor_lower": float,     # Koridor alt
        }

    Returns:
        Feature dictionary
    """
    features = {}

    try:
        # Politika faizi
        policy_rate = tcmb_data.get("policy_rate", 0)
        if policy_rate:
            features["tcmb_policy_rate"] = round(float(policy_rate), 2)

        # Reel faiz = faiz - enflasyon
        inflation = tcmb_data.get("inflation", 0)
        if policy_rate and inflation:
            features["tcmb_real_rate"] = round(float(policy_rate) - float(inflation), 2)

        # Faiz sürprizi
        actual_rate = tcmb_data.get("actual_rate")
        expected_rate = tcmb_data.get("expected_rate")
        if actual_rate is not None and expected_rate is not None:
            features["tcmb_rate_surprise"] = round(float(actual_rate) - float(expected_rate), 4)
            # Sürpriz yönü
            surprise_pct = (float(actual_rate) - float(expected_rate)) / max(abs(float(expected_rate)), 0.01)
            features["tcmb_rate_surprise_pct"] = round(surprise_pct, 4)
            features["tcmb_rate_surprise_direction"] = (
                1.0 if surprise_pct > 0.02 else (-1.0 if surprise_pct < -0.02 else 0.0)
            )

        # Para politikası duruşu
        if policy_rate and inflation:
            real_rate = float(policy_rate) - float(inflation)
            if real_rate > 3:
                features["tcmb_policy_stance"] = 2.0  # ÇOK SIKI
            elif real_rate > 0:
                features["tcmb_policy_stance"] = 1.0  # SIKI
            elif real_rate > -3:
                features["tcmb_policy_stance"] = -1.0  # GEVŞEK
            else:
                features["tcmb_policy_stance"] = -2.0  # ÇOK GEVŞEK

        # Faiz değişimi
        rate_change = tcmb_data.get("rate_change", 0)
        if rate_change:
            features["tcmb_rate_change"] = round(float(rate_change), 2)
            features["tcmb_rate_direction"] = (
                1.0 if float(rate_change) > 0 else (-1.0 if float(rate_change) < 0 else 0.0)
            )

        # ABD faiz farkı (carry trade etkisi)
        us_rate = tcmb_data.get("us_rate")
        if policy_rate and us_rate:
            features["tcmb_rate_differential"] = round(float(policy_rate) - float(us_rate), 2)

        # WACF (ağırlıklı ortalama fonlama maliyeti)
        wacf = tcmb_data.get("wacf")
        if wacf:
            features["tcmb_wacf"] = round(float(wacf), 2)
            if policy_rate:
                features["tcmb_wacf_spread"] = round(float(wacf) - float(policy_rate), 2)

        # Koridor genişliği
        corridor_upper = tcmb_data.get("corridor_upper")
        corridor_lower = tcmb_data.get("corridor_lower")
        if corridor_upper and corridor_lower:
            features["tcmb_corridor_width"] = round(float(corridor_upper) - float(corridor_lower), 2)

    except Exception as e:
        logger.error("TCMB feature computation failed", error=str(e))

    return features
