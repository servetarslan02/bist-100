"""ALPHA BIST — Apache Arrow Veri Boru Hattı Modülü (Enterprise-Grade).

Apache Arrow, Polars, Parquet ve DuckDB tabanlı yüksek başarımlı analitik veri boru hattı:
- Sıfır kopyalama (zero-copy) bellek aktarımı ve Polars/Arrow iki yönlü dönüşüm motoru
- Parquet formatında yüksek sıkıştırmalı, şema evrimli ve atomik güvenli dosya yazımı
- Büyük veri setleri için akışkan PyArrow Dataset ve Polars LazyFrame tembel tarayıcıları
- DuckDB vektörize SQL motoru ile Parquet dosyaları üzerinde parametrik SQL analitiği
- Bölümlenmiş veri setleri (partitioned datasets) ve şema evrimi destekli Parquet birleştirme
- Reentrant thread-safety kilit mimarisi, OpenTelemetry span izleme ve yapısal structlog loglama
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

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

# =====================================================
# DESTEKLENEN SIKIŞTIRMA FORMATLARI VE SABİTLER
# =====================================================

DEFAULT_BASE_PATH: Final[str] = "data"
DEFAULT_COMPRESSION: Final[str] = "snappy"
DEFAULT_SQL_QUERY: Final[str] = "SELECT * FROM parquet_data"
VALID_COMPRESSIONS: Final[frozenset[str | None]] = frozenset(
    {"snappy", "gzip", "brotli", "lz4", "zstd", "none", None}
)


class ArrowPipeline:
    """Apache Arrow, Parquet, Polars ve DuckDB arasında kurumsal analitik veri boru hattı."""

    def __init__(self, base_path: str = DEFAULT_BASE_PATH) -> None:
        """Arrow boru hattı çalışma dizinini ve eşzamanlılık kilidini hazırlar.

        Args:
            base_path: Dosyaların yazılacağı temel dizin yolu.
        """
        self._lock: threading.RLock = threading.RLock()
        self.base_path = Path(base_path)
        with self._lock:
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
    def from_polars(self, df: pl.DataFrame | pl.LazyFrame | None) -> pa.Table:
        """Polars DataFrame veya LazyFrame nesnesini sıfır kopyalamalı Arrow Table formatına dönüştürür.

        Args:
            df: Dönüştürülecek Polars DataFrame veya LazyFrame.

        Returns:
            pa.Table: Arrow Table nesnesi.

        Raises:
            ValueError: DataFrame None olduğunda.
            TypeError: Girdi tipi pl.DataFrame veya pl.LazyFrame olmadığında.
        """
        if df is None:
            raise ValueError("Dönüştürülecek Polars DataFrame None olamaz.")
        if isinstance(df, pl.LazyFrame):
            df = df.collect()
        elif not isinstance(df, pl.DataFrame):
            raise TypeError(f"Beklenen tip pl.DataFrame veya pl.LazyFrame, alınan: {type(df).__name__}")
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
        table: pa.Table | pl.DataFrame | pl.LazyFrame | pa.RecordBatch,
        path: str,
        compression: str = DEFAULT_COMPRESSION,
    ) -> str:
        """Arrow Table, RecordBatch veya Polars veri nesnesini Parquet formatında atomik olarak diske yazar.

        Yazma işlemi geçici bir dosyaya yapılıp ardından atomik olarak hedefe taşınır; böylece
        yarıda kesilme veya işletim sistemi kesintilerinde dosya bozulması (corruption) önlenir.

        Args:
            table: Diske yazılacak veri nesnesi (pa.Table, pl.DataFrame, pl.LazyFrame veya pa.RecordBatch).
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

        if isinstance(table, pl.LazyFrame):
            arrow_table = table.collect().to_arrow()
        elif isinstance(table, pl.DataFrame):
            arrow_table = table.to_arrow()
        elif isinstance(table, pa.RecordBatch):
            arrow_table = pa.Table.from_batches([table])
        elif isinstance(table, pa.Table):
            arrow_table = table
        else:
            raise TypeError(
                f"Yazılacak veri pa.Table, pl.DataFrame, pl.LazyFrame veya pa.RecordBatch olmalıdır, alınan: {type(table).__name__}"
            )

        if arrow_table is None or arrow_table.num_rows == 0:
            raise ValueError("Diske yazılacak tablo boş olamaz.")

        full_path = self._resolve_path(path)

        with self._lock:
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Atomik yazma koruması: geçici dosyaya yazıp atomik replace yap
            temp_path = full_path.with_name(f"{full_path.name}.tmp.{uuid.uuid4().hex[:8]}")
            try:
                pq.write_table(arrow_table, str(temp_path), compression=compression)
                os.replace(temp_path, full_path)
            except Exception as e:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                logger.error("parquet_yazma_hatasi", yol=str(full_path), hata=str(e))
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

    @otel_trace("arrow_pipeline.read_polars")
    def read_polars(
        self,
        path: str,
        columns: list[str] | None = None,
        n_rows: int | None = None,
    ) -> pl.DataFrame:
        """Parquet dosyasını doğrudan Polars DataFrame olarak yüksek hızda okur.

        Args:
            path: Okunacak Parquet dosyasının yolu.
            columns: Yalnızca okunmak istenen sütun listesi.
            n_rows: Okunacak maksimum satır sayısı (None = tüm satırlar).

        Returns:
            pl.DataFrame: Polars veri çerçevesi.

        Raises:
            FileNotFoundError: Dosya bulunamadığında.
            ValueError: Okuma işlemi başarısız olduğunda.
        """
        full_path = self._resolve_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"Parquet dosyası bulunamadı: {full_path}")

        try:
            return pl.read_parquet(str(full_path), columns=columns, n_rows=n_rows)
        except Exception as e:
            logger.error("polars_parquet_okuma_hatasi", yol=str(full_path), hata=str(e))
            raise ValueError(f"Polars Parquet okuma başarısız: {full_path}") from e

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
        sql_query: str = DEFAULT_SQL_QUERY,
        params: Sequence[Any] | None = None,
    ) -> pl.DataFrame:
        """DuckDB motoru ile Parquet dosyasını sıfır kopyalama ve vektörize SQL ile sorgular.

        SQL sorgusu içinde hedef Parquet dosyasına `parquet_data` görünümü olarak başvurulur.

        Args:
            path: Sorgulanacak Parquet dosyasının yolu.
            sql_query: Çalıştırılacak DuckDB SQL sorgusu (varsayılan: "SELECT * FROM parquet_data").
            params: Sorgu parametreleri (parametre bağlama için).

        Returns:
            pl.DataFrame: Sorgu sonucu Polars DataFrame olarak döner.

        Raises:
            FileNotFoundError: Hedef Parquet dosyası mevcut değilse.
            ValueError: SQL sorgusu çalıştırılamadığında veya hata verdiğinde.
        """
        full_path = self._resolve_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"Sorgulanacak Parquet dosyası bulunamadı: {full_path}")

        conn = duckdb.connect()
        try:
            escaped_path = str(full_path).replace("'", "''")
            conn.execute(f"CREATE VIEW parquet_data AS SELECT * FROM read_parquet('{escaped_path}');")
            if params is not None:
                arrow_result = conn.execute(sql_query, params).arrow()
            else:
                arrow_result = conn.execute(sql_query).arrow()
            return pl.from_arrow(arrow_result)
        except Exception as e:
            logger.error("duckdb_parquet_query_failed", yol=str(full_path), sql=sql_query, hata=str(e))
            raise ValueError(f"DuckDB Parquet sorgusu başarısız: {e}") from e
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

        # Tekrarlanan dosya yollarını sırayı koruyarak filtrele
        seen: set[str] = set()
        dedup_paths: list[str] = []
        for p in input_paths:
            if p not in seen:
                seen.add(p)
                dedup_paths.append(p)

        tables: list[pa.Table] = []
        for path in dedup_paths:
            full_path = self._resolve_path(path)
            if not full_path.exists():
                raise FileNotFoundError(f"Birleştirilecek dosya bulunamadı: {full_path}")
            try:
                table = pq.read_table(str(full_path))
                if table.num_rows > 0:
                    tables.append(table)
            except Exception as err:
                logger.error("parquet_birlestirme_okuma_hatasi", yol=str(full_path), hata=str(err))
                raise ValueError(f"Parquet dosyası bozuk veya okunamadı: {full_path}") from err

        if not tables:
            raise ValueError("Birleştirilecek dosyalarda geçerli veri satırı bulunamadı.")

        # Şema farklılıklarını tolere etmek için permissive birleştirme
        try:
            merged = pa.concat_tables(tables, promote_options="permissive")
        except TypeError:
            merged = pa.concat_tables(tables, promote=True)

        return self.to_parquet(merged, output_path, compression=compression)

    @otel_trace("arrow_pipeline.write_partitioned_dataset")
    def write_partitioned_dataset(
        self,
        table: pa.Table | pl.DataFrame | pl.LazyFrame,
        base_dir: str,
        partition_cols: list[str],
        compression: str = DEFAULT_COMPRESSION,
    ) -> str:
        """Veriyi sütunlara göre bölümlenmiş (Hive-partitioned) Parquet veri kümesi olarak yazar.

        Args:
            table: Yazılacak veri tablosu (pa.Table, pl.DataFrame veya pl.LazyFrame).
            base_dir: Bölümlenmiş dizinin kök yolu.
            partition_cols: Bölümleme yapılacak sütun isimleri listesi (örn. ['ticker']).
            compression: Parquet sıkıştırma formatı.

        Returns:
            str: Yazılan bölüm kök dizini.

        Raises:
            ValueError: Tablo veya bölüm sütunları boş olduğunda.
        """
        if not partition_cols:
            raise ValueError("Bölümleme sütun listesi (partition_cols) boş olamaz.")

        if isinstance(table, pl.LazyFrame):
            arrow_table = table.collect().to_arrow()
        elif isinstance(table, pl.DataFrame):
            arrow_table = table.to_arrow()
        elif isinstance(table, pa.Table):
            arrow_table = table
        else:
            raise TypeError(f"Desteklenmeyen tablo tipi: {type(table).__name__}")

        if arrow_table.num_rows == 0:
            raise ValueError("Bölümlenecek veri tablosu boş olamaz.")

        full_dir = self._resolve_path(base_dir)

        with self._lock:
            full_dir.mkdir(parents=True, exist_ok=True)
            pq.write_to_dataset(
                arrow_table,
                root_path=str(full_dir),
                partition_cols=partition_cols,
                compression=compression,
            )

        logger.info(
            "bolumlenmis_dataset_yazildi",
            dizin=str(full_dir),
            satir=arrow_table.num_rows,
            bolumler=partition_cols,
        )
        return str(full_dir)

    @otel_trace("arrow_pipeline.get_metadata")
    def get_metadata(self, path: str) -> dict[str, Any]:
        """Parquet dosyasının şema, sıkıştırma ve satır grubu üst verilerini inceler.

        Args:
            path: İncelenecek Parquet dosyası yolu.

        Returns:
            dict[str, Any]: Satır sayısı, sütun sayısı, şema tipleri ve format bilgisi.

        Raises:
            FileNotFoundError: Dosya mevcut değilse.
            ValueError: Dosya üst verisi okunamadığında.
        """
        full_path = self._resolve_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"Üst verisi okunacak dosya bulunamadı: {full_path}")

        try:
            metadata = pq.read_metadata(str(full_path))
            schema = metadata.schema.to_arrow_schema()
            stat = full_path.stat()
            file_size_bytes = stat.st_size
            file_size_mb = round(file_size_bytes / (1024 * 1024), 3)

            # Sıkıştırma codec'lerini tespit et
            codecs: set[str] = set()
            for rg_idx in range(metadata.num_row_groups):
                rg = metadata.row_group(rg_idx)
                for col_idx in range(rg.num_columns):
                    col = rg.column(col_idx)
                    if col.compression:
                        codecs.add(str(col.compression).lower())

            return {
                "path": str(full_path),
                "rows": metadata.num_rows,
                "columns": metadata.num_columns,
                "row_groups": metadata.num_row_groups,
                "file_size_bytes": file_size_bytes,
                "file_size_mb": file_size_mb,
                "compression_codecs": sorted(codecs),
                "created_by": str(metadata.created_by or "unknown"),
                "format_version": str(metadata.format_version),
                "serialized_size": metadata.serialized_size,
                "column_names": schema.names,
                "schema_types": {field.name: str(field.type) for field in schema},
            }
        except Exception as e:
            logger.error("parquet_metadata_okuma_hatasi", yol=str(full_path), hata=str(e))
            raise ValueError(f"Parquet üst verisi bozuk veya okunamadı: {full_path}") from e


# Global Singleton örneği
arrow_pipeline: Final[ArrowPipeline] = ArrowPipeline()


# =====================================================
# MODÜL DÜZEYİ KOLAYLIK FONKSİYONLARI (CONVENIENCE API)
# =====================================================


def from_polars(
    df: pl.DataFrame | pl.LazyFrame | None, pipeline: ArrowPipeline | None = None
) -> pa.Table:
    """Polars DataFrame veya LazyFrame nesnesini Arrow Table formatına dönüştürür."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.from_polars(df=df)


def to_polars(
    table: pa.Table | pa.RecordBatch | None, pipeline: ArrowPipeline | None = None
) -> pl.DataFrame:
    """Arrow Table veya RecordBatch nesnesini Polars DataFrame formatına çevirir."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.to_polars(table=table)


def to_parquet(
    table: pa.Table | pl.DataFrame | pl.LazyFrame | pa.RecordBatch,
    path: str,
    compression: str = DEFAULT_COMPRESSION,
    pipeline: ArrowPipeline | None = None,
) -> str:
    """Veriyi Parquet formatında atomik olarak diske yazar."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.to_parquet(table=table, path=path, compression=compression)


def read_parquet(
    path: str,
    columns: list[str] | None = None,
    filters: Sequence[tuple[str, str, Any]] | list[list[tuple[str, str, Any]]] | None = None,
    pipeline: ArrowPipeline | None = None,
) -> pa.Table:
    """Parquet dosyasını okuyarak Arrow Table döndürür."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.read_parquet(path=path, columns=columns, filters=filters)


def read_polars(
    path: str,
    columns: list[str] | None = None,
    n_rows: int | None = None,
    pipeline: ArrowPipeline | None = None,
) -> pl.DataFrame:
    """Parquet dosyasını doğrudan Polars DataFrame olarak okur."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.read_polars(path=path, columns=columns, n_rows=n_rows)


def scan_parquet(path: str, pipeline: ArrowPipeline | None = None) -> ds.Dataset:
    """Parquet dosya veya dizini için PyArrow Dataset taraması başlatır."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.scan_parquet(path=path)


def scan_polars(path: str, pipeline: ArrowPipeline | None = None) -> pl.LazyFrame:
    """Parquet dosyası üzerinde Polars LazyFrame tembel tarayıcısı oluşturur."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.scan_polars(path=path)


def query_parquet_with_duckdb(
    path: str,
    sql_query: str = DEFAULT_SQL_QUERY,
    params: Sequence[Any] | None = None,
    pipeline: ArrowPipeline | None = None,
) -> pl.DataFrame:
    """DuckDB motoru ile Parquet dosyasını SQL ile sorgular."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.query_parquet_with_duckdb(path=path, sql_query=sql_query, params=params)


def merge_parquet(
    input_paths: list[str],
    output_path: str,
    compression: str = DEFAULT_COMPRESSION,
    pipeline: ArrowPipeline | None = None,
) -> str:
    """Birden fazla Parquet dosyasını şema evrimiyle birleştirir."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.merge_parquet(input_paths=input_paths, output_path=output_path, compression=compression)


def write_partitioned_dataset(
    table: pa.Table | pl.DataFrame | pl.LazyFrame,
    base_dir: str,
    partition_cols: list[str],
    compression: str = DEFAULT_COMPRESSION,
    pipeline: ArrowPipeline | None = None,
) -> str:
    """Veriyi bölümlenmiş Parquet veri kümesi olarak yazar."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.write_partitioned_dataset(
        table=table, base_dir=base_dir, partition_cols=partition_cols, compression=compression
    )


def get_metadata(path: str, pipeline: ArrowPipeline | None = None) -> dict[str, Any]:
    """Parquet dosyasının şema ve satır grubu üst verilerini inceler."""
    inst = pipeline if pipeline is not None else arrow_pipeline
    return inst.get_metadata(path=path)


def get_arrow_pipeline() -> ArrowPipeline:
    """Tekil ArrowPipeline örneğini döndürür."""
    return arrow_pipeline


__all__: list[str] = [
    "DEFAULT_BASE_PATH",
    "DEFAULT_COMPRESSION",
    "DEFAULT_SQL_QUERY",
    "VALID_COMPRESSIONS",
    "ArrowPipeline",
    "arrow_pipeline",
    "from_polars",
    "get_arrow_pipeline",
    "get_metadata",
    "merge_parquet",
    "query_parquet_with_duckdb",
    "read_parquet",
    "read_polars",
    "scan_parquet",
    "scan_polars",
    "to_parquet",
    "to_polars",
    "write_partitioned_dataset",
]
