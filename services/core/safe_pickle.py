"""ALPHA BIST — Safe Pickle Serialization

Pickle deserialize ederken SHA256 hash doğrulaması yapar.
Model dosyalarının bütünlüğünü korumak için kullanılır.

Kullanım:
    from services.core.safe_pickle import safe_pickle_load, safe_pickle_dump

    # Kaydetme (otomatik hash oluşturur)
    safe_pickle_dump(model, "model.pkl")

    # Yükleme (hash doğrulaması yapar)
    model = safe_pickle_load("model.pkl")
"""

import hashlib
import pickle
from pathlib import Path
from typing import Any

import structlog
import functools
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.safe_pickle")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


@otel_trace("safe_pickle.safe_pickle_dump")
def safe_pickle_dump(obj: Any, path: str, protocol: int = pickle.HIGHEST_PROTOCOL) -> None:
    """Pickle ile kaydet ve SHA256 hash dosyası oluştur.

    Args:
        obj: Kaydedilecek nesne
        path: Dosya yolu
        pickle protocol: Pickle protokolü (varsayılan: en yüksek)
    """
    file_path = Path(path)
    data = pickle.dumps(obj, protocol=protocol)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(data)

    # Hash dosyası oluştur
    hash_path = file_path.with_suffix(file_path.suffix + ".sha256")
    file_hash = hashlib.sha256(data).hexdigest()
    hash_path.write_text(file_hash)

    logger.debug("safe_pickle_dump", path=str(file_path), hash=file_hash[:16])


@otel_trace("safe_pickle.safe_pickle_load")
def safe_pickle_load(path: str, verify_hash: bool = True) -> Any:
    """Pickle yükle — SHA256 hash doğrulaması ile.

    Args:
        path: Dosya yolu
        verify_hash: Hash doğrulaması yap (varsayılan: True)

    Returns:
        Yüklenen nesne

    Raises:
        FileNotFoundError: Dosya bulunamazsa
        ValueError: Hash eşleşmezse
        pickle.UnpicklingError: Pickle bozuksa
    """
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"Model dosyası bulunamadı: {file_path}")

    data = file_path.read_bytes()

    if verify_hash:
        hash_path = file_path.with_suffix(file_path.suffix + ".sha256")
        if hash_path.exists():
            expected_hash = hash_path.read_text().strip()
            actual_hash = hashlib.sha256(data).hexdigest()

            if actual_hash != expected_hash:
                logger.error(
                    "Pickle hash doğrulama başarısız!",
                    path=str(file_path),
                    expected=expected_hash[:16],
                    actual=actual_hash[:16],
                )
                raise ValueError(
                    f"Model dosyası bütünlük doğrulaması başarısız: {file_path}\n"
                    f"Beklenen: {expected_hash[:16]}...\n"
                    f"Gerçek:   {actual_hash[:16]}...\n"
                    f"Dosya değiştirilmiş veya bozulmuş olabilir."
                )
            logger.debug("safe_pickle_load verified", path=str(file_path), hash=actual_hash[:16])
        else:
            logger.warning("Hash dosyası yok — doğrulama atlandı", path=str(file_path))

    try:
        return pickle.loads(data)
    except pickle.UnpicklingError as e:
        logger.error("Pickle yükleme başarısız", path=str(file_path), error=str(e))
        raise
