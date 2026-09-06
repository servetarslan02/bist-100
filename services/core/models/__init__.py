"""ALPHA BIST — Core Models Package & Re-export Hub.

Bu paket hem `models.py` içindeki kurumsal domain modellerini (Pydantic v2)
dışa aktarır hem de alt modülleri (setup_paper_db vb.) destekler.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_models_file = Path(__file__).parent.parent / "models.py"
if _models_file.exists():
    _spec = importlib.util.spec_from_file_location("services.core._domain_models_file", _models_file)
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        __all__ = getattr(_mod, "__all__", [attr for attr in dir(_mod) if not attr.startswith("_")])
        for _attr in __all__:
            globals()[_attr] = getattr(_mod, _attr)
else:
    __all__ = []
