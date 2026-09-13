from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Para politikası duruşu reel faiz ve Taylor kuralı sapma eşik sabitleri (%)
DEFAULT_TCMB_STANCE_VERY_TIGHT: float = 4.0
DEFAULT_TCMB_STANCE_TIGHT: float = 1.0
DEFAULT_TCMB_STANCE_NEUTRAL: float = -1.0
DEFAULT_TCMB_STANCE_LOOSE: float = -4.0
DEFAULT_TCMB_SURPRISE_THRESHOLD: float = 0.02


def compute_tcmb_features(tcmb_data: dict[str, Any]) -> dict[str, float]:
    """TCMB para politikası, rezerv yeterliliği, Taylor kuralı ve likidite koridoru analitiklerini hesaplar.

    Hesaplanan Kurumsal Göstergeler:
    - tcmb_policy_rate: 1 haftalık repo politika faizi (%)
    - tcmb_real_rate: Gerçekleşen reel faiz (politika faizi - cari TÜFE)
    - tcmb_forward_real_rate: 12 ay ileriye dönük beklenen reel faiz
    - tcmb_taylor_gap: Taylor kuralı ima edilen faiz sapması (geride kalma / önden yükleme)
    - tcmb_carry_to_risk: TCMB-Fed faiz farkının USD/TRY oynaklığına oranı (Carry Trade cazibesi)
    - tcmb_wacf: Ağırlıklı ortalama fonlama maliyeti (WACF / AOFM)
    - tcmb_wacf_spread: AOFM - Politika faizi makası (örtülü sıkılaştırma/gevşeme)
    - tcmb_corridor_width: Üst bant - alt bant koridor genişliği
    - tcmb_corridor_asymmetry: AOFM'nin koridor içindeki göreceli konumu (0 = alt bant, 1 = üst bant)
    - tcmb_net_reserves_ex_swap: Swap hariç net rezerv baskı seviyesi (Milyar USD)
    - tcmb_net_reserve_change_1m: Net rezervlerin 1 aylık ivmesi
    - tcmb_policy_stance: -2 (Çok Gevşek) ile +2 (Çok Sıkı) arası para politikası duruş kodu

    Args:
        tcmb_data: Faizler, beklentiler, WACF, enflasyon, rezerv ve koridor verilerini içeren sözlük.

    Returns:
        dict[str, float]: Hesaplanmış kantitatif merkez bankası göstergeleri sözlüğü.
    """
    features: dict[str, float] = {}

    if not tcmb_data:
        return features

    try:
        # 1. Politika Faizi ve Değişimi
        policy_rate = tcmb_data.get("policy_rate")
        if policy_rate is not None:
            p_rate = float(policy_rate)
            features["tcmb_policy_rate"] = round(p_rate, 2)

            rate_change = tcmb_data.get("rate_change")
            if rate_change is None and "prev_policy_rate" in tcmb_data:
                rate_change = p_rate - float(tcmb_data["prev_policy_rate"])

            if rate_change is not None:
                features["tcmb_rate_change"] = round(float(rate_change), 2)
                features["tcmb_rate_direction"] = 1.0 if float(rate_change) > 0 else (-1.0 if float(rate_change) < 0 else 0.0)

            # 2. Cari ve İleriye Dönük Reel Faiz
            inflation = tcmb_data.get("inflation") or tcmb_data.get("inflation_rate") or tcmb_data.get("cpi_yoy")
            if inflation is not None:
                features["tcmb_real_rate"] = round(p_rate - float(inflation), 2)

            expected_inf_12m = tcmb_data.get("expected_inflation_12m") or tcmb_data.get("expected_inflation")
            if expected_inf_12m is not None and float(expected_inf_12m) > 0:
                features["tcmb_forward_real_rate"] = round(p_rate - float(expected_inf_12m), 2)

            # 3. Taylor Kuralı Sapması (Taylor Rule Implied Rate Gap)
            # Standart Taylor Kuralı: i* = r* + pi + 0.5 * (pi - target_pi) + 0.5 * output_gap
            neutral_real_rate = float(tcmb_data.get("neutral_real_rate", 2.0))  # r* denge reel faizi
            target_inflation = float(tcmb_data.get("target_inflation", 5.0))  # Resmi hedef %5
            output_gap = float(tcmb_data.get("output_gap", 0.0))  # Çıktı açığı

            inf_level = float(inflation) if inflation is not None else float(expected_inf_12m or 30.0)
            taylor_implied_rate = neutral_real_rate + inf_level + (0.5 * (inf_level - target_inflation)) + (0.5 * output_gap)
            taylor_gap = p_rate - taylor_implied_rate
            features["tcmb_taylor_implied_rate"] = round(taylor_implied_rate, 2)
            features["tcmb_taylor_gap"] = round(taylor_gap, 2)

            # 4. Küresel Faiz Farkı & Carry-to-Risk Oranı
            us_rate = tcmb_data.get("us_rate") or tcmb_data.get("fed_rate") or tcmb_data.get("fed_funds_rate")
            if us_rate is not None:
                rate_diff = p_rate - float(us_rate)
                features["tcmb_rate_differential"] = round(rate_diff, 2)

                fx_vol = float(tcmb_data.get("usdtry_volatility_20d") or tcmb_data.get("usdtry_volatility") or 12.0)
                if fx_vol > 0:
                    features["tcmb_carry_to_risk"] = round(rate_diff / fx_vol, 3)

        # 5. Faiz Sürprizi ve Beklenti Ayrışması
        actual_rate = tcmb_data.get("actual_rate")
        expected_rate = tcmb_data.get("expected_rate")
        if actual_rate is not None and expected_rate is not None:
            surprise = float(actual_rate) - float(expected_rate)
            features["tcmb_rate_surprise"] = round(surprise, 4)
            surprise_pct = surprise / max(abs(float(expected_rate)), 0.01)
            features["tcmb_rate_surprise_pct"] = round(surprise_pct, 4)
            features["tcmb_rate_surprise_direction"] = (
                1.0 if surprise_pct > DEFAULT_TCMB_SURPRISE_THRESHOLD
                else (-1.0 if surprise_pct < -DEFAULT_TCMB_SURPRISE_THRESHOLD else 0.0)
            )

        # 6. Fonlama Maliyeti (WACF / AOFM) ve Faiz Koridoru
        wacf = tcmb_data.get("wacf")
        if wacf is not None and float(wacf) > 0:
            w_val = float(wacf)
            features["tcmb_wacf"] = round(w_val, 2)
            if "tcmb_policy_rate" in features:
                features["tcmb_wacf_spread"] = round(w_val - features["tcmb_policy_rate"], 2)

        corridor_upper = tcmb_data.get("corridor_upper") or tcmb_data.get("upper_corridor")
        corridor_lower = tcmb_data.get("corridor_lower") or tcmb_data.get("lower_corridor")
        if corridor_upper is not None and corridor_lower is not None:
            c_up = float(corridor_upper)
            c_low = float(corridor_lower)
            c_width = c_up - c_low
            features["tcmb_corridor_width"] = round(c_width, 2)

            if wacf is not None and c_width > 0:
                # AOFM'nin koridordaki bağıl konumu: 0.0 (alt bant) ile 1.0 (üst bant)
                corridor_pos = (float(wacf) - c_low) / c_width
                features["tcmb_corridor_asymmetry"] = round(max(0.0, min(1.0, corridor_pos)), 4)

        # 7. Swap Hariç Net Uluslararası Rezerv Baskısı (Net International Reserves)
        net_reserves = tcmb_data.get("net_reserves_ex_swap")
        if net_reserves is None and "gross_reserves" in tcmb_data and "swap_obligations" in tcmb_data:
            net_reserves = float(tcmb_data["gross_reserves"]) - float(tcmb_data["swap_obligations"])

        if net_reserves is not None:
            features["tcmb_net_reserves_ex_swap"] = round(float(net_reserves), 2)
            reserves_prev = tcmb_data.get("net_reserves_ex_swap_prev")
            if reserves_prev is not None:
                features["tcmb_net_reserve_change_1m"] = round(float(net_reserves) - float(reserves_prev), 2)

        # 8. Para Politikası Duruşu (Reel faiz rejimi)
        real_rate_val = features.get("tcmb_real_rate")
        if real_rate_val is not None:
            if real_rate_val > DEFAULT_TCMB_STANCE_VERY_TIGHT:
                stance = 2.0  # ÇOK SIKI (> 3.0%)
            elif real_rate_val > DEFAULT_TCMB_STANCE_TIGHT:
                stance = 1.0  # SIKI (> 0.0%)
            elif real_rate_val > DEFAULT_TCMB_STANCE_LOOSE:
                stance = -1.0  # GEVŞEK (> -3.0%)
            else:
                stance = -2.0  # ÇOK GEVŞEK (<= -3.0%)
            features["tcmb_policy_stance"] = stance

    except Exception as e:
        logger.error("TCMB kurumsal analitik hesaplaması başarısız oldu", error=str(e))

    return features


__all__ = [
    "DEFAULT_TCMB_STANCE_VERY_TIGHT",
    "DEFAULT_TCMB_STANCE_TIGHT",
    "DEFAULT_TCMB_STANCE_NEUTRAL",
    "DEFAULT_TCMB_STANCE_LOOSE",
    "DEFAULT_TCMB_SURPRISE_THRESHOLD",
    "compute_tcmb_features",
]


