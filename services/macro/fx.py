"""ALPHA BIST — FX Features."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def compute_fx_features(fx_data: Dict[str, Any]) -> Dict[str, float]:
    """Döviz kuru feature'ları."""
    features = {}
    features["usdtry"] = fx_data.get("usdtry", 0)
    features["usdtry_change"] = fx_data.get("usdtry_change", 0)
    features["usdtry_volatility"] = fx_data.get("usdtry_vol", 0)
    features["eurtry"] = fx_data.get("eurtry", 0)
    features["eurusd"] = fx_data.get("eurusd", 0)
    return features
