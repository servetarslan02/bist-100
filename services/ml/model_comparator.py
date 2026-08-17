"""ALPHA BIST — Model Comparator."""
import numpy as np
from typing import Dict, Any, List, Callable
from dataclasses import dataclass
import structlog
logger = structlog.get_logger()

@dataclass
class ModelResult:
    name: str
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    ic: float = 0.0  # Information Coefficient

    def to_dict(self):
        return {"name": self.name, "accuracy": round(self.accuracy, 4), "precision": round(self.precision, 4),
                "recall": round(self.recall, 4), "f1": round(self.f1, 4), "ic": round(self.ic, 4)}

class ModelComparator:
    def compare(self, models: Dict[str, Callable], X_test: np.ndarray, y_test: np.ndarray) -> List[ModelResult]:
        results = []
        for name, predict_fn in models.items():
            try:
                preds = predict_fn(X_test)
                binary_preds = (preds > 0.5).astype(int)
                acc = float(np.mean(binary_preds == y_test))
                tp = np.sum((binary_preds == 1) & (y_test == 1))
                fp = np.sum((binary_preds == 1) & (y_test == 0))
                fn = np.sum((binary_preds == 0) & (y_test == 1))
                precision = tp / (tp + fp) if (tp + fp) > 0 else 0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
                ic = float(np.corrcoef(preds, y_test)[0, 1]) if len(np.unique(y_test)) > 1 else 0
                results.append(ModelResult(name=name, accuracy=acc, precision=precision, recall=recall, f1=f1, ic=ic))
            except Exception as e:
                logger.warning("Model comparison failed", model=name, error=str(e))
        results.sort(key=lambda r: r.f1, reverse=True)
        return results

model_comparator = ModelComparator()
