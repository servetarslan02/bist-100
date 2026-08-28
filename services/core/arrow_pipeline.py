"""
ALPHA BIST — PyArrow Data Pipeline

Apache Arrow tabanlı veri pipeline'ı.

Özellikler:
- Zero-copy veri aktarımı
- Columnar format (analitik sorgular için optimize)
- Parquet okuma/yazma
- Polars ile uyumlu

Kullanım:
    from services.core.arrow_pipeline import ArrowPipeline

    pipeline = ArrowPipeline()

    # DataFrame'den Arrow'a
    arrow_table = pipeline.from_polars(df)

    # Parquet'e yaz
    pipeline.to_parquet(arrow_table, "data/output.parquet")

    # Parquet'ten oku
    table = pipeline.read_parquet("data/output.parquet")
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl
    import pyarrow as pa

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.arrow_pipeline")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)
        return wrapper
    return decorator


class ArrowPipeline:
    """Apache Arrow tabanlı veri pipeline'ı."""

    def __init__(self, base_path: str = "data"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    @otel_trace("arrow_pipeline.from_polars")
    def from_polars(self, df) -> pa.Table:
        """Polars DataFrame'den Arrow Table'a çevir."""
        try:
            return df.to_arrow()
        except ImportError:
            logger.error("PyArrow not installed")
            raise

    @otel_trace("arrow_pipeline.to_polars")
    def to_polars(self, table) -> pl.DataFrame:
        """Arrow Table'dan Polars DataFrame'e çevir."""
        try:
            import polars as pl

            return pl.from_arrow(table)
        except ImportError:
            logger.error("Polars not installed")
            raise

    @otel_trace("arrow_pipeline.to_parquet")
    def to_parquet(self, table, path: str, compression: str = "snappy") -> str:
        """Arrow Table'ı Parquet dosyasına yaz."""
        try:
            import pyarrow.parquet as pq

            full_path = self.base_path / path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            pq.write_table(table, str(full_path), compression=compression)

            size_mb = full_path.stat().st_size / (1024 * 1024)
            logger.info(
                "Parquet written",
                path=str(full_path),
                rows=table.num_rows,
                cols=table.num_columns,
                size_mb=round(size_mb, 2),
            )

            return str(full_path)
        except ImportError:
            logger.error("PyArrow not installed")
            raise

    @otel_trace("arrow_pipeline.read_parquet")
    def read_parquet(self, path: str, columns: list[str] | None = None):
        """Parquet dosyasından Arrow Table oku."""
        try:
            import pyarrow.parquet as pq

            full_path = self.base_path / path
            table = pq.read_table(str(full_path), columns=columns)

            logger.info("Parquet read", path=str(full_path), rows=table.num_rows, cols=table.num_columns)

            return table
        except ImportError:
            logger.error("PyArrow not installed")
            raise

    @otel_trace("arrow_pipeline.scan_parquet")
    def scan_parquet(self, path: str):
        """Parquet dosyasını lazy olarak tara (büyük dosyalar için)."""
        try:
            import pyarrow.dataset as ds

            full_path = self.base_path / path
            dataset = ds.dataset(str(full_path), format="parquet")

            return dataset
        except ImportError:
            logger.error("PyArrow not installed")
            raise

    @otel_trace("arrow_pipeline.merge_parquet")
    def merge_parquet(self, input_paths: list[str], output_path: str) -> str:
        """Birden fazla Parquet dosyasını birleştir."""
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            tables = []
            for path in input_paths:
                full_path = self.base_path / path
                table = pq.read_table(str(full_path))
                tables.append(table)

            merged = pa.concat_tables(tables)
            output_full = self.base_path / output_path
            output_full.parent.mkdir(parents=True, exist_ok=True)

            pq.write_table(merged, str(output_full))

            logger.info("Parquet merged", inputs=len(input_paths), output=str(output_full), rows=merged.num_rows)

            return str(output_full)
        except ImportError:
            logger.error("PyArrow not installed")
            raise

    @otel_trace("arrow_pipeline.get_metadata")
    def get_metadata(self, path: str) -> dict[str, Any]:
        """Parquet dosyası metadata'sını al."""
        try:
            import pyarrow.parquet as pq

            full_path = self.base_path / path
            metadata = pq.read_metadata(str(full_path))

            return {
                "path": str(full_path),
                "rows": metadata.num_rows,
                "columns": metadata.num_columns,
                "row_groups": metadata.num_row_groups,
                "created_by": metadata.created_by,
                "format_version": metadata.format_version,
                "serialized_size": metadata.serialized_size,
            }
        except ImportError:
            logger.error("PyArrow not installed")
            raise
