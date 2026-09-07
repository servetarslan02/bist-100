"""ALPHA BIST — Core Models Package & Re-export Hub.

Bu paket hem `models.py` içindeki kurumsal domain modellerini (Pydantic v2)
dışa aktarır hem de alt modülleri (`setup_paper_db` vb.) re-export eder.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from services.core.models.setup_paper_db import (
    clear_paper_trade_duckdb,
    export_paper_db_schema_to_orjson_bytes,
    export_paper_db_schema_to_polars,
    setup_duckdb_tables,
    setup_tables,
)

_paper_db_exports: list[str] = [
    "clear_paper_trade_duckdb",
    "export_paper_db_schema_to_orjson_bytes",
    "export_paper_db_schema_to_polars",
    "setup_duckdb_tables",
    "setup_tables",
]

_models_file = Path(__file__).parent.parent / "models.py"
_domain_exports: list[str] = []
if _models_file.exists():
    _spec = importlib.util.spec_from_file_location("services.core._domain_models_file", _models_file)
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _domain_exports = getattr(_mod, "__all__", [attr for attr in dir(_mod) if not attr.startswith("_")])
        for _attr in _domain_exports:
            globals()[_attr] = getattr(_mod, _attr)

__all__: list[str] = sorted(list(set(_domain_exports + _paper_db_exports)))

