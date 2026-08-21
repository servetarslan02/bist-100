"""
ALPHA BIST — Data Validation Schemas v1.0 (Pydantic-based)

F-026: Sistematik data quality framework.
Pandera yerine Pydantic kullanılır (zaten projede mevcut).

Her veri tipi için validation schema:
- OHLCV verisi
- Feature vektörü
- Model tahmini
- Sinyal
- Portföy pozisyonu

Kullanım:
    from services.core.data_schemas import validate_ohlcv, validate_features
    validated = validate_ohlcv(raw_data)
"""

import numpy as np
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime
import structlog

logger = structlog.get_logger()


class OHLCVSchema(BaseModel):
    """OHLCV veri doğrulama şeması."""
    date: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @validator("high")
    def high_gte_low(cls, v, values):
        if "low" in values and v < values["low"]:
            raise ValueError("high must be >= low")
        return v

    @validator("open")
    def open_in_range(cls, v, values):
        if "high" in values and "low" in values:
            if v > values["high"] or v < values["low"]:
                raise ValueError("open must be between low and high")
        return v


class FeatureVectorSchema(BaseModel):
    """Feature vektörü doğrulama şeması."""
    ticker: str
    date: datetime
    features: Dict[str, float]

    @validator("features")
    def no_nan_inf(cls, v):
        for key, val in v.items():
            if val is not None and (np.isnan(val) or np.isinf(val)):
                raise ValueError(f"Feature '{key}' contains NaN/Inf")
        return v


class PredictionSchema(BaseModel):
    """Model tahmin doğrulama şeması."""
    model_id: str
    ticker: str
    timestamp: datetime
    predicted_direction: str = Field(pattern="^(UP|DOWN|NEUTRAL)$")
    confidence: float = Field(ge=0.0, le=1.0)
    prediction_horizon: str


class SignalSchema(BaseModel):
    """Sinyal doğrulama şeması."""
    ticker: str
    action: str = Field(pattern="^(BUY|SELL|HOLD)$")
    price: float = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0)
    stop_loss: Optional[float] = Field(default=None, gt=0)
    target: Optional[float] = Field(default=None, gt=0)


class PositionSchema(BaseModel):
    """Pozisyon doğrulama şeması."""
    ticker: str
    direction: str = Field(pattern="^(LONG|SHORT)$")
    quantity: int = Field(gt=0)
    entry_price: float = Field(gt=0)
    current_price: float = Field(ge=0)


def validate_ohlcv(data: Dict[str, Any]) -> Dict[str, Any]:
    """OHLCV verisini doğrula."""
    try:
        validated = OHLCVSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("OHLCV validation failed", error=str(e), data=data)
        return None


def validate_features(data: Dict[str, Any]) -> Dict[str, Any]:
    """Feature vektörünü doğrula."""
    try:
        validated = FeatureVectorSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("Feature validation failed", error=str(e))
        return None


def validate_prediction(data: Dict[str, Any]) -> Dict[str, Any]:
    """Model tahminini doğrula."""
    try:
        validated = PredictionSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("Prediction validation failed", error=str(e))
        return None


def validate_signal(data: Dict[str, Any]) -> Dict[str, Any]:
    """Sinyali doğrula."""
    try:
        validated = SignalSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("Signal validation failed", error=str(e))
        return None


def validate_position(data: Dict[str, Any]) -> Dict[str, Any]:
    """Pozisyonu doğrula."""
    try:
        validated = PositionSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("Position validation failed", error=str(e))
        return None
