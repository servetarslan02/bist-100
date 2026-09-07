"""ALPHA BIST — Grafana Dashboard ve Veri Kaynağı Sağlama (Provisioning) Modülü.

Bu modül, platform metriklerinin ve piyasa izleme ekranlarının Grafana üzerinde
otomatik olarak yapılandırılmasını, dashboard JSON tanımlarının yüklenmesini,
Prometheus ve ClickHouse veri kaynaklarının (datasource) tanımlanmasını, klasör,
uyarı kuralları (alert rules) ve versiyon yönetimini sağlar.

Temel Yetenekler:
- Grafana REST API entegrasyonu (Basic Auth, API Token, Bearer Token, Service Account).
- Veri kaynağı (Datasource) oluşturma ve yerinde güncelleme (Prometheus & ClickHouse).
- Dashboard JSON dosyalarının taranması, deterministik UID sağlama ve versiyonlama.
- Klasör (Folder) yönetimi ve çakışma çözümleme.
- Dashboard arama, sorgulama ve silme REST işlemleri.
- Uyarı kuralları (alert_rules.json) ayrıştırma ve doğrulama.
- Sistem sağlık kontrolü (Health Check / Liveness / Readiness).
- Polars DataFrame ile dashboard versiyon geçmişi ihracı (katı şema garantili).
- DuckDB ile denetim izi (Audit Trail) kaydı ve sıfır kopyalı native .pl() sorgulama.
- Context manager desteği (senkron ve asenkron oturum yönetimi).
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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

DEFAULT_GRAFANA_URL: Final[str] = "http://localhost:3000"
DEFAULT_GRAFANA_AUTH: Final[str] = "admin:admin"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_HEALTH_TIMEOUT_SECONDS: Final[float] = 5.0
DEFAULT_MAX_VERSIONS: Final[int] = 1000
DEFAULT_PROMETHEUS_URL: Final[str] = "http://localhost:9090"
DEFAULT_CLICKHOUSE_URL: Final[str] = "http://localhost:8123"
DEFAULT_CLICKHOUSE_DS_NAME: Final[str] = "ClickHouse"
DEFAULT_GRAFANA_AUDIT_DB_PATH: Final[str] = "data/grafana_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)

VALID_DASHBOARD_STATUSES: Final[frozenset[str]] = frozenset(
    {"SUCCESS", "FAILED", "SKIPPED", "FAILED_IO", "FAILED_JSON", "NOT_FOUND"}
)

DASHBOARD_DIR: Final[Path] = Path(__file__).resolve().parent.parent.parent / "monitoring"


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
        clean_auth = self.auth.strip()
        if ":" in clean_auth:
            user = clean_auth.split(":", 1)[0]
            masked_auth = f"{user}:***"
        elif len(clean_auth) > 8:
            masked_auth = f"{clean_auth[:4]}...{clean_auth[-4:]}"

        return {
            "url": self.url.strip().rstrip("/"),
            "auth": masked_auth,
            "timeout": float(self.timeout),
            "verify_ssl": bool(self.verify_ssl),
            "org_id": int(self.org_id),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"GrafanaConfig(url='{self.url.strip().rstrip('/')}', timeout={self.timeout}s, "
            f"verify_ssl={self.verify_ssl}, org_id={self.org_id})"
        )


@dataclass(slots=True)
class DatasourceConfig:
    """Grafana veri kaynağı (Datasource) yapılandırması.

    Attributes:
        name: Veri kaynağı adı (örn: 'Prometheus', 'ClickHouse').
        type: Kaynak türü ('prometheus', 'clickhouse', 'influxdb' vb.).
        url: Kaynak hedef sunucu adresi (örn: 'http://localhost:9090').
        access: Erişim türü ('proxy' veya 'direct').
        is_default: Varsayılan veri kaynağı olarak atansın mı.
        database: Hedef veritabanı adı (opsiyonel, ClickHouse için).
        extra: Ek veri kaynağı parametreleri (HTTP başlıkları, JSONData vb.).
    """

    name: str
    type: str
    url: str
    access: str = "proxy"
    is_default: bool = False
    database: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_grafana_payload(self) -> dict[str, Any]:
        """Grafana REST API payload sözlüğüne dönüştür."""
        payload: dict[str, Any] = {
            "name": self.name.strip(),
            "type": self.type.strip().lower(),
            "url": self.url.strip().rstrip("/"),
            "access": self.access.strip().lower(),
            "isDefault": bool(self.is_default),
        }
        if self.database:
            payload["database"] = self.database.strip()

        if self.extra:
            payload.update(self.extra)
        return payload

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür."""
        return self.to_grafana_payload()

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt serileştirmesi."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"DatasourceConfig(ad='{self.name}', tur='{self.type}', url='{self.url}', "
            f"varsayilan={self.is_default})"
        )


@dataclass(slots=True)
class DashboardVersion:
    """Dashboard yükleme ve versiyon kayıt modeli.

    Attributes:
        uid: Dashboard benzersiz kimliği (12 karakterli UID).
        title: Dashboard başlığı.
        version: Grafana versiyon numarası (-1 ise hata).
        provisioned_at: Yükleme zaman damgası (ISO 8601 UTC).
        file_path: Kaynak JSON dosya yolu.
        status: Yükleme durumu ('SUCCESS', 'FAILED', 'FAILED_IO', 'FAILED_JSON' vb.).
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
            "version": int(self.version),
            "provisioned_at": self.provisioned_at,
            "file_path": self.file_path,
            "status": self.status,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict(), default=str)

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
            config: Grafana bağlantı ayarları (None ise varsayılan GrafanaConfig).
        """
        self._config = config or GrafanaConfig()
        self._lock = threading.RLock()
        self._versions: deque[DashboardVersion] = deque(maxlen=DEFAULT_MAX_VERSIONS)
        self._provisioned_dashboards: dict[str, int] = {}  # uid -> version
        self._provisioned_datasources: list[str] = []
        self._shared_client: httpx.AsyncClient | None = None

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
        """Yapılandırılmış yeni asenkron HTTP istemcisi üret.

        Returns:
            httpx.AsyncClient: İstemci nesnesi.
        """
        auth, headers = self._get_auth_and_headers()
        return httpx.AsyncClient(
            auth=auth,
            headers=headers,
            timeout=httpx.Timeout(self._config.timeout),
            verify=self._config.verify_ssl,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[httpx.AsyncClient]:
        """Yeniden kullanılabilir asenkron istemci oturumu bağlamı.

        Yields:
            httpx.AsyncClient: Aktif HTTP oturumu.
        """
        async with self._create_client() as client:
            yield client

    # ==========================================================================
    # CONTEXT MANAGER PROTOKOLÜ
    # ==========================================================================

    def __enter__(self) -> GrafanaProvisioner:
        """Senkron bağlam yöneticisi girişi."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Senkron bağlam yöneticisi çıkışı."""
        self.clear_in_memory_state()

    async def __aenter__(self) -> GrafanaProvisioner:
        """Asenkron bağlam yöneticisi girişi."""
        auth, headers = self._get_auth_and_headers()
        self._shared_client = httpx.AsyncClient(
            auth=auth,
            headers=headers,
            timeout=httpx.Timeout(self._config.timeout),
            verify=self._config.verify_ssl,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Asenkron bağlam yöneticisi çıkışı."""
        if self._shared_client is not None:
            await self._shared_client.aclose()
            self._shared_client = None

    # ==========================================================================
    # SAĞLIK VE DURUM KONTROLÜ
    # ==========================================================================

    @otel_trace("grafana.check_health")
    async def check_health(self, timeout: float = DEFAULT_HEALTH_TIMEOUT_SECONDS) -> bool:
        """Grafana sunucusunun erişilebilir ve sağlıklı olduğunu doğrula.

        Args:
            timeout: Sağlık kontrolü için maksimum bekleme süresi (saniye).

        Returns:
            bool: Grafana /api/health endpoint'i 200 dönüyorsa True, aksi halde False.
        """
        base = self._config.url.strip().rstrip("/")
        url = f"{base}/api/health"
        auth, headers = self._get_auth_and_headers()

        try:
            async with httpx.AsyncClient(
                auth=auth,
                headers=headers,
                timeout=httpx.Timeout(timeout),
                verify=self._config.verify_ssl,
            ) as client:
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
        base_url = f"{self._config.url.strip().rstrip('/')}/api/datasources"
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

    @otel_trace("grafana.provision_clickhouse_datasource")
    async def provision_clickhouse_datasource(
        self,
        name: str = DEFAULT_CLICKHOUSE_DS_NAME,
        url: str = DEFAULT_CLICKHOUSE_URL,
        database: str = "alpha_bist",
        is_default: bool = False,
    ) -> bool:
        """ClickHouse veri kaynağını (Datasource) otomatik olarak yapılandır.

        Args:
            name: Veri kaynağı adı (varsayılan: 'ClickHouse').
            url: ClickHouse HTTP adresi (varsayılan: 'http://localhost:8123').
            database: Varsayılan veritabanı adı.
            is_default: Varsayılan veri kaynağı olarak atansın mı.

        Returns:
            bool: Sağlama başarılı ise True, aksi halde False.
        """
        ds_config = DatasourceConfig(
            name=name,
            type="clickhouse",
            url=url,
            access="proxy",
            is_default=is_default,
            database=database,
            extra={
                "jsonData": {
                    "defaultDatabase": database,
                    "port": 8123,
                    "protocol": "http",
                }
            },
        )
        return await self.provision_datasource(ds_config)

    @otel_trace("grafana.list_datasources")
    async def list_datasources(self) -> list[dict[str, Any]]:
        """Kayıtlı tüm Grafana veri kaynaklarını listele.

        Returns:
            list[dict[str, Any]]: Veri kaynağı sözlükleri listesi.
        """
        url = f"{self._config.url.strip().rstrip('/')}/api/datasources"
        try:
            async with self._create_client() as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return list(orjson.loads(resp.content))
                logger.error("veri_kaynaklari_listeleme_basarisiz", status=resp.status_code)
                return []
        except Exception as e:
            logger.error("veri_kaynaklari_listeleme_istisnasi", hata=str(e))
            return []

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
        clean_title = title.strip()
        base_url = f"{self._config.url.strip().rstrip('/')}/api/folders"
        folder_uid = uid.strip() if uid else hashlib.sha256(clean_title.encode("utf-8")).hexdigest()[:10]
        payload = {"title": clean_title, "uid": folder_uid}

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
                    logger.info("grafana_klasor_olusturuldu", baslik=clean_title, id=folder_id, uid=folder_uid)
                    return folder_id

                # Çakışma (409) durumunda tüm klasörleri tarayıp başlığa göre bul
                if post_resp.status_code == 409:
                    list_resp = await client.get(base_url)
                    if list_resp.status_code == 200:
                        for item in orjson.loads(list_resp.content):
                            if item.get("title") == clean_title:
                                return int(item.get("id", 0))

                logger.error(
                    "grafana_klasor_olusturma_basarisiz",
                    baslik=clean_title,
                    status=post_resp.status_code,
                    govde=post_resp.text[:200],
                )
                return None
        except Exception as e:
            logger.error("grafana_klasor_hatasi", baslik=clean_title, hata=str(e))
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
        now_iso = datetime.now(UTC).isoformat()
        safe_folder_id = max(0, int(folder_id))

        if not path.exists():
            logger.error("dashboard_dosyasi_bulunamadi", yol=str(path))
            with self._lock:
                self._versions.append(
                    DashboardVersion(
                        uid=path.stem[:12],
                        title=path.stem,
                        version=-1,
                        provisioned_at=now_iso,
                        file_path=str(path),
                        status="NOT_FOUND",
                    )
                )
            return None

        try:
            raw_data = path.read_bytes()
            dashboard_data = orjson.loads(raw_data)
        except Exception as e:
            logger.error("dashboard_json_cozumleme_hatasi", yol=str(path), hata=str(e))
            with self._lock:
                self._versions.append(
                    DashboardVersion(
                        uid=path.stem[:12],
                        title=path.stem,
                        version=-1,
                        provisioned_at=now_iso,
                        file_path=str(path),
                        status=f"FAILED_IO_{type(e).__name__}",
                    )
                )
            return None

        dashboard_obj = dashboard_data.get("dashboard", dashboard_data)
        if not isinstance(dashboard_obj, dict):
            logger.error("gecersiz_dashboard_formati", yol=str(path))
            with self._lock:
                self._versions.append(
                    DashboardVersion(
                        uid=path.stem[:12],
                        title=path.stem,
                        version=-1,
                        provisioned_at=now_iso,
                        file_path=str(path),
                        status="FAILED_JSON",
                    )
                )
            return None

        # UID yoksa dosya yolundan deterministik üret
        if "uid" not in dashboard_obj or not dashboard_obj["uid"]:
            uid = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
            dashboard_obj["uid"] = uid
        else:
            uid = str(dashboard_obj["uid"]).strip()

        title = str(dashboard_obj.get("title", path.stem)).strip()
        payload = {
            "dashboard": dashboard_obj,
            "folderId": safe_folder_id,
            "overwrite": overwrite,
        }

        url = f"{self._config.url.strip().rstrip('/')}/api/dashboards/db"

        try:
            async with self._create_client() as client:
                resp = await client.post(url, json=payload)
                if resp.status_code in (200, 201):
                    result = orjson.loads(resp.content)
                    raw_ver = result.get("version")
                    version = int(raw_ver) if raw_ver is not None else 1

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

    @otel_trace("grafana.get_dashboard")
    async def get_dashboard(self, uid: str) -> dict[str, Any] | None:
        """Belirtilen UID'ye sahip dashboard'u Grafana'dan getir.

        Args:
            uid: Dashboard benzersiz kimliği.

        Returns:
            dict[str, Any] | None: Dashboard JSON içeriği veya bulunamazsa None.
        """
        clean_uid = uid.strip()
        url = f"{self._config.url.strip().rstrip('/')}/api/dashboards/uid/{clean_uid}"
        try:
            async with self._create_client() as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return dict(orjson.loads(resp.content))
                logger.warning("dashboard_bulunamadi", uid=clean_uid, status=resp.status_code)
                return None
        except Exception as e:
            logger.error("dashboard_getirme_istisnasi", uid=clean_uid, hata=str(e))
            return None

    @otel_trace("grafana.delete_dashboard")
    async def delete_dashboard(self, uid: str) -> bool:
        """Belirtilen UID'ye sahip dashboard'u Grafana'dan sil.

        Args:
            uid: Silinecek dashboard UID'si.

        Returns:
            bool: Silme işlemi başarılı ise True, aksi halde False.
        """
        clean_uid = uid.strip()
        url = f"{self._config.url.strip().rstrip('/')}/api/dashboards/uid/{clean_uid}"
        try:
            async with self._create_client() as client:
                resp = await client.delete(url)
                if resp.status_code == 200:
                    with self._lock:
                        self._provisioned_dashboards.pop(clean_uid, None)
                    logger.info("dashboard_silindi", uid=clean_uid)
                    return True
                logger.error("dashboard_silme_basarisiz", uid=clean_uid, status=resp.status_code)
                return False
        except Exception as e:
            logger.error("dashboard_silme_istisnasi", uid=clean_uid, hata=str(e))
            return False

    @otel_trace("grafana.search_dashboards")
    async def search_dashboards(self, query: str = "") -> list[dict[str, Any]]:
        """Grafana üzerinde dashboard araması yap.

        Args:
            query: Arama metni (boş ise tüm dashboardlar).

        Returns:
            list[dict[str, Any]]: Eşleşen dashboard listesi.
        """
        url = f"{self._config.url.strip().rstrip('/')}/api/search?type=dash-db&query={query.strip()}"
        try:
            async with self._create_client() as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return list(orjson.loads(resp.content))
                logger.error("dashboard_arama_basarisiz", status=resp.status_code)
                return []
        except Exception as e:
            logger.error("dashboard_arama_istisnasi", hata=str(e))
            return []

    # ==========================================================================
    # UYARI KURALLARI VE TOPLU SAĞLAMA
    # ==========================================================================

    def load_alert_rules(self, file_path: Path | str | None = None) -> list[dict[str, Any]]:
        """monitoring/alert_rules.json dosyasını oku ve kuralları doğrula.

        Args:
            file_path: Kural dosya yolu (None ise varsayılan monitoring/alert_rules.json).

        Returns:
            list[dict[str, Any]]: Ayrıştırılan geçerli kural listesi.
        """
        target_path = Path(file_path) if file_path else DASHBOARD_DIR / "alert_rules.json"
        if not target_path.exists():
            logger.warning("uyari_kurallari_dosyasi_bulunamadi", yol=str(target_path))
            return []

        try:
            content = target_path.read_bytes()
            data = orjson.loads(content)
            rules = data.get("alert_rules", [])
            if isinstance(rules, list):
                logger.info("uyari_kurallari_yuklendi", kural_sayisi=len(rules), yol=str(target_path))
                return rules
            return []
        except Exception as e:
            logger.error("uyari_kurallari_okuma_hatasi", yol=str(target_path), hata=str(e))
            return []

    @otel_trace("grafana.provision_all")
    async def provision_all(
        self,
        dashboard_dir: Path | str | None = None,
        provision_clickhouse: bool = True,
    ) -> dict[str, Any]:
        """Tüm standart veri kaynaklarını ve dashboard dosyalarını toplu yükle.

        Args:
            dashboard_dir: Dashboard JSON dosyalarının bulunduğu dizin (None ise DASHBOARD_DIR).
            provision_clickhouse: ClickHouse veri kaynağı da sağlansın mı.

        Returns:
            dict[str, Any]: Yükleme sonuçları ve durum raporu.
        """
        target_dir = Path(dashboard_dir) if dashboard_dir else DASHBOARD_DIR
        results: dict[str, Any] = {
            "datasources": {},
            "dashboards": {},
            "alert_rules_loaded": 0,
            "errors": [],
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # 1. Standart Veri Kaynağı: Prometheus
        prom_ds = DatasourceConfig(
            name="Prometheus",
            type="prometheus",
            url=DEFAULT_PROMETHEUS_URL,
            is_default=True,
        )
        prom_ok = await self.provision_datasource(prom_ds)
        results["datasources"]["Prometheus"] = "ok" if prom_ok else "failed"

        # 2. Standart Veri Kaynağı: ClickHouse
        if provision_clickhouse:
            ch_ok = await self.provision_clickhouse_datasource(
                name=DEFAULT_CLICKHOUSE_DS_NAME,
                url=DEFAULT_CLICKHOUSE_URL,
                database="alpha_bist",
                is_default=False,
            )
            results["datasources"]["ClickHouse"] = "ok" if ch_ok else "failed"

        # 3. Uyarı Kurallarını Tara
        alert_rules = self.load_alert_rules()
        results["alert_rules_loaded"] = len(alert_rules)

        # 4. Dizin içerisindeki dashboard dosyalarını tara
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
            uyari_kurallari=results["alert_rules_loaded"],
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

    def get_provisioned_dashboards(self) -> dict[str, int]:
        """Sağlanan güncel dashboard UID -> version eşleşmesini getir.

        Returns:
            dict[str, int]: UID -> versiyon haritası.
        """
        with self._lock:
            return dict(self._provisioned_dashboards)

    def get_provisioned_datasources(self) -> list[str]:
        """Sağlanan veri kaynakları listesini getir.

        Returns:
            list[str]: Veri kaynağı isimleri listesi.
        """
        with self._lock:
            return list(self._provisioned_datasources)

    def clear_in_memory_state(self) -> None:
        """Bellekteki versiyon ve dashboard kayıtlarını sıfırla."""
        with self._lock:
            self._versions.clear()
            self._provisioned_dashboards.clear()
            self._provisioned_datasources.clear()

    def get_provisioning_status(self) -> dict[str, Any]:
        """Provisioning durum ve özet metriklerini getir.

        Returns:
            dict[str, Any]: Grafana URL'si, yüklenen dashboard ve veri kaynakları sayısı.
        """
        with self._lock:
            return {
                "grafana_url": self._config.url.strip().rstrip("/"),
                "dashboards_provisioned": len(self._provisioned_dashboards),
                "datasources_provisioned": len(self._provisioned_datasources),
                "dashboard_versions_recorded": len(self._versions),
                "latest_versions": dict(self._provisioned_dashboards),
            }

    def export_versions_to_polars(self) -> pl.DataFrame:
        """Dashboard versiyon geçmişini sıfır kopyalı Polars DataFrame'e dönüştür (GEMINI.md Kural 2).

        Returns:
            pl.DataFrame: Katı şemalı analitik veri çerçevesi.
        """
        with self._lock:
            history = [v.to_dict() for v in self._versions]

        schema: dict[str, pl.DataType] = {
            "uid": pl.Utf8,
            "title": pl.Utf8,
            "version": pl.Int64,
            "provisioned_at": pl.Utf8,
            "file_path": pl.Utf8,
            "status": pl.Utf8,
        }

        if not history:
            return pl.DataFrame(schema=schema)

        return pl.DataFrame(history, schema=schema)

    def export_to_duckdb(self, db_path: str = DEFAULT_GRAFANA_AUDIT_DB_PATH) -> int:
        """Versiyon geçmişini kalıcı denetim için DuckDB tablosuna aktar (GEMINI.md Kural 5).

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

        rows = [
            (
                uuid.uuid4().hex,
                v.uid,
                v.title,
                v.version,
                v.provisioned_at,
                v.file_path,
                v.status,
                orjson.dumps(v.to_dict(), default=str).decode("utf-8"),
            )
            for v in entries
        ]

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                configure_duckdb_wal(conn)
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

    def query_provisioning_audit_duckdb(
        self,
        db_path: str = DEFAULT_GRAFANA_AUDIT_DB_PATH,
        status: str | None = None,
        uid: str | None = None,
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak sorgula (GEMINI.md Kural 2 & 5).

        Args:
            db_path: DuckDB dosya yolu.
            status: Opsiyonel durum filtresi ('SUCCESS', 'FAILED' vb.).
            uid: Opsiyonel dashboard UID filtresi.
            limit: Maksimum satır sayısı.

        Returns:
            pl.DataFrame: Filtrelenmiş sıfır kopyalı Polars tablosu.
        """
        target_file = Path(db_path)
        safe_limit = max(1, int(limit))

        schema: dict[str, pl.DataType] = {
            "id": pl.Utf8,
            "created_at": pl.Datetime,
            "uid": pl.Utf8,
            "title": pl.Utf8,
            "version": pl.Int64,
            "provisioned_at": pl.Utf8,
            "file_path": pl.Utf8,
            "status": pl.Utf8,
            "metadata_json": pl.Utf8,
        }

        if not target_file.exists():
            return pl.DataFrame(schema=schema)

        with self._lock:
            with duckdb.connect(str(target_file)) as conn:
                configure_duckdb_wal(conn)
                # Tablo var mı kontrol et
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name = 'grafana_provisioning_audit'"
                ).fetchall()
                if not tables:
                    return pl.DataFrame(schema=schema)

                query = "SELECT * FROM grafana_provisioning_audit WHERE 1=1"
                params: list[Any] = []

                if status:
                    query += " AND status = ?"
                    params.append(status.strip().upper())
                if uid:
                    query += " AND uid = ?"
                    params.append(uid.strip())

                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(safe_limit)

                return conn.execute(query, params).pl()

    def to_dict(self) -> dict[str, Any]:
        """Sağlayıcı durumunu sözlük olarak döner."""
        with self._lock:
            return {
                "url": self._config.url.strip().rstrip("/"),
                "provisioned_dashboards_count": len(self._provisioned_dashboards),
                "provisioned_datasources_count": len(self._provisioned_datasources),
                "versions_count": len(self._versions),
            }

    def to_orjson_bytes(self) -> bytes:
        """Sağlayıcı durumunu ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def clear_audit_duckdb(self, db_path: str = DEFAULT_GRAFANA_AUDIT_DB_PATH) -> None:
        """DuckDB Grafana denetim tablosunu sıfırlar."""
        clear_grafana_audit_duckdb(db_path=db_path)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return (
                f"GrafanaProvisioner(url='{self._config.url.strip().rstrip('/')}', "
                f"yuklenen_dashboardlar={len(self._provisioned_dashboards)}, "
                f"veri_kaynaklari={len(self._provisioned_datasources)}, "
                f"kayitli_surumler={len(self._versions)})"
            )


# ==============================================================================
# Global Singleton ve Modül Seviyesi Kolaylık Fonksiyonları
# ==============================================================================

grafana_provisioner: GrafanaProvisioner = GrafanaProvisioner()


def get_grafana_provisioner() -> GrafanaProvisioner:
    """GrafanaProvisioner singleton örneğini döndürür."""
    return grafana_provisioner


async def check_grafana_health(timeout: float = DEFAULT_HEALTH_TIMEOUT_SECONDS) -> bool:
    """Grafana sunucusunun sağlıklı olup olmadığını kontrol eder."""
    return await grafana_provisioner.check_health(timeout=timeout)


async def provision_grafana_datasource(ds_config: DatasourceConfig) -> bool:
    """Grafana veri kaynağı oluşturur veya günceller."""
    return await grafana_provisioner.provision_datasource(ds_config=ds_config)


async def provision_grafana_clickhouse(
    name: str = DEFAULT_CLICKHOUSE_DS_NAME,
    url: str = DEFAULT_CLICKHOUSE_URL,
    database: str = "alpha_bist",
    is_default: bool = False,
) -> bool:
    """ClickHouse veri kaynağını Grafana üzerinde yapılandırır."""
    return await grafana_provisioner.provision_clickhouse_datasource(
        name=name,
        url=url,
        database=database,
        is_default=is_default,
    )


async def provision_grafana_dashboard(
    file_path: str | Path,
    folder_id: int = 0,
    overwrite: bool = True,
) -> int | None:
    """Dashboard JSON dosyasını Grafana'ya yükler ve versiyonlar."""
    return await grafana_provisioner.provision_dashboard(
        file_path=file_path,
        folder_id=folder_id,
        overwrite=overwrite,
    )


async def provision_grafana_all(
    dashboard_dir: Path | str | None = None,
    provision_clickhouse: bool = True,
) -> dict[str, Any]:
    """Tüm dashboard ve veri kaynaklarını Grafana'ya toplu olarak sağlar."""
    return await grafana_provisioner.provision_all(
        dashboard_dir=dashboard_dir,
        provision_clickhouse=provision_clickhouse,
    )


def export_grafana_versions_to_polars() -> pl.DataFrame:
    """Grafana dashboard versiyon geçmişini Polars DataFrame olarak döndürür."""
    return grafana_provisioner.export_versions_to_polars()


def export_grafana_audit_to_duckdb(db_path: str = DEFAULT_GRAFANA_AUDIT_DB_PATH) -> int:
    """Grafana versiyon geçmişini DuckDB tablosuna kaydeder."""
    return grafana_provisioner.export_to_duckdb(db_path=db_path)


def query_grafana_audit_duckdb(
    db_path: str = DEFAULT_GRAFANA_AUDIT_DB_PATH,
    status: str | None = None,
    uid: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosundan Polars DataFrame olarak sorgu çeker."""
    return grafana_provisioner.query_provisioning_audit_duckdb(
        db_path=db_path,
        status=status,
        uid=uid,
        limit=limit,
    )


def get_grafana_provisioning_status() -> dict[str, Any]:
    """Grafana sağlayıcı durum özetini döndürür."""
    return grafana_provisioner.get_provisioning_status()


def read_grafana_audit_from_duckdb(
    db_path: str = DEFAULT_GRAFANA_AUDIT_DB_PATH,
    status: str | None = None,
    uid: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        status: İsteğe bağlı durum filtresi.
        uid: İsteğe bağlı dashboard UID filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Okunan denetim kayıtları.
    """
    path_obj = Path(db_path)
    schema: dict[str, pl.DataType] = {
        "id": pl.Utf8,
        "created_at": pl.Datetime,
        "uid": pl.Utf8,
        "title": pl.Utf8,
        "version": pl.Int64,
        "provisioned_at": pl.Utf8,
        "file_path": pl.Utf8,
        "status": pl.Utf8,
        "metadata_json": pl.Utf8,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'grafana_provisioning_audit'"
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = "SELECT * FROM grafana_provisioning_audit WHERE 1=1"
            params: list[Any] = []

            if status:
                query += " AND status = ?"
                params.append(status.strip().upper())
            if uid:
                query += " AND uid = ?"
                params.append(uid.strip())

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(max(1, int(limit)))

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_grafana_audit_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_grafana_audit_duckdb(db_path: str = DEFAULT_GRAFANA_AUDIT_DB_PATH) -> None:
    """DuckDB'deki Grafana denetim tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS grafana_provisioning_audit;")
    except Exception as exc:
        logger.error("duckdb_grafana_audit_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__: Final[list[str]] = [
    # Sabitler
    "DASHBOARD_DIR",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_CLICKHOUSE_DS_NAME",
    "DEFAULT_CLICKHOUSE_URL",
    "DEFAULT_GRAFANA_AUDIT_DB_PATH",
    "DEFAULT_GRAFANA_AUTH",
    "DEFAULT_GRAFANA_URL",
    "DEFAULT_HEALTH_TIMEOUT_SECONDS",
    "DEFAULT_MAX_VERSIONS",
    "DEFAULT_PROMETHEUS_URL",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_WAL_SIZE",
    "VALID_DASHBOARD_STATUSES",
    # Veri Modelleri ve Ana Motor
    "DashboardVersion",
    "DatasourceConfig",
    "GrafanaConfig",
    "GrafanaProvisioner",
    # Singleton
    "grafana_provisioner",
    # Modül Seviyesi Kolaylık Fonksiyonları
    "check_grafana_health",
    "clear_grafana_audit_duckdb",
    "configure_duckdb_wal",
    "export_grafana_audit_to_duckdb",
    "export_grafana_versions_to_polars",
    "get_grafana_provisioner",
    "get_grafana_provisioning_status",
    "provision_grafana_all",
    "provision_grafana_clickhouse",
    "provision_grafana_dashboard",
    "provision_grafana_datasource",
    "query_grafana_audit_duckdb",
    "read_grafana_audit_from_duckdb",
    "to_orjson_bytes",
]
