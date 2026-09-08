"""services.ml __init__.py Kapsamlı Modül Dışa Aktarım ve Bütünlük Test Paketi.

GEMINI.md Kural 7 (Modül Dışa Aktarımı) ve Kural 3 (Fail-Closed) standartlarına göre
tüm __all__ sembollerinin paket seviyesinde erişilebilirliğini, tip doğruluğunu
ve içe aktarma bütünlüğünü doğrular.
"""

from __future__ import annotations

import importlib


def test_ml_package_import() -> None:
    """services.ml paketinin temiz ve hatasız içe aktarılabilirliği."""
    ml = importlib.import_module("services.ml")
    assert ml is not None
    assert hasattr(ml, "__all__")
    assert isinstance(ml.__all__, list)
    assert len(ml.__all__) > 0


def test_ml_all_symbols_resolvable() -> None:
    """__all__ içerisindeki her bir sembolün modülde fiilen tanımlı olduğu doğrulanır."""
    ml = importlib.import_module("services.ml")

    unresolved: list[str] = []
    for symbol in ml.__all__:
        if not hasattr(ml, symbol):
            unresolved.append(symbol)

    assert not unresolved, f"__all__ içinde tanımlı ama modülde bulunamayan semboller: {unresolved}"


def test_core_classes_and_objects() -> None:
    """Temel sınıfların ve nesnelerin varlığı ve doğruluğu."""
    import services.ml as ml

    # Core
    assert hasattr(ml, "AdjustedMSELoss")
    assert hasattr(ml, "ModelCalibration")
    assert hasattr(ml, "EnsembleModel")
    assert hasattr(ml, "LightGBMTrainer")
    assert hasattr(ml, "XGBoostModel")

    # Quant/Ranking
    assert hasattr(ml, "LearningToRankModel")
    assert hasattr(ml, "RankingModel")
    assert hasattr(ml, "QlibBIST")

    # RL
    assert hasattr(ml, "RLConfig")
    assert hasattr(ml, "train_rl_agent")
    assert hasattr(ml, "evaluate_rl_agent")


def test_catboost_fallback_safety() -> None:
    """CatBoost opsiyonel modülü yüklü değilse bile modülün fail-open olmadan None ataması."""
    import services.ml as ml

    assert hasattr(ml, "CatBoostModel")
    assert hasattr(ml, "CatBoostConfig")
    # CatBoost yüklüyse sınıf olmalı, değilse None olmalı (NameError fırlatmamalı)
    val = ml.CatBoostModel
    assert val is None or isinstance(val, type)
