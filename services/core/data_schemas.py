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

from datetime import datetime
from typing import Any

import numpy as np
import structlog
from pydantic import BaseModel, Field, validator

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
    def high_gte_low(self, v, values):
        if "low" in values and v < values["low"]:
            raise ValueError("high must be >= low")
        return v

    @validator("open")
    def open_in_range(self, v, values):
        if "high" in values and "low" in values and (v > values["high"] or v < values["low"]):
            raise ValueError("open must be between low and high")
        return v


class FeatureVectorSchema(BaseModel):
    """Feature vektörü doğrulama şeması."""

    ticker: str
    date: datetime
    features: dict[str, float]

    @validator("features")
    def no_nan_inf(self, v):
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
    stop_loss: float | None = Field(default=None, gt=0)
    target: float | None = Field(default=None, gt=0)


class PositionSchema(BaseModel):
    """Pozisyon doğrulama şeması."""

    ticker: str
    direction: str = Field(pattern="^(LONG|SHORT)$")
    quantity: int = Field(gt=0)
    entry_price: float = Field(gt=0)
    current_price: float = Field(ge=0)


def validate_ohlcv(data: dict[str, Any]) -> dict[str, Any]:
    """OHLCV verisini doğrula."""
    try:
        validated = OHLCVSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("OHLCV validation failed", error=str(e), data=data)
        return None


def validate_features(data: dict[str, Any]) -> dict[str, Any]:
    """Feature vektörünü doğrula."""
    try:
        validated = FeatureVectorSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("Feature validation failed", error=str(e))
        return None


def validate_prediction(data: dict[str, Any]) -> dict[str, Any]:
    """Model tahminini doğrula."""
    try:
        validated = PredictionSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("Prediction validation failed", error=str(e))
        return None


def validate_signal(data: dict[str, Any]) -> dict[str, Any]:
    """Sinyali doğrula."""
    try:
        validated = SignalSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("Signal validation failed", error=str(e))
        return None


def validate_position(data: dict[str, Any]) -> dict[str, Any]:
    """Pozisyonu doğrula."""
    try:
        validated = PositionSchema(**data)
        return validated.dict()
    except Exception as e:
        logger.warning("Position validation failed", error=str(e))
        return None
