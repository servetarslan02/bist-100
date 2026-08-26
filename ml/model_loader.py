"""
ALPHA BIST — ML Model Loader v1.0

6. Quant Probability Proxy yerine gerçek eğitilmiş ML modeli bağla.
Model dosyasından yükler, inference yapar.
"""

import pickle
import orjson
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from datetime import datetime
import structlog

logger = structlog.get_logger()


class MLModelLoader:
    """
    Eğitilmiş ML modeli yükler ve inference yapar.
    Gerçek model varsa kullanır, yoksa Quant Probability Proxy döndürür.
    """

    def __init__(self):
        self._models: Dict[str, Any] = {}
        self._model_configs: Dict[str, Dict] = {}
        self._loaded = False

    def load_models(self, model_dir: str = "ml/saved_models") -> int:
        """Tüm eğitilmiş modelleri yükle."""
        model_path = Path(model_dir)
        if not model_path.exists():
            logger.warning("Model directory not found", path=model_dir)
            return 0

        loaded = 0
        for model_file in model_path.glob("*/model.pkl"):
            model_name = model_file.parent.name
            try:
                # Hash doğrulama (pickle deserilization güvenliği)
                hash_file = model_file.parent / "model.pkl.sha256"
                if hash_file.exists():
                    import hashlib
                    expected_hash = hash_file.read_text().strip()
                    actual_hash = hashlib.sha256(model_file.read_bytes()).hexdigest()
                    if actual_hash != expected_hash:
                        logger.error("Model hash MISMATCH — possible tampering",
                                   name=model_name, expected=expected_hash[:16], actual=actual_hash[:16])
                        continue

                with open(model_file, "rb") as f:
                    model = pickle.load(f)
                self._models[model_name] = model
                loaded += 1

                # Config varsa yükle
                config_file = model_file.parent / "config.json"
                if config_file.exists():
                    with open(config_file) as f:
                        self._model_configs[model_name] = orjson.loads(f.read())

                logger.info("Model loaded", name=model_name)
            except Exception as e:
                logger.warning("Model load failed", name=model_name, error=str(e))

        self._loaded = loaded > 0
        logger.info("ML models loaded", count=loaded)
        return loaded

    def predict(self, model_name: str, features: Dict[str, float]) -> Optional[Dict[str, float]]:
        """
        Tek bir model ile tahmin yap.

        Returns: {"return_5d": 3.2, "direction": 1, "confidence": 0.75} veya None
        """
        model = self._models.get(model_name)
        if not model:
            return None

        config = self._model_configs.get(model_name, {})
        feature_names = config.get("features", [])

        if not feature_names:
            return None

        # Feature vektörü oluştur
        X = np.array([[features.get(f, 0) for f in feature_names]])

        try:
            # Tahmin
            if hasattr(model, "predict_proba"):
                # Classification
                proba = model.predict_proba(X)[0]
                pred = model.predict(X)[0]
                return {
                    "prediction": float(pred),
                    "probability_positive": float(proba[1]) if len(proba) > 1 else float(proba[0]),
                    "confidence": float(max(proba)),
                }
            else:
                # Regression
                pred = model.predict(X)[0]
                return {
                    "prediction": float(pred),
                    "confidence": 0.5,  # Varsayılan
                }

        except Exception as e:
            logger.warning("Prediction failed", model=model_name, error=str(e))
            return None

    def predict_ensemble(self, features: Dict[str, float]) -> Dict[str, float]:
        """
        Tüm modellerden tahmin al ve birleştir.

        Returns: {"return_5d": 3.2, "direction": 1, "confidence": 0.75}
        """
        if not self._loaded:
            return self._quant_proxy(features)

        predictions = {}
        for name, model in self._models.items():
            pred = self.predict(name, features)
            if pred:
                predictions[name] = pred

        if not predictions:
            return self._quant_proxy(features)

        # Ensemble: ağırlıklı ortalama
        values = [p["prediction"] for p in predictions.values()]
        confidences = [p.get("confidence", 0.5) for p in predictions.values()]

        # Confidence ağırlıklı ortalama
        if sum(confidences) > 0:
            weights = np.array(confidences) / sum(confidences)
            ensemble_pred = np.average(values, weights=weights)
        else:
            ensemble_pred = np.mean(values)

        # Direction
        direction = 1 if ensemble_pred > 0 else -1

        # Confidence (model agreement)
        if len(values) > 1:
            agreement = 1 - np.std(values) / (abs(np.mean(values)) + 1e-6)
            confidence = max(0, min(1, agreement))
        else:
            confidence = confidences[0] if confidences else 0.5

        return {
            "prediction": float(ensemble_pred),
            "direction": direction,
            "confidence": float(confidence),
            "model_count": len(predictions),
            "source": "ml_ensemble",
        }

    def _quant_proxy(self, features: Dict[str, float]) -> Dict[str, float]:
        """
        Quant Probability Proxy — gerçek model yoksa kullanılır.
        Feature-based heuristic.
        """
        mom = features.get("roc_20d", 0)
        vol_z = features.get("volume_zscore", 0)
        rsi = features.get("rsi_14", 50)

        score = 50
        if mom > 5: score += min(mom * 2, 20)
        elif mom < -5: score += max(mom * 2, -20)
        if vol_z > 2: score += min(vol_z * 5, 15)
        if 30 < rsi < 70: score += 5
        elif rsi < 25: score += 10
        elif rsi > 75: score -= 10

        prediction = (score - 50) / 10  # -5 ile +5 arası

        return {
            "prediction": float(prediction),
            "direction": 1 if prediction > 0 else -1,
            "confidence": 0.3,  # Düşük güven (proxy)
            "model_count": 0,
            "source": "quant_proxy",
        }

    def get_status(self) -> Dict:
        """Model durumu."""
        return {
            "loaded": self._loaded,
            "model_count": len(self._models),
            "models": list(self._models.keys()),
            "configs": {k: v.get("metrics", {}) for k, v in self._model_configs.items()},
        }


# Singleton
ml_model_loader = MLModelLoader()
