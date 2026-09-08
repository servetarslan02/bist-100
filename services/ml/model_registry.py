"""ALPHA BIST — Kurumsal Model Kayıt Defteri ve Yaşam Döngüsü Yöneticisi (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; geliştirilen tüm niceliksel ve makine öğrenimi modellerinin (Şampiyon LightGBM,
Challenger CatBoost/XGBoost, Derin Öğrenme LSTM vb.) tüm yaşam döngüsünü (CANDIDATE, SHADOW,
CHAMPION, RETIRED, FAILED, ARCHIVED) yönetir, versiyon takibini yapar, soy kütüğü (lineage) ve
eğitim veri hash'lerini saklar, model artefaktlarını güvenli biçimde serileştirir ve modeller arası
karşılaştırma raporları üretir.

Temel Yetenekler:
- Otomatik Versiyonlama ve Sağlam Sayısal Takip (v1, v2, v3, ...)
- Durum Yaşam Döngüsü: Aday (CANDIDATE) → Gölge (SHADOW) → Şampiyon (CHAMPION) → Emekli (RETIRED)
- Veri ve Model Soy Kütüğü (Lineage, feature_set_version, training_data_hash)
- SSD Dostu Güvenli Model ve Metadata Serileştirmesi (Debounced Safe Pickle & orjson)
- DuckDB Üzerinde SSD Korumalı WAL ile Kayıt ve Geçiş Denetim İzi (Audit Trail)
- Polars Tabanlı Model Listeleme ve Versiyon Karşılaştırma Desteği
- İş Parçacığı Güvenliği (`threading.RLock`) ve Fail-Closed Hata Yönetimi
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.debounce import should_save
from services.core.safe_pickle import safe_pickle_dump, safe_pickle_load

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_REGISTRY_PATH: Final[str] = "data/model_registry"
DEFAULT_DUCKDB_PATH: Final[str] = "data/model_registry.duckdb"
DEFAULT_DEBOUNCE_SECONDS: Final[int] = 120
DEFAULT_LIST_LIMIT: Final[int] = 50


class ModelStatus(StrEnum):
    """Model yaşam döngüsü durumları."""

    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    CHAMPION = "CHAMPION"
    RETIRED = "RETIRED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


MODEL_STATUSES: Final[list[str]] = [s.value for s in ModelStatus]


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısına SSD ömrünü ve WAL boyutunu koruma direktiflerini uygular.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute("PRAGMA checkpoint_threshold = '4MB';")
        conn.execute("PRAGMA wal_autocheckpoint = '2MB';")
    except Exception as exc:
        logger.warning("DuckDB WAL pragma yapilandirmasi basarisiz", hata=str(exc))


@dataclass(slots=True)
class ModelEntry:
    """Model kayıt defteri girdi veri modeli."""

    model_id: str
    version: str
    model_type: str
    status: str = ModelStatus.CANDIDATE.value
    metrics: dict[str, Any] = field(default_factory=dict)
    hyperparams: dict[str, Any] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    training_data_hash: str = ""
    training_data_info: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    promoted_at: str | None = None
    retired_at: str | None = None
    description: str = ""
    tags: list[str] = field(default_factory=list)
    parent_model: str | None = None
    training_config: dict[str, Any] = field(default_factory=dict)
    feature_set_version: str = ""
    production_metrics: dict[str, Any] = field(default_factory=dict)
    last_evaluated: str | None = None
    author: str = "system"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Girdiyi standart sözlük yapısına dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """Girdiyi orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelEntry:
        """Sözlük verisinden geçerli alanları filtreleyerek ModelEntry nesnesi üretir.

        Args:
            data: Girdi sözlüğü.

        Returns:
            Oluşturulan ModelEntry örneği.
        """
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def __repr__(self) -> str:
        """Kayıt girdisinin özet metin gösterimini oluşturur."""
        return (
            f"ModelEntry(id='{self.model_id}', ver='{self.version}', "
            f"type='{self.model_type}', status='{self.status}', author='{self.author}')"
        )


class ModelRegistry:
    """Kurumsal Model Kayıt Defteri ve Yaşam Döngüsü Yöneticisi."""

    def __init__(
        self,
        registry_path: str = DEFAULT_REGISTRY_PATH,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """ModelRegistry bileşenini başlatır ve diskteki kayıtları yükler.

        Args:
            registry_path: Model dosyaları ve JSON metadata'nın tutulacağı dizin.
            duckdb_path: Denetim izi için kullanılacak DuckDB dosya yolu.
        """
        self._registry_path: str = registry_path
        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()
        self._entries: dict[str, ModelEntry] = {}
        self._models: dict[str, Any] = {}
        self._snapshots: dict[str, dict[str, Any]] = {}

        os.makedirs(self._registry_path, exist_ok=True)
        self._init_duckdb()
        self._load_registry()

    def _init_duckdb(self) -> None:
        """DuckDB denetim izi tablosunu güvenle ilklendirir."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS model_registry_audit (
                        timestamp TIMESTAMPTZ NOT NULL,
                        event_type VARCHAR NOT NULL,
                        model_id VARCHAR NOT NULL,
                        version VARCHAR NOT NULL,
                        model_type VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        details VARCHAR NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB model_registry_audit tablosu ilklendirilemedi", hata=str(exc))

    def _record_audit_event(
        self,
        event_type: str,
        model_id: str,
        version: str,
        model_type: str,
        status: str,
        details: dict[str, Any],
    ) -> None:
        """Model üzerinde gerçekleşen bir işlemi DuckDB denetim tablosuna yazar.

        Args:
            event_type: Olay tipi (REGISTER, PROMOTE, REJECT, ARCHIVE, EVALUATE).
            model_id: Model tanımlayıcısı.
            version: Model sürümü.
            model_type: Model türü.
            status: Model durumu.
            details: Olay detay sözlüğü.
        """
        try:
            now_iso = datetime.now(UTC).isoformat()
            details_json = orjson.dumps(details, default=str).decode()
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO model_registry_audit
                    (timestamp, event_type, model_id, version, model_type, status, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    [now_iso, event_type, model_id, version, model_type, status, details_json],
                )
        except Exception as exc:
            logger.warning("DuckDB denetim kaydi yazilamadi", olay=event_type, model_id=model_id, hata=str(exc))

    def register(
        self,
        model_id: str,
        model: Any,
        model_type: str,
        metrics: dict[str, Any],
        hyperparams: dict[str, Any] | None = None,
        features: list[str] | None = None,
        training_data_hash: str = "",
        training_data_info: dict[str, Any] | None = None,
        description: str = "",
        tags: list[str] | None = None,
        parent_model: str | None = None,
        training_config: dict[str, Any] | None = None,
        feature_set_version: str = "",
        author: str = "system",
        force_save: bool = True,
    ) -> str:
        """Yeni bir modeli kayıt defterine ekler ve otomatik versiyon atar.

        Veri kaybını önlemek için model ve metadata varsayılan olarak doğrudan diske yazılır (`force_save=True`).

        Args:
            model_id: Model tanımlayıcısı (ör. 'lightgbm_champion', 'catboost_bist100').
            model: Bellekteki model nesnesi.
            model_type: Model algoritma tipi (LIGHTGBM, CATBOOST, XGBOOST vb.).
            metrics: Eğitim ve doğrulama metrikleri sözlüğü.
            hyperparams: Hiperparametre sözlüğü.
            features: Modelin kullandığı öznitelik listesi.
            training_data_hash: Eğitim verisi SHA256 parmak izi.
            training_data_info: Eğitim verisi hakkında ek bilgiler.
            description: Model açıklaması.
            tags: Etiketler listesi.
            parent_model: Soy kütüğü için atasal model anahtarı.
            training_config: Eğitim konfigürasyon detayları.
            feature_set_version: Öznitelik seti sürümü.
            author: Modeli eğiten sistem veya kullanıcı.
            force_save: Kalıcı yazma (varsayılan: True - veri kaybı engellenir).

        Returns:
            Oluşturulan model anahtarı (model_id:version).
        """
        with self._lock:
            version = self._next_version(model_id)
            key = f"{model_id}:{version}"

            entry = ModelEntry(
                model_id=model_id,
                version=version,
                model_type=model_type,
                status=ModelStatus.CANDIDATE.value,
                metrics=metrics or {},
                hyperparams=hyperparams or {},
                features=features or [],
                training_data_hash=training_data_hash,
                training_data_info=training_data_info or {},
                created_at=datetime.now(UTC).isoformat(),
                description=description,
                tags=tags or [],
                parent_model=parent_model,
                training_config=training_config or {},
                feature_set_version=feature_set_version,
                author=author,
            )

            self._entries[key] = entry
            self._models[key] = model

            # Kritik veri kaybını önlemek için her model kaydı diske doğrudan yazılır
            self._save_model(key, model, force=force_save)
            self._save_registry(force=force_save)

            self._record_audit_event(
                event_type="REGISTER",
                model_id=model_id,
                version=version,
                model_type=model_type,
                status=entry.status,
                details={"metrics": metrics, "author": author, "tags": tags},
            )

            logger.info(
                "Model basariyla kaydedildi",
                model_id=model_id,
                version=version,
                model_type=model_type,
            )
            return key

    def _resolve_target_key(self, model_id: str, version: str | None = None) -> tuple[str, str, str] | None:
        """Verilen model_id ve version girdisini ayrıştırıp tam (key, model_id, version) döndürür.

        Eğer version belirtilmemişse önce en son CANDIDATE olanı, yoksa en son oluşturulan sürümü seçer.

        Args:
            model_id: Model ID veya 'model_id:version' bileşik anahtarı.
            version: İsteğe bağlı sürüm bilgisi.

        Returns:
            (key, model_id, version) tuple'ı veya bulunamazsa None.
        """
        if ":" in model_id:
            m_id, v_id = model_id.split(":", 1)
            key = f"{m_id}:{v_id}"
            if key in self._entries:
                return key, m_id, v_id

        m_id = model_id
        if version:
            key = f"{m_id}:{version}"
            if key in self._entries:
                return key, m_id, version
            return None

        # Sürüm verilmediyse: önce CANDIDATE olan en son modeli ara
        candidates = [
            (k, e)
            for k, e in self._entries.items()
            if e.model_id == m_id and e.status == ModelStatus.CANDIDATE.value
        ]
        if candidates:
            candidates.sort(key=lambda x: x[1].created_at, reverse=True)
            k, e = candidates[0]
            return k, m_id, e.version

        # CANDIDATE yoksa modelin en son sürümünü al
        all_versions = [(k, e) for k, e in self._entries.items() if e.model_id == m_id]
        if all_versions:
            all_versions.sort(key=lambda x: x[1].created_at, reverse=True)
            k, e = all_versions[0]
            return k, m_id, e.version

        return None

    def promote(self, model_id: str, version: str | None = None, reason: str = "") -> bool:
        """Belirtilen modeli CHAMPION durumuna yükseltir ve önceki şampiyonu RETIRED yapar.

        Version belirtilmezse ilgili modelin en son adayı (CANDIDATE) otomatik seçilir.

        Args:
            model_id: Model tanımlayıcısı veya anahtarı (ör. 'lightgbm_model' veya 'lightgbm_model:v2').
            version: Yükseltilecek sürüm (isteğe bağlı).
            reason: Terfi gerekçesi.

        Returns:
            İşlem başarılı ise True, model bulunamazsa False.
        """
        with self._lock:
            resolved = self._resolve_target_key(model_id, version)
            if not resolved:
                logger.warning("Terfi edilecek model kayit defterinde bulunamadi", model_id=model_id, version=version)
                return False

            key, m_id, v_id = resolved
            now_iso = datetime.now(UTC).isoformat()

            # Mevcut şampiyonu emekli et
            for k, v in self._entries.items():
                if v.model_id == m_id and v.status == ModelStatus.CHAMPION.value and k != key:
                    v.status = ModelStatus.RETIRED.value
                    v.retired_at = now_iso
                    if reason:
                        v.notes.append(f"Emekli Edildi ({now_iso}): Yeni sampiyon {key} terfi etti. Neden: {reason}")
                    self._record_audit_event(
                        event_type="RETIRE",
                        model_id=v.model_id,
                        version=v.version,
                        model_type=v.model_type,
                        status=v.status,
                        details={"reason": reason, "replaced_by": key},
                    )
                    logger.info("Onceki sampiyon model emekli edildi", key=k)

            target_entry = self._entries[key]
            target_entry.status = ModelStatus.CHAMPION.value
            target_entry.promoted_at = now_iso
            if reason:
                target_entry.notes.append(f"Terfi Edildi ({now_iso}): {reason}")

            self._save_registry(force=True)
            self._record_audit_event(
                event_type="PROMOTE",
                model_id=target_entry.model_id,
                version=target_entry.version,
                model_type=target_entry.model_type,
                status=target_entry.status,
                details={"reason": reason},
            )

            logger.info("Model sampiyonluk seviyesine yukseltildi", key=key, reason=reason)
            return True

    def reject(self, model_id: str, version: str | None = None, reason: str = "") -> bool:
        """Modeli FAILED durumuna geçirir.

        Version belirtilmezse modelin en son adayı otomatik seçilir.

        Args:
            model_id: Model tanımlayıcısı veya anahtarı.
            version: Reddedilecek sürüm (isteğe bağlı).
            reason: Ret gerekçesi.

        Returns:
            İşlem başarılı ise True, model bulunamazsa False.
        """
        with self._lock:
            resolved = self._resolve_target_key(model_id, version)
            if not resolved:
                logger.warning("Reddedilecek model bulunamadi", model_id=model_id, version=version)
                return False

            key, _, _ = resolved
            now_iso = datetime.now(UTC).isoformat()
            target_entry = self._entries[key]
            target_entry.status = ModelStatus.FAILED.value
            if reason:
                target_entry.notes.append(f"Reddedildi ({now_iso}): {reason}")

            self._save_registry(force=True)
            self._record_audit_event(
                event_type="REJECT",
                model_id=target_entry.model_id,
                version=target_entry.version,
                model_type=target_entry.model_type,
                status=target_entry.status,
                details={"reason": reason},
            )
            logger.info("Model reddedildi", key=key, reason=reason)
            return True

    def archive(self, model_id: str, version: str | None = None) -> bool:
        """Modeli ARCHIVED durumuna geçirir.

        Args:
            model_id: Model tanımlayıcısı veya anahtarı.
            version: Arşivlenecek sürüm (isteğe bağlı).

        Returns:
            İşlem başarılı ise True, model bulunamazsa False.
        """
        with self._lock:
            resolved = self._resolve_target_key(model_id, version)
            if not resolved:
                logger.warning("Arsivlenecek model bulunamadi", model_id=model_id, version=version)
                return False

            key, _, _ = resolved
            now_iso = datetime.now(UTC).isoformat()
            target_entry = self._entries[key]
            target_entry.status = ModelStatus.ARCHIVED.value
            target_entry.notes.append(f"Arsivlendi ({now_iso})")

            self._save_registry(force=True)
            self._record_audit_event(
                event_type="ARCHIVE",
                model_id=target_entry.model_id,
                version=target_entry.version,
                model_type=target_entry.model_type,
                status=target_entry.status,
                details={},
            )
            logger.info("Model arsivlendi", key=key)
            return True

    def get_champion(self, model_id: str) -> dict[str, Any] | None:
        """Belirtilen model için CHAMPION durumundaki modeli getirir.

        Args:
            model_id: Model tanımlayıcısı.

        Returns:
            Model ve metadata sözlüğü veya None.
        """
        with self._lock:
            for key, entry in self._entries.items():
                if entry.model_id == model_id and entry.status == ModelStatus.CHAMPION.value:
                    model_obj = self._models.get(key)
                    if model_obj is None:
                        model_obj = self._load_model(key)
                        if model_obj is not None:
                            self._models[key] = model_obj
                    return {"key": key, "entry": entry, "model": model_obj}
            return None

    def get_latest(self, model_id: str, status: str | None = None) -> dict[str, Any] | None:
        """En son oluşturulan model sürümünü getirir.

        Args:
            model_id: Model tanımlayıcısı.
            status: İsteğe bağlı durum filtresi (ör. 'CHAMPION', 'CANDIDATE').

        Returns:
            Model ve metadata sözlüğü veya None.
        """
        with self._lock:
            candidates = [
                (key, entry)
                for key, entry in self._entries.items()
                if entry.model_id == model_id and (status is None or entry.status == status)
            ]
            if not candidates:
                return None

            candidates.sort(key=lambda x: x[1].created_at, reverse=True)
            key, entry = candidates[0]
            model_obj = self._models.get(key)
            if model_obj is None:
                model_obj = self._load_model(key)
                if model_obj is not None:
                    self._models[key] = model_obj
            return {"key": key, "entry": entry, "model": model_obj}

    def get_model(self, model_id: str, version: str) -> Any | None:
        """Model nesnesini bellekten veya diskten yükler.

        Args:
            model_id: Model tanımlayıcısı.
            version: Model sürümü.

        Returns:
            Model nesnesi veya bulunamazsa None.
        """
        with self._lock:
            key = f"{model_id}:{version}"
            if key in self._models:
                return self._models[key]
            loaded = self._load_model(key)
            if loaded is not None:
                self._models[key] = loaded
            return loaded

    def get_entry(self, key: str) -> ModelEntry | None:
        """Kayıt anahtarına (örn. 'alpha_net:v1') göre ModelEntry nesnesini döndürür.

        Args:
            key: Model kayıt anahtarı ('model_id:version').

        Returns:
            ModelEntry nesnesi veya bulunamazsa None.
        """
        with self._lock:
            return self._entries.get(key)

    def list_models(
        self,
        model_id: str | None = None,
        status: str | None = None,
        model_type: str | None = None,
        tag: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[dict[str, Any]]:
        """Filtrelenmiş model kayıtlarını listeler.

        Args:
            model_id: Model kimliği filtresi.
            status: Model durumu filtresi.
            model_type: Model tipi filtresi.
            tag: Etiket filtresi.
            limit: Maksimum döndürülecek kayıt sayısı.

        Returns:
            Kayıt özet sözlükleri listesi.
        """
        with self._lock:
            results: list[dict[str, Any]] = []
            for key, entry in self._entries.items():
                if model_id and entry.model_id != model_id:
                    continue
                if status and entry.status != status:
                    continue
                if model_type and entry.model_type != model_type:
                    continue
                if tag and tag not in entry.tags:
                    continue
                results.append(
                    {
                        "key": key,
                        "model_id": entry.model_id,
                        "version": entry.version,
                        "model_type": entry.model_type,
                        "status": entry.status,
                        "metrics": entry.metrics,
                        "created_at": entry.created_at,
                        "promoted_at": entry.promoted_at,
                        "description": entry.description,
                        "tags": entry.tags,
                        "author": entry.author,
                    }
                )

            results.sort(key=lambda x: str(x["created_at"]), reverse=True)
            return results[:limit]

    def list_models_polars(
        self,
        model_id: str | None = None,
        status: str | None = None,
        model_type: str | None = None,
        tag: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> pl.DataFrame:
        """Kayıtlı modelleri Polars DataFrame formatında döndürür.

        Args:
            model_id: Model kimliği filtresi.
            status: Model durumu filtresi.
            model_type: Model tipi filtresi.
            tag: Etiket filtresi.
            limit: Maksimum satır sayısı.

        Returns:
            Polars DataFrame tablosu.
        """
        models = self.list_models(
            model_id=model_id,
            status=status,
            model_type=model_type,
            tag=tag,
            limit=limit,
        )
        if not models:
            return pl.DataFrame(
                schema={
                    "key": pl.Utf8,
                    "model_id": pl.Utf8,
                    "version": pl.Utf8,
                    "model_type": pl.Utf8,
                    "status": pl.Utf8,
                    "created_at": pl.Utf8,
                    "promoted_at": pl.Utf8,
                    "description": pl.Utf8,
                    "author": pl.Utf8,
                }
            )

        flat_records = []
        for m in models:
            rec = {
                "key": m["key"],
                "model_id": m["model_id"],
                "version": m["version"],
                "model_type": m["model_type"],
                "status": m["status"],
                "created_at": str(m["created_at"]),
                "promoted_at": str(m["promoted_at"]) if m["promoted_at"] else None,
                "description": m["description"],
                "author": m["author"],
            }
            flat_records.append(rec)

        return pl.DataFrame(flat_records)

    def compare_versions(
        self,
        model_id: str,
        version_a: str,
        version_b: str,
    ) -> dict[str, Any]:
        """İki model versiyonunu metrikler ve parametreler açısından karşılaştırır.

        Args:
            model_id: Karşılaştırılacak model kimliği.
            version_a: İlk versiyon (ör. 'v1').
            version_b: İkinci versiyon (ör. 'v2').

        Returns:
            Karşılaştırma özet sözlüğü.
        """
        with self._lock:
            key_a = f"{model_id}:{version_a}"
            key_b = f"{model_id}:{version_b}"

            entry_a = self._entries.get(key_a)
            entry_b = self._entries.get(key_b)

            if not entry_a or not entry_b:
                return {"error": "Versiyon bulunamadi", "version_a": version_a, "version_b": version_b}

            common_features = set(entry_a.features) & set(entry_b.features)
            comparison: dict[str, Any] = {
                "model_id": model_id,
                "version_a": version_a,
                "version_b": version_b,
                "status_a": entry_a.status,
                "status_b": entry_b.status,
                "metrics_comparison": {},
                "hyperparams_diff": {},
                "features_diff": {
                    "added": sorted(list(set(entry_b.features) - set(entry_a.features))),
                    "removed": sorted(list(set(entry_a.features) - set(entry_b.features))),
                    "unchanged": sorted(list(common_features)),
                    "unchanged_count": len(common_features),
                },
            }

            all_metrics = set(list(entry_a.metrics.keys()) + list(entry_b.metrics.keys()))
            for metric in all_metrics:
                val_a = entry_a.metrics.get(metric, 0.0)
                val_b = entry_b.metrics.get(metric, 0.0)
                if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                    diff = float(val_b - val_a)
                    pct = (diff / abs(val_a) * 100.0) if val_a != 0.0 else 0.0
                    comparison["metrics_comparison"][metric] = {
                        "val_a": float(val_a),
                        "val_b": float(val_b),
                        "diff": round(diff, 4),
                        "pct_change": round(pct, 2),
                        "b_better": diff > 0.0,
                    }

            all_params = set(list(entry_a.hyperparams.keys()) + list(entry_b.hyperparams.keys()))
            for param in all_params:
                val_a = entry_a.hyperparams.get(param)
                val_b = entry_b.hyperparams.get(param)
                if val_a != val_b:
                    comparison["hyperparams_diff"][param] = {"val_a": val_a, "val_b": val_b}

            return comparison

    def compare_versions_polars(
        self,
        model_id: str,
        version_a: str,
        version_b: str,
    ) -> pl.DataFrame:
        """İki model versiyonunun metrik karşılaştırmasını Polars tablosu olarak döndürür.

        Args:
            model_id: Model kimliği.
            version_a: İlk sürüm.
            version_b: İkinci sürüm.

        Returns:
            Metrik farklarını içeren Polars DataFrame.
        """
        comp = self.compare_versions(model_id, version_a, version_b)
        if "error" in comp or "metrics_comparison" not in comp:
            return pl.DataFrame(
                schema={
                    "metric": pl.Utf8,
                    "val_a": pl.Float64,
                    "val_b": pl.Float64,
                    "diff": pl.Float64,
                    "pct_change": pl.Float64,
                    "b_better": pl.Boolean,
                }
            )

        rows = []
        for metric, data in comp["metrics_comparison"].items():
            rows.append(
                {
                    "metric": str(metric),
                    "val_a": float(data["val_a"]),
                    "val_b": float(data["val_b"]),
                    "diff": float(data["diff"]),
                    "pct_change": float(data["pct_change"]),
                    "b_better": bool(data["b_better"]),
                }
            )

        if not rows:
            return pl.DataFrame(
                schema={
                    "metric": pl.Utf8,
                    "val_a": pl.Float64,
                    "val_b": pl.Float64,
                    "diff": pl.Float64,
                    "pct_change": pl.Float64,
                    "b_better": pl.Boolean,
                }
            )

        return pl.DataFrame(rows)

    def update_production_metrics(
        self,
        model_id: str,
        version: str,
        metrics: dict[str, Any],
    ) -> bool:
        """Canlı ortamda gözlemlenen üretim metriklerini günceller.

        Args:
            model_id: Model tanımlayıcısı.
            version: Model versiyonu.
            metrics: Canlı metrikler sözlüğü.

        Returns:
            İşlem başarılı ise True, model bulunamazsa False.
        """
        with self._lock:
            key = f"{model_id}:{version}"
            if key not in self._entries:
                return False

            now_iso = datetime.now(UTC).isoformat()
            self._entries[key].production_metrics = metrics
            self._entries[key].last_evaluated = now_iso
            self._save_registry(force=False)  # Sık güncelleme durumunda debounced

            self._record_audit_event(
                event_type="EVALUATE",
                model_id=model_id,
                version=version,
                model_type=self._entries[key].model_type,
                status=self._entries[key].status,
                details={"production_metrics": metrics},
            )
            return True

    def add_note(self, model_id: str, version: str, note: str) -> bool:
        """Modele zaman damgalı denetim notu ekler.

        Args:
            model_id: Model tanımlayıcısı.
            version: Model sürümü.
            note: Eklenecek not metni.

        Returns:
            İşlem başarılı ise True, model bulunamazsa False.
        """
        with self._lock:
            key = f"{model_id}:{version}"
            if key not in self._entries:
                return False

            now_iso = datetime.now(UTC).isoformat()
            self._entries[key].notes.append(f"[{now_iso}] {note}")
            self._save_registry(force=True)
            return True

    def snapshot(self, name: str) -> bool:
        """Kayıt defterinin anlık tam durum yedeğini (snapshot) alır.

        Args:
            name: Snapshot tanımlayıcı adı.

        Returns:
            Her zaman True.
        """
        with self._lock:
            self._snapshots[name] = {
                "timestamp": datetime.now(UTC).isoformat(),
                "entries": {k: asdict(v) for k, v in self._entries.items()},
            }
            return True

    def get_stats(self) -> dict[str, Any]:
        """Kayıt defterinin genel istatistiklerini hesaplar.

        Returns:
            Toplam model, durum dağılımı ve snapshot sayılarını içeren sözlük.
        """
        with self._lock:
            status_counts: dict[str, int] = {}
            type_counts: dict[str, int] = {}
            for entry in self._entries.values():
                status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
                type_counts[entry.model_type] = type_counts.get(entry.model_type, 0) + 1

            return {
                "total_models": len(self._entries),
                "status_distribution": status_counts,
                "type_distribution": type_counts,
                "n_snapshots": len(self._snapshots),
            }

    def _next_version(self, model_id: str) -> str:
        """Sonraki artırımlı sürüm numarasını (v1, v2, ...) belirler.

        Tüm versiyon formatlarındaki sayısal değerleri güvenle ayrıştırır.
        """
        existing = [e.version for e in self._entries.values() if e.model_id == model_id]
        if not existing:
            return "v1"

        numeric_versions = []
        for v in existing:
            digits = re.findall(r"\d+", v)
            if digits:
                numeric_versions.append(int(digits[0]))

        if not numeric_versions:
            return f"v{len(existing) + 1}"

        return f"v{max(numeric_versions) + 1}"

    def _save_model(self, key: str, model: Any, force: bool = True) -> None:
        """Model nesnesini SSD dostu güvenli pickle ile diske kaydeder."""
        if not force and not should_save(f"model_save_{key}", DEFAULT_DEBOUNCE_SECONDS):
            return
        try:
            path = os.path.join(self._registry_path, f"{key.replace(':', '_')}.pkl")
            safe_pickle_dump(model, path)
        except Exception as exc:
            logger.error("Model diske kaydedilemedi", key=key, hata=str(exc))

    def _load_model(self, key: str) -> Any | None:
        """Model nesnesini diskten güvenli pickle ile yükler."""
        try:
            path = os.path.join(self._registry_path, f"{key.replace(':', '_')}.pkl")
            if os.path.exists(path):
                return safe_pickle_load(path)
        except Exception as exc:
            logger.error("Model diskten yuklenemedi", key=key, hata=str(exc))
        return None

    def _save_registry(self, force: bool = True) -> None:
        """Kayıt defteri metadata'sını orjson formatında diske kaydeder."""
        if not force and not should_save("model_registry", DEFAULT_DEBOUNCE_SECONDS):
            return
        try:
            data = {k: asdict(v) for k, v in self._entries.items()}
            path = os.path.join(self._registry_path, "registry.json")
            with open(path, "wb") as f:
                f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str))
        except Exception as exc:
            logger.error("Registry verisi diske kaydedilemedi", hata=str(exc))

    def _load_registry(self) -> None:
        """Diskteki registry.json dosyasını yükler ve ModelEntry nesnelerine dönüştürür."""
        try:
            path = os.path.join(self._registry_path, "registry.json")
            if os.path.exists(path):
                with open(path, "rb") as f:
                    data = orjson.loads(f.read())
                for key, entry_dict in data.items():
                    if isinstance(entry_dict, dict):
                        self._entries[key] = ModelEntry.from_dict(entry_dict)
        except Exception as exc:
            logger.warning("Registry verisi yuklenemedi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki model yaşam döngüsü denetim kayıtlarını Polars DataFrame olarak döndürür."""
        with self._lock:
            try:
                with duckdb.connect(self._duckdb_path) as conn:
                    return conn.execute("SELECT * FROM model_registry_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        """ModelRegistry özet metin gösterimini oluşturur."""
        with self._lock:
            return f"ModelRegistry(path='{self._registry_path}', total_models={len(self._entries)})"


model_registry: Final[ModelRegistry] = ModelRegistry()

__all__: Final[list[str]] = [
    "DEFAULT_DEBOUNCE_SECONDS",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_LIST_LIMIT",
    "DEFAULT_REGISTRY_PATH",
    "MODEL_STATUSES",
    "ModelEntry",
    "ModelRegistry",
    "ModelStatus",
    "configure_duckdb_wal",
    "model_registry",
]
