"""ALPHA BIST — Apache Arrow Veri Boru Hattı Modülü (Enterprise-Grade).

Apache Arrow ve Parquet tabanlı analitik veri işleme ve serileştirme motoru:
- Sıfır kopyalama (zero-copy) bellek aktarımı ve Polars entegrasyonu
- Parquet formatında yüksek sıkıştırmalı ve optimize dosya depolama
- Büyük veri setleri için akışkan ve tembel (lazy) veri kümesi (dataset) tarama
- Parquet dosyalarını şema evrimi (schema evolution) destekli birleştirme (merge)
- OpenTelemetry span izleme ve yapısal structlog loglama
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import polars as pl
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import structlog
from opentelemetry import trace

from services.core.otel import otel_trace

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.arrow_pipeline")

# Desteklenen Sıkıştırma Formatları ve Sabitler
DEFAULT_BASE_PATH = "data"
DEFAULT_COMPRESSION = "snappy"
VALID_COMPRESSIONS = frozenset({"snappy", "gzip", "brotli", "lz4", "zstd", "none", None})


class ArrowPipeline:
    """Apache Arrow, Parquet ve DuckDB arasında kurumsal analitik veri boru hattı."""

    def __init__(self, base_path: str = DEFAULT_BASE_PATH) -> None:
        """Arrow boru hattı çalışma dizinini hazırlar.

        Args:
            base_path: Dosyaların yazılacağı temel dizin yolu.
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        """Boru hattının açıklayıcı dize temsili."""
        return f"ArrowPipeline(base_path={str(self.base_path)!r})"

    def _resolve_path(self, path: str | Path) -> Path:
        """Göreli veya mutlak dosya yolunu güvenli biçimde çözümler.

        Args:
            path: Çözümlenecek dosya yolu.

        Returns:
            Path: Çözümlenmiş dosya yolu nesnesi.
        """
        p = Path(path)
        if p.is_absolute():
            return p
        return self.base_path / p

    @otel_trace("arrow_pipeline.from_polars")
    def from_polars(self, df: pl.DataFrame | None) -> pa.Table:
        """Polars DataFrame nesnesini sıfır kopyalamalı Arrow Table formatına dönüştürür.

        Args:
            df: Dönüştürülecek Polars DataFrame.

        Returns:
            pa.Table: Arrow Table nesnesi.

        Raises:
            ValueError: DataFrame None olduğunda.
            TypeError: Girdi tipi pl.DataFrame olmadığında.
        """
        if df is None:
            raise ValueError("Dönüştürülecek Polars DataFrame None olamaz.")
        if not isinstance(df, pl.DataFrame):
            raise TypeError(f"Beklenen tip pl.DataFrame, alınan: {type(df).__name__}")
        return df.to_arrow()

    @otel_trace("arrow_pipeline.to_polars")
    def to_polars(self, table: pa.Table | pa.RecordBatch | None) -> pl.DataFrame:
        """Arrow Table veya RecordBatch nesnesini Polars DataFrame formatına çevirir.

        Args:
            table: Dönüştürülecek Arrow Table veya RecordBatch.

        Returns:
            pl.DataFrame: Oluşturulan Polars DataFrame.

        Raises:
            ValueError: Tablo None ise.
            TypeError: Girdi tipi pa.Table veya pa.RecordBatch olmadığında.
        """
        if table is None:
            raise ValueError("Dönüştürülecek Arrow Table None olamaz.")
        if not isinstance(table, (pa.Table, pa.RecordBatch)):
            raise TypeError(f"Beklenen tip pa.Table veya pa.RecordBatch, alınan: {type(table).__name__}")
        return pl.from_arrow(table)

    @otel_trace("arrow_pipeline.to_parquet")
    def to_parquet(
        self,
        table: pa.Table | pl.DataFrame,
        path: str,
        compression: str = DEFAULT_COMPRESSION,
    ) -> str:
        """Arrow Table veya Polars DataFrame nesnesini Parquet formatında atomik olarak diske yazar.

        Yazma işlemi geçici bir dosyaya yapılıp ardından atomik olarak hedefe taşınır; böylece
        yarıda kesilme veya elektrik/süreç kesintilerinde dosya bozulması (corruption) önlenir.

        Args:
            table: Diske yazılacak Arrow Table veya Polars DataFrame nesnesi.
            path: Göreli veya tam hedef dosya yolu.
            compression: Sıkıştırma algoritması ('snappy', 'gzip', 'brotli', 'lz4', 'zstd', 'none').

        Returns:
            str: Yazılan dosyanın mutlak dosya yolu.

        Raises:
            ValueError: Tablo boş, geçersiz veya sıkıştırma formatı hatalıysa.
            TypeError: Desteklenmeyen veri tipi gönderildiğinde.
        """
        if compression not in VALID_COMPRESSIONS:
            raise ValueError(
                f"Geçersiz sıkıştırma formatı: {compression!r}. Desteklenenler: {sorted(c for c in VALID_COMPRESSIONS if c)}"
            )

        if isinstance(table, pl.DataFrame):
            arrow_table = table.to_arrow()
        elif isinstance(table, pa.Table):
            arrow_table = table
        else:
            raise TypeError(f"Yazılacak veri pa.Table veya pl.DataFrame olmalıdır, alınan: {type(table).__name__}")

        if arrow_table is None or arrow_table.num_rows == 0:
            raise ValueError("Diske yazılacak tablo boş olamaz.")

        full_path = self._resolve_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomik yazma koruması: geçici dosyaya yazıp atomik replace yap
        temp_path = full_path.with_name(f"{full_path.name}.tmp.{uuid.uuid4().hex[:8]}")
        try:
            pq.write_table(arrow_table, str(temp_path), compression=compression)
            os.replace(temp_path, full_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

        size_mb = full_path.stat().st_size / (1024 * 1024)
        logger.info(
            "parquet_dosyasi_yazildi",
            yol=str(full_path),
            satir=arrow_table.num_rows,
            sutun=arrow_table.num_columns,
            boyut_mb=round(size_mb, 2),
            sikistirma=compression,
        )

        return str(full_path)

    @otel_trace("arrow_pipeline.read_parquet")
    def read_parquet(
        self,
        path: str,
        columns: list[str] | None = None,
        filters: Sequence[tuple[str, str, Any]] | list[list[tuple[str, str, Any]]] | None = None,
    ) -> pa.Table:
        """Parquet dosyasını sütun ve koşul iteleme (predicate pushdown) ile okuyarak Arrow Table döndürür.

        Args:
            path: Okunacak Parquet dosyasının yolu.
            columns: Sadece okunmak istenen sütun isimleri listesi (None = tüm sütunlar).
            filters: PyArrow filtreleme kriterleri (örn. [("ticker", "=", "EREGL")]).

        Returns:
            pa.Table: Okunan Arrow tablosu.

        Raises:
            FileNotFoundError: Dosya mevcut değilse.
            ValueError: Parquet dosyası bozuk veya geçersizse.
        """
        full_path = self._resolve_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"Parquet dosyası bulunamadı: {full_path}")

        try:
            table = pq.read_table(str(full_path), columns=columns, filters=filters)
        except Exception as e:
            logger.error("parquet_dosyasi_okuma_hatasi", yol=str(full_path), hata=str(e))
            raise ValueError(f"Parquet dosyası okunamadı veya bozuk: {full_path}") from e

        logger.info(
            "parquet_dosyasi_okundu",
            yol=str(full_path),
            satir=table.num_rows,
            sutun=table.num_columns,
        )
        return table

    @otel_trace("arrow_pipeline.scan_parquet")
    def scan_parquet(self, path: str) -> ds.Dataset:
        """Büyük Parquet dosyaları için akışkan ve tembel (lazy) PyArrow Dataset taraması başlatır.

        Args:
            path: Taranacak Parquet dosya veya dizin yolu.

        Returns:
            ds.Dataset: PyArrow Dataset nesnesi.

        Raises:
            FileNotFoundError: Hedef yol mevcut değilse.
        """
        full_path = self._resolve_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"Taranacak Parquet yolu bulunamadı: {full_path}")

        return ds.dataset(str(full_path), format="parquet")

    @otel_trace("arrow_pipeline.scan_polars")
    def scan_polars(self, path: str) -> pl.LazyFrame:
        """Parquet dosyası üzerinde optimize Polars LazyFrame tarayıcısı oluşturur.

        Args:
            path: Taranacak Parquet dosya yolu.

        Returns:
            pl.LazyFrame: Tembel değerlendirme yapan Polars LazyFrame nesnesi.

        Raises:
            FileNotFoundError: Hedef yol mevcut değilse.
        """
        full_path = self._resolve_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"Taranacak Parquet yolu bulunamadı: {full_path}")

        return pl.scan_parquet(str(full_path))

    @otel_trace("arrow_pipeline.query_parquet_with_duckdb")
    def query_parquet_with_duckdb(
        self,
        path: str,
        sql_query: str = "SELECT * FROM parquet_data",
    ) -> pl.DataFrame:
        """DuckDB motoru ile Parquet dosyasını sıfır kopyalama ve vektörize SQL ile sorgular.

        SQL sorgusu içinde hedef Parquet dosyasına `parquet_data` tablosu olarak başvurulur.

        Args:
            path: Sorgulanacak Parquet dosyasının yolu.
            sql_query: Çalıştırılacak DuckDB SQL sorgusu (varsayılan: "SELECT * FROM parquet_data").

        Returns:
            pl.DataFrame: Sorgu sonucu Polars DataFrame olarak döner.

        Raises:
            FileNotFoundError: Hedef Parquet dosyası mevcut değilse.
        """
        full_path = self._resolve_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"Sorgulanacak Parquet dosyası bulunamadı: {full_path}")

        conn = duckdb.connect()
        try:
            # parquet_data görünümü oluştur (dosya yolunu güvenle escape et)
            escaped_path = str(full_path).replace("'", "''")
            conn.execute(f"CREATE VIEW parquet_data AS SELECT * FROM read_parquet('{escaped_path}');")
            arrow_result = conn.execute(sql_query).arrow()
            return pl.from_arrow(arrow_result)
        finally:
            conn.close()

    @otel_trace("arrow_pipeline.merge_parquet")
    def merge_parquet(
        self,
        input_paths: list[str],
        output_path: str,
        compression: str = DEFAULT_COMPRESSION,
    ) -> str:
        """Birden fazla Parquet dosyasını şema evrimi desteğiyle tek bir dosyada birleştirir.

        Args:
            input_paths: Birleştirilecek girdi dosyalarının yolları.
            output_path: Çıktı dosya yolu.
            compression: Çıktı için sıkıştırma formatı.

        Returns:
            str: Birleştirilen dosyanın tam yolu.

        Raises:
            ValueError: Girdi dosya listesi boş ise veya sıkıştırma geçersizse.
            FileNotFoundError: Girdi dosyalarından biri mevcut değilse.
        """
        if not input_paths:
            raise ValueError("Birleştirilecek Parquet dosya listesi boş olamaz.")
        if compression not in VALID_COMPRESSIONS:
            raise ValueError(f"Geçersiz sıkıştırma formatı: {compression!r}")

        tables: list[pa.Table] = []
        for path in input_paths:
            full_path = self._resolve_path(path)
            if not full_path.exists():
                raise FileNotFoundError(f"Birleştirilecek dosya bulunamadı: {full_path}")
            table = pq.read_table(str(full_path))
            if table.num_rows > 0:
                tables.append(table)

        if not tables:
            raise ValueError("Birleştirilecek dosyalarda geçerli veri satırı bulunamadı.")

        # Şema farklılıklarını tolere etmek için permissive birleştirme
        try:
            merged = pa.concat_tables(tables, promote_options="permissive")
        except TypeError:
            # PyArrow eski sürümleri için fallback
            merged = pa.concat_tables(tables, promote=True)

        return self.to_parquet(merged, output_path, compression=compression)

    @otel_trace("arrow_pipeline.get_metadata")
    def get_metadata(self, path: str) -> dict[str, Any]:
        """Parquet dosyasının şema, sıkıştırma ve satır grubu üst verilerini inceler.

        Args:
            path: İncelenecek Parquet dosyası yolu.

        Returns:
            dict[str, Any]: Satır sayısı, sütun sayısı, şema tipleri ve format bilgisi.

        Raises:
            FileNotFoundError: Dosya mevcut değilse.
        """
        full_path = self._resolve_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"Üst verisi okunacak dosya bulunamadı: {full_path}")

        metadata = pq.read_metadata(str(full_path))
        schema = metadata.schema.to_arrow_schema()

        return {
            "path": str(full_path),
            "rows": metadata.num_rows,
            "columns": metadata.num_columns,
            "row_groups": metadata.num_row_groups,
            "created_by": str(metadata.created_by or "unknown"),
            "format_version": str(metadata.format_version),
            "serialized_size": metadata.serialized_size,
            "column_names": schema.names,
            "schema_types": {field.name: str(field.type) for field in schema},
        }


# Singleton örneği
arrow_pipeline = ArrowPipeline()

__all__ = [
    "DEFAULT_BASE_PATH",
    "DEFAULT_COMPRESSION",
    "VALID_COMPRESSIONS",
    "ArrowPipeline",
    "arrow_pipeline",
]

