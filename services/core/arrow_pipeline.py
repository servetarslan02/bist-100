"""ALPHA BIST — Apache Arrow Veri Boru Hattı Modülü (Enterprise-Grade).

Apache Arrow ve Parquet tabanlı analitik veri işleme ve serileştirme motoru:
- Sıfır kopyalama (zero-copy) bellek aktarımı ve Polars entegrasyonu
- Parquet formatında yüksek sıkıştırmalı ve optimize dosya depolama
- Büyük veri setleri için akışkan ve tembel (lazy) veri kümesi (dataset) tarama
- Parquet dosyalarını birleştirme (merge) ve üst veri (metadata) analizi
- OpenTelemetry span izleme ve yapısal structlog loglama
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.arrow_pipeline")


def otel_trace(span_name: str) -> Callable[..., Any]:
    """Metotları OpenTelemetry span bloğu içine saran dekoratör.

    Args:
        span_name: Oluşturulacak span adı.

    Returns:
        Callable: Sarmalanmış fonksiyon.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class ArrowPipeline:
    """Apache Arrow ve Parquet formatları arasında veri dönüşüm boru hattı."""

    def __init__(self, base_path: str = "data") -> None:
        """Arrow boru hattı çalışma dizinini hazırlar.

        Args:
            base_path: Dosyaların yazılacağı temel dizin yolu.
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        """Boru hattının dize temsili."""
        return f"<ArrowPipeline(base_path='{self.base_path}')>"

    @otel_trace("arrow_pipeline.from_polars")
    def from_polars(self, df: pl.DataFrame | None) -> pa.Table:
        """Polars DataFrame nesnesini Arrow Table formatına dönüştürür.

        Args:
            df: Dönüştürülecek Polars DataFrame.

        Returns:
            pa.Table: Sıfır kopyalamalı Arrow Table nesnesi.

        Raises:
            ValueError: DataFrame None veya geçersiz olduğunda.
        """
        if df is None:
            raise ValueError("Dönüştürülecek Polars DataFrame None olamaz.")
        return df.to_arrow()

    @otel_trace("arrow_pipeline.to_polars")
    def to_polars(self, table: pa.Table | None) -> pl.DataFrame:
        """Arrow Table nesnesini Polars DataFrame formatına çevirir.

        Args:
            table: Dönüştürülecek Arrow Table.

        Returns:
            pl.DataFrame: Oluşturulan Polars DataFrame.

        Raises:
            ValueError: Tablo None ise.
        """
        if table is None:
            raise ValueError("Dönüştürülecek Arrow Table None olamaz.")
        return pl.from_arrow(table)

    @otel_trace("arrow_pipeline.to_parquet")
    def to_parquet(self, table: pa.Table, path: str, compression: str = "snappy") -> str:
        """Arrow Table nesnesini Parquet formatında diske yazar.

        Args:
            table: Diske yazılacak Arrow tablosu.
            path: Göreli veya tam hedef dosya yolu.
            compression: Sıkıştırma algoritması ('snappy', 'gzip', 'zstd', vb.).

        Returns:
            str: Yazılan dosyanın mutlak dosya yolu.

        Raises:
            ValueError: Tablo boş veya geçersizse.
        """
        if table is None or table.num_rows == 0:
            raise ValueError("Diske yazılacak Arrow tablosu boş olamaz.")

        full_path = self.base_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        pq.write_table(table, str(full_path), compression=compression)

        size_mb = full_path.stat().st_size / (1024 * 1024)
        logger.info(
            "parquet_dosyasi_yazildi",
            yol=str(full_path),
            satir=table.num_rows,
            sutun=table.num_columns,
            boyut_mb=round(size_mb, 2),
            sikistirma=compression,
        )

        return str(full_path)

    @otel_trace("arrow_pipeline.read_parquet")
    def read_parquet(self, path: str, columns: list[str] | None = None) -> pa.Table:
        """Parquet dosyasını okuyarak Arrow Table döner.

        Args:
            path: Okunacak Parquet dosyasının yolu.
            columns: Sadece okunmak istenen sütun isimleri listesi.

        Returns:
            pa.Table: Okunan Arrow tablosu.

        Raises:
            FileNotFoundError: Dosya mevcut değilse.
        """
        full_path = self.base_path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Parquet dosyası bulunamadı: {full_path}")

        table = pq.read_table(str(full_path), columns=columns)
        logger.info(
            "parquet_dosyasi_okundu",
            yol=str(full_path),
            satir=table.num_rows,
            sutun=table.num_columns,
        )
        return table

    @otel_trace("arrow_pipeline.scan_parquet")
    def scan_parquet(self, path: str) -> ds.Dataset:
        """Büyük Parquet dosyaları için lazy veri kümesi (Dataset) taraması başlatır.

        Args:
            path: Taranacak Parquet dosya veya dizin yolu.

        Returns:
            ds.Dataset: PyArrow Dataset nesnesi.

        Raises:
            FileNotFoundError: Hedef yol mevcut değilse.
        """
        full_path = self.base_path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Taranacak Parquet yolu bulunamadı: {full_path}")

        return ds.dataset(str(full_path), format="parquet")

    @otel_trace("arrow_pipeline.merge_parquet")
    def merge_parquet(self, input_paths: list[str], output_path: str, compression: str = "snappy") -> str:
        """Birden fazla Parquet dosyasını tek bir Parquet dosyasında birleştirir.

        Args:
            input_paths: Birleştirilecek girdi dosyalarının yolları.
            output_path: Çıktı dosya yolu.
            compression: Çıktı için sıkıştırma formatı.

        Returns:
            str: Birleştirilen dosyanın yolu.

        Raises:
            ValueError: Girdi dosya listesi boş ise.
            FileNotFoundError: Girdi dosyalarından biri mevcut değilse.
        """
        if not input_paths:
            raise ValueError("Birleştirilecek Parquet dosya listesi boş olamaz.")

        tables: list[pa.Table] = []
        for path in input_paths:
            full_path = self.base_path / path
            if not full_path.exists():
                raise FileNotFoundError(f"Birleştirilecek dosya bulunamadı: {full_path}")
            table = pq.read_table(str(full_path))
            tables.append(table)

        merged = pa.concat_tables(tables)
        output_full = self.base_path / output_path
        output_full.parent.mkdir(parents=True, exist_ok=True)

        pq.write_table(merged, str(output_full), compression=compression)

        logger.info(
            "parquet_dosyalari_birlestirildi",
            girdi_sayisi=len(input_paths),
            cikti=str(output_full),
            toplam_satir=merged.num_rows,
        )
        return str(output_full)

    @otel_trace("arrow_pipeline.get_metadata")
    def get_metadata(self, path: str) -> dict[str, Any]:
        """Parquet dosyasının şema ve satır grubu üst verilerini (metadata) inceler.

        Args:
            path: İncelenecek Parquet dosyası yolu.

        Returns:
            dict[str, Any]: Satır sayısı, sütun sayısı, sıkıştırma ve format bilgisi.

        Raises:
            FileNotFoundError: Dosya mevcut değilse.
        """
        full_path = self.base_path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Üst verisi okunacak dosya bulunamadı: {full_path}")

        metadata = pq.read_metadata(str(full_path))

        return {
            "path": str(full_path),
            "rows": metadata.num_rows,
            "columns": metadata.num_columns,
            "row_groups": metadata.num_row_groups,
            "created_by": str(metadata.created_by or "unknown"),
            "format_version": str(metadata.format_version),
            "serialized_size": metadata.serialized_size,
        }


__all__ = [
    "ArrowPipeline",
]
