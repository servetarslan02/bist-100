"""ALPHA BIST — Grafana Dashboard ve Veri Kaynağı Sağlama (Provisioning) Modülü.

Bu modül, platform metriklerinin ve piyasa izleme ekranlarının Grafana üzerinde
otomatik olarak yapılandırılmasını, dashboard JSON tanımlarının yüklenmesini,
Prometheus ve ClickHouse veri kaynaklarının (datasource) tanımlanmasını, klasör
ve versiyon yönetimini sağlar.

Temel Yetenekler:
- Grafana REST API entegrasyonu (Basic Auth, API Token, Bearer Token).
- Veri kaynağı (Datasource) oluşturma ve yerinde güncelleme.
- Dashboard JSON dosyalarının taranması, UID sağlama ve versiyonlama.
- Klasör (Folder) yönetimi ve yetkilendirme.
- Sistem sağlık kontrolü (Health Check / Liveness).
- Polars DataFrame ile dashboard versiyon geçmişi ihracı.
- DuckDB ile denetim izi (Audit Trail) kaydı.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import httpx
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# ==============================================================================
# Standart Yapılandırma ve Yol Sabitleri
# ==============================================================================

DEFAULT_GRAFANA_URL: str = "http://localhost:3000"
DEFAULT_GRAFANA_AUTH: str = "admin:admin"
DEFAULT_TIMEOUT_SECONDS: float = 30.0
DEFAULT_MAX_VERSIONS: int = 1000
DEFAULT_PROMETHEUS_URL: str = "http://localhost:9090"
DEFAULT_GRAFANA_AUDIT_DB_PATH: str = "data/grafana_audit.duckdb"

DASHBOARD_DIR: Path = Path(__file__).resolve().parent.parent.parent / "monitoring"


# ==============================================================================
# Veri Modelleri
# ==============================================================================


@dataclass(slots=True)
class GrafanaConfig:
    """Grafana bağlantı ve yetkilendirme yapılandırması.

    Attributes:
        url: Grafana sunucu adresi (örn: http://localhost:3000).
        auth: Kullanıcı adı:şifre veya Bearer / Service Account token.
        timeout: HTTP istek zaman aşımı süresi (saniye).
        verify_ssl: SSL sertifika doğrulaması aktif mi.
        org_id: Hedef organizasyon kimliği (varsayılan: 1).
    """

    url: str = DEFAULT_GRAFANA_URL
    auth: str = DEFAULT_GRAFANA_AUTH
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    verify_ssl: bool = True
    org_id: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür (şifre maskelenir)."""
        masked_auth = "***"
        if ":" in self.auth:
            user = self.auth.split(":", 1)[0]
            masked_auth = f"{user}:***"
        elif len(self.auth) > 8:
            masked_auth = f"{self.auth[:4]}...{self.auth[-4:]}"

        return {
            "url": self.url,
            "auth": masked_auth,
            "timeout": self.timeout,
            "verify_ssl": self.verify_ssl,
            "org_id": self.org_id,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"GrafanaConfig(url='{self.url}', timeout={self.timeout}s, "
            f"verify_ssl={self.verify_ssl}, org_id={self.org_id})"
        )


@dataclass(slots=True)
class DatasourceConfig:
    """Grafana veri kaynağı (Datasource) yapılandırması.

    Attributes:
        name: Veri kaynağı adı (örn: 'Prometheus').
        type: Kaynak türü ('prometheus', 'influxdb', 'clickhouse' vb.).
        url: Kaynak hedef sunucu adresi (örn: 'http://localhost:9090').
        access: Erişim türü ('proxy' veya 'direct').
        is_default: Varsayılan veri kaynağı olarak atansın mı.
        extra: Ek veri kaynağı parametreleri (HTTP başlıkları, JSONData vb.).
    """

    name: str
    type: str
    url: str
    access: str = "proxy"
    is_default: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_grafana_payload(self) -> dict[str, Any]:
        """Grafana REST API payload sözlüğüne dönüştür."""
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "url": self.url,
            "access": self.access,
            "isDefault": self.is_default,
        }
        payload.update(self.extra)
        return payload

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür."""
        return self.to_grafana_payload()

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt serileştirmesi."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"DatasourceConfig(ad='{self.name}', tur='{self.type}', url='{self.url}', "
            f"varsayilan={self.is_default})"
        )


@dataclass(slots=True)
class DashboardVersion:
    """Dashboard yükleme ve versiyon kayıt kaydı.

    Attributes:
        uid: Dashboard benzersiz kimliği (12 karakterli UID).
        title: Dashboard başlığı.
        version: Grafana versiyon numarası.
        provisioned_at: Yükleme zaman damgası (ISO 8601 UTC).
        file_path: Kaynak JSON dosya yolu.
        status: Yükleme durumu ('SUCCESS', 'FAILED', 'SKIPPED').
    """

    uid: str
    title: str
    version: int
    provisioned_at: str
    file_path: str
    status: str = "SUCCESS"

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür."""
        return {
            "uid": self.uid,
            "title": self.title,
            "version": self.version,
            "provisioned_at": self.provisioned_at,
            "file_path": self.file_path,
            "status": self.status,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"DashboardVersion(uid='{self.uid}', baslik='{self.title}', "
            f"surum={self.version}, durum='{self.status}')"
        )


# ==============================================================================
# Grafana Provisioner Ana Sınıfı
# ==============================================================================


class GrafanaProvisioner:
    """Grafana dashboard, datasource ve klasör sağlayıcı motor.

    HTTPX tabanlı asenkron iletişim, thread-safe durum yönetimi, Polars ve DuckDB
    denetim izi entegrasyonu sunar.
    """

    def __init__(self, config: GrafanaConfig | None = None) -> None:
        """GrafanaProvisioner başlatıcı.

        Args:
            config: Grafana bağlantı ayarları (None ise ortam değişkenlerinden türetilir).
        """
        self._config = config or GrafanaConfig()
        self._lock = threading.RLock()
        self._versions: deque[DashboardVersion] = deque(maxlen=DEFAULT_MAX_VERSIONS)
        self._provisioned_dashboards: dict[str, int] = {}  # uid -> version
        self._provisioned_datasources: list[str] = []

    def _get_auth_and_headers(self) -> tuple[httpx.Auth | None, dict[str, str]]:
        """Grafana kimlik doğrulama başlıklarını ve Auth nesnesini üret.

        Returns:
            tuple[httpx.Auth | None, dict[str, str]]: Auth nesnesi ve ek başlıklar.
        """
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        auth_str = self._config.auth.strip()

        if auth_str.startswith("Bearer "):
            headers["Authorization"] = auth_str
            return None, headers
        if auth_str.startswith("glsa_") or (len(auth_str) >= 32 and ":" not in auth_str):
            headers["Authorization"] = f"Bearer {auth_str}"
            return None, headers
        if ":" in auth_str:
            user, pwd = auth_str.split(":", 1)
            return httpx.BasicAuth(user, pwd), headers

        headers["Authorization"] = f"Bearer {auth_str}"
        return None, headers

    def _create_client(self) -> httpx.AsyncClient:
        """Yapılandırılmış asenkron HTTP istemcisi üret."""
        auth, headers = self._get_auth_and_headers()
        return httpx.AsyncClient(
            auth=auth,
            headers=headers,
            timeout=httpx.Timeout(self._config.timeout),
            verify=self._config.verify_ssl,
        )

    # ==========================================================================
    # SAĞLIK VE DURUM KONTROLÜ
    # ==========================================================================

    @otel_trace("grafana.check_health")
    async def check_health(self) -> bool:
        """Grafana sunucusunun erişilebilir ve sağlıklı olduğunu doğrula.

        Returns:
            bool: Grafana /api/health endpoint'i 200 dönüyorsa True, aksi halde False.
        """
        url = f"{self._config.url.rstrip('/')}/api/health"
        try:
            async with self._create_client() as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = orjson.loads(resp.content)
                    logger.info(
                        "grafana_saglik_kontrolu_basarili",
                        surum=data.get("version"),
                        veritabani=data.get("database"),
                    )
                    return True
                logger.warning("grafana_saglik_kontrolu_olumsuz", status=resp.status_code)
                return False
        except Exception as e:
            logger.error("grafana_saglik_kontrolu_hatasi", url=url, hata=str(e))
            return False

    # ==========================================================================
    # VERİ KAYNAĞI (DATASOURCE) İŞLEMLERİ
    # ==========================================================================

    @otel_trace("grafana.provision_datasource")
    async def provision_datasource(self, ds_config: DatasourceConfig) -> bool:
        """Datasource oluştur veya mevcut ise güncelle.

        Args:
            ds_config: Yüklenecek veri kaynağı yapılandırması.

        Returns:
            bool: İşlem başarılı ise True, hata durumunda False.
        """
        base_url = f"{self._config.url.rstrip('/')}/api/datasources"
        payload = ds_config.to_grafana_payload()

        try:
            async with self._create_client() as client:
                # 1. Mevcut veri kaynağını kontrol et
                check_resp = await client.get(f"{base_url}/name/{ds_config.name}")
                if check_resp.status_code == 200:
                    existing = orjson.loads(check_resp.content)
                    ds_id = existing.get("id")
                    payload["id"] = ds_id

                    # Güncelleme (PUT)
                    put_resp = await client.put(f"{base_url}/{ds_id}", json=payload)
                    if put_resp.status_code == 200:
                        logger.info("veri_kaynagi_guncellendi", ad=ds_config.name, id=ds_id)
                        with self._lock:
                            if ds_config.name not in self._provisioned_datasources:
                                self._provisioned_datasources.append(ds_config.name)
                        return True
                    logger.error(
                        "veri_kaynagi_guncelleme_basarisiz",
                        ad=ds_config.name,
                        status=put_resp.status_code,
                        govde=put_resp.text[:200],
                    )
                    return False

                # 2. Mevcut değilse yeni oluştur (POST)
                post_resp = await client.post(base_url, json=payload)
                if post_resp.status_code in (200, 201):
                    logger.info("veri_kaynagi_olusturuldu", ad=ds_config.name)
                    with self._lock:
                        if ds_config.name not in self._provisioned_datasources:
                            self._provisioned_datasources.append(ds_config.name)
                    return True

                logger.error(
                    "veri_kaynagi_olusturma_basarisiz",
                    ad=ds_config.name,
                    status=post_resp.status_code,
                    govde=post_resp.text[:200],
                )
                return False

        except Exception as e:
            logger.error("veri_kaynagi_saglama_hatasi", ad=ds_config.name, hata=str(e))
            return False

    # ==========================================================================
    # KLASÖR (FOLDER) İŞLEMLERİ
    # ==========================================================================

    @otel_trace("grafana.provision_folder")
    async def provision_folder(self, title: str, uid: str | None = None) -> int | None:
        """Grafana üzerinde dashboard klasörü oluştur veya mevcut olanın kimliğini al.

        Args:
            title: Klasör başlığı.
            uid: Opsiyonel klasör UID'si.

        Returns:
            int | None: Klasör ID'si (folderId) veya hata durumunda None.
        """
        base_url = f"{self._config.url.rstrip('/')}/api/folders"
        folder_uid = uid or hashlib.sha256(title.encode("utf-8")).hexdigest()[:10]
        payload = {"title": title, "uid": folder_uid}

        try:
            async with self._create_client() as client:
                # 1. UID ile mevcut mu kontrol et
                get_resp = await client.get(f"{base_url}/{folder_uid}")
                if get_resp.status_code == 200:
                    return int(orjson.loads(get_resp.content).get("id", 0))

                # 2. Yeni klasör oluştur
                post_resp = await client.post(base_url, json=payload)
                if post_resp.status_code in (200, 201):
                    folder_id = int(orjson.loads(post_resp.content).get("id", 0))
                    logger.info("grafana_klasor_olusturuldu", baslik=title, id=folder_id, uid=folder_uid)
                    return folder_id

                # Çakışma durumunda tüm klasörleri tarayıp başlığa göre bul
                if post_resp.status_code == 409:
                    list_resp = await client.get(base_url)
                    if list_resp.status_code == 200:
                        for item in orjson.loads(list_resp.content):
                            if item.get("title") == title:
                                return int(item.get("id", 0))

                logger.error(
                    "grafana_klasor_olusturma_basarisiz",
                    baslik=title,
                    status=post_resp.status_code,
                    govde=post_resp.text[:200],
                )
                return None
        except Exception as e:
            logger.error("grafana_klasor_hatasi", baslik=title, hata=str(e))
            return None

    # ==========================================================================
    # DASHBOARD İŞLEMLERİ
    # ==========================================================================

    @otel_trace("grafana.provision_dashboard")
    async def provision_dashboard(
        self,
        file_path: str | Path,
        folder_id: int = 0,
        overwrite: bool = True,
    ) -> int | None:
        """Dashboard JSON dosyasını okuyup Grafana'ya yükle ve versiyonla.

        Args:
            file_path: JSON dashboard dosyasının yolu.
            folder_id: Hedef klasör kimliği (0: General).
            overwrite: Mevcut dashboard'un üzerine yazılsın mı.

        Returns:
            int | None: Güncel dashboard sürüm numarası veya hata durumunda None.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            logger.error("dashboard_dosyasi_bulunamadi", yol=str(path))
            return None

        try:
            raw_data = path.read_bytes()
            dashboard_data = orjson.loads(raw_data)
        except Exception as e:
            logger.error("dashboard_json_cozumleme_hatasi", yol=str(path), hata=str(e))
            return None

        dashboard_obj = dashboard_data.get("dashboard", dashboard_data)
        if not isinstance(dashboard_obj, dict):
            logger.error("gecersiz_dashboard_formati", yol=str(path))
            return None

        # UID yoksa dosya yolundan deterministik üret
        if "uid" not in dashboard_obj or not dashboard_obj["uid"]:
            uid = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
            dashboard_obj["uid"] = uid
        else:
            uid = str(dashboard_obj["uid"])

        title = str(dashboard_obj.get("title", path.stem))
        payload = {
            "dashboard": dashboard_obj,
            "folderId": folder_id,
            "overwrite": overwrite,
        }

        url = f"{self._config.url.rstrip('/')}/api/dashboards/db"
        now_iso = datetime.now(UTC).isoformat()

        try:
            async with self._create_client() as client:
                resp = await client.post(url, json=payload)
                if resp.status_code in (200, 201):
                    result = orjson.loads(resp.content)
                    version = int(result.get("version", 1))

                    ver_entry = DashboardVersion(
                        uid=uid,
                        title=title,
                        version=version,
                        provisioned_at=now_iso,
                        file_path=str(path),
                        status="SUCCESS",
                    )
                    with self._lock:
                        self._provisioned_dashboards[uid] = version
                        self._versions.append(ver_entry)

                    logger.info("dashboard_yuklendi", baslik=title, surum=version, uid=uid)
                    return version

                body = resp.text
                logger.error("dashboard_yukleme_basarisiz", status=resp.status_code, govde=body[:200])
                with self._lock:
                    self._versions.append(
                        DashboardVersion(
                            uid=uid,
                            title=title,
                            version=-1,
                            provisioned_at=now_iso,
                            file_path=str(path),
                            status=f"FAILED_HTTP_{resp.status_code}",
                        )
                    )
                return None

        except Exception as e:
            logger.error("dashboard_yukleme_istisnasi", yol=str(path), hata=str(e))
            with self._lock:
                self._versions.append(
                    DashboardVersion(
                        uid=uid,
                        title=title,
                        version=-1,
                        provisioned_at=now_iso,
                        file_path=str(path),
                        status=f"EXCEPTION_{type(e).__name__}",
                    )
                )
            return None

    @otel_trace("grafana.provision_all")
    async def provision_all(self, dashboard_dir: Path | str | None = None) -> dict[str, Any]:
        """Tüm standart veri kaynaklarını ve dashboard dosyalarını toplu yükle.

        Args:
            dashboard_dir: Dashboard JSON dosyalarının bulunduğu dizin (None ise DASHBOARD_DIR).

        Returns:
            dict[str, Any]: Yükleme sonuçları ve durum raporu.
        """
        target_dir = Path(dashboard_dir) if dashboard_dir else DASHBOARD_DIR
        results: dict[str, Any] = {
            "datasources": {},
            "dashboards": {},
            "errors": [],
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # 1. Standart Veri Kaynağı: Prometheus
        prom_url = DEFAULT_PROMETHEUS_URL
        prom_ds = DatasourceConfig(
            name="Prometheus",
            type="prometheus",
            url=prom_url,
            is_default=True,
        )
        prom_ok = await self.provision_datasource(prom_ds)
        results["datasources"]["Prometheus"] = "ok" if prom_ok else "failed"

        # 2. Dizin içerisindeki dashboard dosyalarını tara
        if not target_dir.exists():
            msg = f"Dashboard dizini bulunamadı: {target_dir}"
            results["errors"].append(msg)
            logger.warning("dashboard_dizini_bulunamadi", dizin=str(target_dir))
            return results

        json_files = list(target_dir.glob("*.json"))
        # alert_rules.json gibi kural dosyalarını dashboard olarak yükleme
        dashboard_files = [f for f in json_files if "alert_rules" not in f.name.lower()]

        if not dashboard_files:
            logger.info("yuklenecek_dashboard_dosyasi_bulunamadi", dizin=str(target_dir))
            return results

        for fpath in dashboard_files:
            version = await self.provision_dashboard(fpath)
            results["dashboards"][fpath.stem] = {
                "version": version,
                "file": str(fpath),
                "status": "ok" if version is not None else "failed",
            }

        logger.info(
            "tum_grafana_bilesenleri_saglandi",
            veri_kaynaklari=len(results["datasources"]),
            dashboardlar=len(results["dashboards"]),
            hatalar=len(results["errors"]),
        )
        return results

    # ==========================================================================
    # VERSİYON GEÇMİŞİ, POLARS VE DUCKDB ENTEGRASYONU
    # ==========================================================================

    def get_version_history(self) -> list[dict[str, Any]]:
        """Kayıtlı dashboard versiyon geçmişini liste olarak döndür.

        Returns:
            list[dict[str, Any]]: Versiyon detay sözlükleri.
        """
        with self._lock:
            return [v.to_dict() for v in self._versions]

    def get_provisioning_status(self) -> dict[str, Any]:
        """Provisioning durum ve özet metriklerini getir.

        Returns:
            dict[str, Any]: Grafana URL'si, yüklenen dashboard ve veri kaynakları sayısı.
        """
        with self._lock:
            return {
                "grafana_url": self._config.url,
                "dashboards_provisioned": len(self._provisioned_dashboards),
                "datasources_provisioned": len(self._provisioned_datasources),
                "dashboard_versions_recorded": len(self._versions),
                "latest_versions": dict(self._provisioned_dashboards),
            }

    def export_versions_to_polars(self) -> pl.DataFrame:
        """Dashboard versiyon geçmişini sıfır kopyalı Polars DataFrame'e dönüştür.

        Returns:
            pl.DataFrame: Analitik ve raporlama için optimize edilmiş DataFrame.
        """
        with self._lock:
            history = [v.to_dict() for v in self._versions]

        if not history:
            return pl.DataFrame(
                schema={
                    "uid": pl.Utf8,
                    "title": pl.Utf8,
                    "version": pl.Int64,
                    "provisioned_at": pl.Utf8,
                    "file_path": pl.Utf8,
                    "status": pl.Utf8,
                }
            )

        return pl.DataFrame(history)

    def export_to_duckdb(self, db_path: str = DEFAULT_GRAFANA_AUDIT_DB_PATH) -> int:
        """Versiyon geçmişini kalıcı denetim için DuckDB tablosuna aktar.

        Args:
            db_path: DuckDB veritabanı dosya yolu.

        Returns:
            int: Başarıyla kaydedilen satır sayısı.
        """
        with self._lock:
            entries = list(self._versions)

        if not entries:
            return 0

        target_file = Path(db_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        rows = []
        for v in entries:
            rows.append(
                (
                    uuid.uuid4().hex,
                    v.uid,
                    v.title,
                    v.version,
                    v.provisioned_at,
                    v.file_path,
                    v.status,
                    orjson.dumps(v.to_dict()).decode("utf-8"),
                )
            )

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS grafana_provisioning_audit (
                        id VARCHAR PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        uid VARCHAR,
                        title VARCHAR,
                        version INTEGER,
                        provisioned_at VARCHAR,
                        file_path VARCHAR,
                        status VARCHAR,
                        metadata_json VARCHAR
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO grafana_provisioning_audit (
                        id, uid, title, version, provisioned_at, file_path, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

        logger.info("grafana_denetim_kayitlari_duckdb_aktarildi", adet=len(rows), yol=db_path)
        return len(rows)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return (
                f"GrafanaProvisioner(url='{self._config.url}', "
                f"yuklenen_dashboardlar={len(self._provisioned_dashboards)}, "
                f"veri_kaynaklari={len(self._provisioned_datasources)}, "
                f"kayitli_surumler={len(self._versions)})"
            )


# ==============================================================================
# Global Singleton ve Dışa Aktarımlar
# ==============================================================================

grafana_provisioner: GrafanaProvisioner = GrafanaProvisioner()

__all__: list[str] = [
    "DASHBOARD_DIR",
    "DEFAULT_GRAFANA_AUDIT_DB_PATH",
    "DEFAULT_GRAFANA_AUTH",
    "DEFAULT_GRAFANA_URL",
    "DEFAULT_MAX_VERSIONS",
    "DEFAULT_PROMETHEUS_URL",
    "DEFAULT_TIMEOUT_SECONDS",
    "DashboardVersion",
    "DatasourceConfig",
    "GrafanaConfig",
    "GrafanaProvisioner",
    "grafana_provisioner",
]
