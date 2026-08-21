"""
⚠️  DEPRECATED — Bu dosya artık canonical değil.

Canonical production server: app.py (services/api/app.py)
Bu dosya sadece geriye dönük uyumluluk için tutulmaktadır.

Kullanım:
    # Eski (DEPRECATED):
    uvicorn services.api.main:app

    # Yeni (CANONICAL):
    uvicorn services.api.app:app
"""

import sys
import warnings

# Geriye dönük uyumluluk: canonical app'i yeniden dışa aktar
from .app import app  # noqa: F401

warnings.warn(
    "services.api.main is DEPRECATED. Use services.api.app instead. "
    "All endpoints have been migrated to the canonical app.py with /api/v1 prefix.",
    DeprecationWarning,
    stacklevel=2,
)

if __name__ == "__main__":
    print(
        "⚠️  DEPRECATED: services/api/main.py artık canonical değil.\n"
        "   Canonical server: services/api/app.py\n"
        "   Çalıştırmak için: uvicorn services.api.app:app --reload\n",
        file=sys.stderr,
    )
    sys.exit(1)
