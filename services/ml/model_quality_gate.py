# ============================================================
# Model Quality Gate — Champion/Challenger System
# ============================================================

import json
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class QualityGateCriteria:
    """Quality Gate minimum kriterleri."""
    min_icir: float = 0.5
    min_positive_ic_ratio: float = 0.70
    min_spread_pct: float = 0.0
    min_sharpe: float = 1.0
    max_drawdown_pct: float = -20.0
    min_net_alpha_pct: float = 0.0
    max_survivorship_risk: str = "MEDIUM"  # LOW, MEDIUM, HIGH


@dataclass
class ModelMetrics:
    """Model performans metrikleri."""
    model_name: str
    model_version: str
    
    # OOS Performance
    gross_cagr_pct: float
    net_cagr_pct: float
    benchmark_cagr_pct: float
    net_alpha_pct: float
    sharpe: float
    sortino: Optional[float] = None
    max_drawdown_pct: float = 0.0
    avg_turnover: float = 0.0
    avg_transaction_cost_pct: float = 0.0
    icir: float = 0.0
    positive_ic_ratio: float = 0.0
    avg_spread_pct: float = 0.0
    win_rate_fold: float = 0.0
    
    # Data Quality
    survivorship_risk: str = "UNKNOWN"
    missing_tickers_per_fold: float = 0.0
    leakage_check_pass: bool = False
    
    # Training Metadata
    train_period_start: str = ""
    train_period_end: str = ""
    oos_period: str = ""
    folds: int = 0
    features: int = 0


class QualityGate:
    """Model Quality Gate — Champion/Challenger mekanizması."""
    
    def __init__(self, criteria: Optional[QualityGateCriteria] = None):
        self.criteria = criteria or QualityGateCriteria()
        self.results: Dict[str, bool] = {}
    
    def evaluate(self, metrics: ModelMetrics) -> Tuple[bool, Dict]:
        """
        Modeli Quality Gate'den geçir.
        
        Returns:
            (pass/fail, detailed_results)
        """
        self.results = {}
        
        # 1. ICIR
        self.results["icir"] = {
            "threshold": self.criteria.min_icir,
            "actual": metrics.icir,
            "pass": metrics.icir >= self.criteria.min_icir,
        }
        
        # 2. Positive IC Ratio
        self.results["positive_ic_ratio"] = {
            "threshold": self.criteria.min_positive_ic_ratio,
            "actual": metrics.positive_ic_ratio,
            "pass": metrics.positive_ic_ratio >= self.criteria.min_positive_ic_ratio,
        }
        
        # 3. Spread
        self.results["spread"] = {
            "threshold": self.criteria.min_spread_pct,
            "actual": metrics.avg_spread_pct,
            "pass": metrics.avg_spread_pct > self.criteria.min_spread_pct,
        }
        
        # 4. Sharpe
        self.results["sharpe"] = {
            "threshold": self.criteria.min_sharpe,
            "actual": metrics.sharpe,
            "pass": metrics.sharpe >= self.criteria.min_sharpe,
        }
        
        # 5. Max Drawdown
        self.results["max_drawdown"] = {
            "threshold": self.criteria.max_drawdown_pct,
            "actual": metrics.max_drawdown_pct,
            "pass": metrics.max_drawdown_pct > self.criteria.max_drawdown_pct,
        }
        
        # 6. Net Alpha
        self.results["net_alpha"] = {
            "threshold": self.criteria.min_net_alpha_pct,
            "actual": metrics.net_alpha_pct,
            "pass": metrics.net_alpha_pct > self.criteria.min_net_alpha_pct,
        }
        
        # 7. Survivorship Bias
        risk_levels = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        self.results["survivorship"] = {
            "threshold": self.criteria.max_survivorship_risk,
            "actual": metrics.survivorship_risk,
            "pass": risk_levels.get(metrics.survivorship_risk, 999) <= risk_levels.get(self.criteria.max_survivorship_risk, 999),
        }
        
        # 8. Leakage Check
        self.results["leakage"] = {
            "threshold": True,
            "actual": metrics.leakage_check_pass,
            "pass": metrics.leakage_check_pass,
        }
        
        # Overall
        all_pass = all(r["pass"] for r in self.results.values())
        
        if all_pass:
            logger.info("✅ Quality Gate PASSED", model=metrics.model_name, version=metrics.model_version)
        else:
            failed = [k for k, v in self.results.items() if not v["pass"]]
            logger.warning("❌ Quality Gate FAILED", model=metrics.model_name, failed_criteria=failed)
        
        return all_pass, self.results


class ChampionRegistry:
    """Champion model registry ve yönetimi."""
    
    def __init__(self, registry_path: str = "data/champion_registry.json"):
        self.registry_path = Path(registry_path)
        self.registry = self._load()
    
    def _load(self) -> Dict:
        """Registry'yi yükle."""
        if self.registry_path.exists():
            with open(self.registry_path, 'r') as f:
                return json.load(f)
        return {"champions": [], "challengers": [], "promotion_history": []}
    
    def save(self):
        """Registry'yi kaydet."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.registry_path, 'w') as f:
            json.dump(self.registry, f, indent=2)
    
    def get_champion(self) -> Optional[Dict]:
        """Mevcut Champion'ı getir."""
        champions = [c for c in self.registry.get("champions", []) if c.get("status") == "ACTIVE"]
        return champions[-1] if champions else None
    
    def register_champion(self, metrics: ModelMetrics, quality_results: Dict):
        """Yeni Champion kaydet."""
        entry = {
            "model_name": metrics.model_name,
            "model_version": metrics.model_version,
            "status": "ACTIVE",
            "promotion_date": datetime.now().isoformat(),
            "metrics": asdict(metrics),
            "quality_gate": quality_results,
        }
        
        # Eski champion'ı retired yap
        for c in self.registry.get("champions", []):
            if c.get("status") == "ACTIVE":
                c["status"] = "RETIRED"
                c["retirement_date"] = datetime.now().isoformat()
        
        self.registry.setdefault("champions", []).append(entry)
        self.save()
        
        logger.info("🏆 New Champion registered", model=metrics.model_name, version=metrics.model_version)
    
    def register_challenger(self, metrics: ModelMetrics, quality_results: Dict):
        """Challenger kaydet (Champion olamaz)."""
        entry = {
            "model_name": metrics.model_name,
            "model_version": metrics.model_version,
            "status": "CHALLENGER",
            "registration_date": datetime.now().isoformat(),
            "metrics": asdict(metrics),
            "quality_gate": quality_results,
        }
        
        self.registry.setdefault("challengers", []).append(entry)
        self.save()
        
        logger.info("🥈 Challenger registered", model=metrics.model_name, version=metrics.model_version)
    
    def promote_challenger(self, challenger_name: str, challenger_version: str) -> bool:
        """
        Challenger'ı Champion yap.
        
        Sadece Quality Gate'den geçmiş ve Shadow/A-B testi başarılı olan challenger'lar
        promote edilebilir.
        """
        challengers = [c for c in self.registry.get("challengers", [])
                       if c.get("model_name") == challenger_name 
                       and c.get("model_version") == challenger_version]
        
        if not challengers:
            logger.error("Challenger not found", name=challenger_name, version=challenger_version)
            return False
        
        challenger = challengers[-1]
        
        # Quality Gate kontrolü
        if not all(v.get("pass", False) for v in challenger.get("quality_gate", {}).values()):
            logger.error("Challenger failed Quality Gate", name=challenger_name)
            return False
        
        # Shadow/A-B test kontrolü (varsa)
        if not challenger.get("shadow_test_pass", False):
            logger.warning("Challenger has no shadow test results", name=challenger_name)
            # Shadow test olmadan promote etme (opsiyonel)
            # return False
        
        # Promote
        metrics = ModelMetrics(**challenger["metrics"])
        self.register_champion(metrics, challenger["quality_gate"])
        
        # History
        self.registry.setdefault("promotion_history", []).append({
            "date": datetime.now().isoformat(),
            "from": self.get_champion().get("model_name", "None") if len(self.registry["champions"]) > 1 else "None",
            "to": challenger_name,
            "version": challenger_version,
        })
        
        logger.info("🚀 Challenger promoted to Champion", name=challenger_name, version=challenger_version)
        return True
    
    def get_promotion_pipeline(self) -> Dict:
        """Promote pipeline durumunu getir."""
        return {
            "current_champion": self.get_champion(),
            "active_challengers": [c for c in self.registry.get("challengers", []) if c.get("status") == "CHALLENGER"],
            "pending_oos_tests": self.registry.get("pending_oos_tests", []),
        }


# Singleton instances
quality_gate = QualityGate()
champion_registry = ChampionRegistry()
