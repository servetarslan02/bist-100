"""
ALPHA BIST — Grafana Provisioning

Dashboard ve datasource otomatik yükleme.

Özellikler:
- Grafana API ile dashboard yükleme
- Datasource tanımlama
- Dashboard versiyonlama
- Provisioning status takibi

Kullanım:
    provisioner = GrafanaProvisioner("http://localhost:3000", "admin:admin")
    await provisioner.provision_all()
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()

DASHBOARD_DIR = Path(__file__).parent.parent.parent / "monitoring"


@dataclass
class GrafanaConfig:
    """Grafana bağlantı yapılandırması."""
    url: str = os.environ.get("GRAFANA_URL", "http://localhost:3000")
    auth: str = os.environ.get("GRAFANA_AUTH", "admin:admin")  # user:password veya API key
    timeout: float = 30.0
    verify_ssl: bool = True


@dataclass
class DatasourceConfig:
    """Datasource yapılandırması."""
    name: str
    type: str  # prometheus, influxdb, etc.
    url: str
    access: str = "proxy"
    is_default: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_grafana_payload(self) -> Dict[str, Any]:
        payload = {
            "name": self.name,
            "type": self.type,
            "url": self.url,
            "access": self.access,
            "isDefault": self.is_default,
        }
        payload.update(self.extra)
        return payload


@dataclass
class DashboardVersion:
    """Dashboard versiyon kaydı."""
    uid: str
    title: str
    version: int
    provisioned_at: str
    file_path: str


class GrafanaProvisioner:
    """Grafana dashboard ve datasource provisioning."""

    def __init__(self, config: Optional[GrafanaConfig] = None):
        self._config = config or GrafanaConfig()
        self._versions: List[DashboardVersion] = []
        self._provisioned_dashboards: Dict[str, int] = {}  # uid → version
        self._provisioned_datasources: List[str] = []

    # =====================================================
    # DATASOURCE
    # =====================================================

    async def provision_datasource(self, ds_config: DatasourceConfig) -> bool:
        """Datasource oluştur veya güncelle."""
        try:
            import aiohttp
            url = f"{self._config.url}/api/datasources"
            auth_parts = self._config.auth.split(":")
            auth = aiohttp.BasicAuth(auth_parts[0], auth_parts[1]) if len(auth_parts) == 2 else None

            payload = ds_config.to_grafana_payload()

            async with aiohttp.ClientSession() as session:
                # Önce mevcut datasource'u kontrol et
                async with session.get(
                    f"{url}/name/{ds_config.name}",
                    auth=auth,
                    timeout=aiohttp.ClientTimeout(total=self._config.timeout),
                    ssl=self._config.verify_ssl,
                ) as resp:
                    if resp.status == 200:
                        # Güncelle
                        existing = await resp.json()
                        payload["id"] = existing["id"]
                        async with session.put(
                            f"{url}/{existing['id']}",
                            json=payload, auth=auth,
                            timeout=aiohttp.ClientTimeout(total=self._config.timeout),
                        ) as put_resp:
                            if put_resp.status == 200:
                                logger.info("Datasource updated", name=ds_config.name)
                                self._provisioned_datasources.append(ds_config.name)
                                return True

                # Yeni oluştur
                async with session.post(
                    url, json=payload, auth=auth,
                    timeout=aiohttp.ClientTimeout(total=self._config.timeout),
                    ssl=self._config.verify_ssl,
                ) as resp:
                    if resp.status in (200, 201):
                        logger.info("Datasource created", name=ds_config.name)
                        self._provisioned_datasources.append(ds_config.name)
                        return True
                    else:
                        body = await resp.text()
                        logger.error("Datasource creation failed",
                                   name=ds_config.name, status=resp.status, body=body[:200])
                        return False

        except Exception as e:
            logger.error("Datasource provisioning error", name=ds_config.name, error=str(e))
            return False

    # =====================================================
    # DASHBOARD
    # =====================================================

    async def provision_dashboard(self, file_path: str, folder_id: int = 0,
                                  overwrite: bool = True) -> Optional[int]:
        """Dashboard JSON dosyasını Grafana'ya yükle.

        Returns:
            Dashboard version numarası veya None
        """
        try:
            import aiohttp

            path = Path(file_path)
            if not path.exists():
                logger.error("Dashboard file not found", path=str(path))
                return None

            with open(path) as f:
                dashboard_data = json.load(f)

            # Grafana API payload
            payload = {
                "dashboard": dashboard_data.get("dashboard", dashboard_data),
                "folderId": folder_id,
                "overwrite": overwrite,
            }

            # UID yoksa oluştur
            if "uid" not in payload["dashboard"]:
                import hashlib
                uid = hashlib.sha256(str(path).encode()).hexdigest()[:12]
                payload["dashboard"]["uid"] = uid

            url = f"{self._config.url}/api/dashboards/db"
            auth_parts = self._config.auth.split(":")
            auth = aiohttp.BasicAuth(auth_parts[0], auth_parts[1]) if len(auth_parts) == 2 else None

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, auth=auth,
                    timeout=aiohttp.ClientTimeout(total=self._config.timeout),
                    ssl=self._config.verify_ssl,
                ) as resp:
                    if resp.status in (200, 201):
                        result = await resp.json()
                        version = result.get("version", 1)
                        uid = payload["dashboard"]["uid"]
                        title = payload["dashboard"].get("title", "unknown")

                        self._provisioned_dashboards[uid] = version
                        self._versions.append(DashboardVersion(
                            uid=uid, title=title, version=version,
                            provisioned_at=str(__import__('datetime').datetime.now(
                                __import__('datetime').timezone.utc)),
                            file_path=str(path),
                        ))

                        logger.info("Dashboard provisioned",
                                  title=title, version=version, uid=uid)
                        return version
                    else:
                        body = await resp.text()
                        logger.error("Dashboard provisioning failed",
                                   status=resp.status, body=body[:200])
                        return None

        except Exception as e:
            logger.error("Dashboard provisioning error", path=file_path, error=str(e))
            return None

    async def provision_all(self) -> Dict[str, Any]:
        """Tüm dashboard dosyalarını yükle."""
        results = {"dashboards": {}, "datasources": {}, "errors": []}

        # Datasource: Prometheus
        prom_ds = DatasourceConfig(
            name="Prometheus",
            type="prometheus",
            url=os.environ.get("PROMETHEUS_URL", "http://localhost:9090"),
            is_default=True,
        )
        ds_ok = await self.provision_datasource(prom_ds)
        results["datasources"]["Prometheus"] = "ok" if ds_ok else "failed"

        # Dashboard'ları yükle
        dashboard_file = DASHBOARD_DIR / "grafana_dashboard.json"
        if dashboard_file.exists():
            version = await self.provision_dashboard(str(dashboard_file))
            results["dashboards"]["alpha_bist"] = {
                "version": version,
                "file": str(dashboard_file),
                "status": "ok" if version else "failed",
            }
        else:
            results["errors"].append(f"Dashboard file not found: {dashboard_file}")

        return results

    # =====================================================
    # VERSION HISTORY
    # =====================================================

    def get_version_history(self) -> List[Dict[str, Any]]:
        """Dashboard versiyon geçmişi."""
        return [
            {
                "uid": v.uid,
                "title": v.title,
                "version": v.version,
                "provisioned_at": v.provisioned_at,
                "file_path": v.file_path,
            }
            for v in self._versions
        ]

    def get_provisioning_status(self) -> Dict[str, Any]:
        """Provisioning durumu."""
        return {
            "grafana_url": self._config.url,
            "dashboards_provisioned": len(self._provisioned_dashboards),
            "datasources_provisioned": len(self._provisioned_datasources),
            "dashboard_versions": len(self._versions),
            "latest_versions": {
                uid: ver for uid, ver in self._provisioned_dashboards.items()
            },
        }


# Default provisioner
grafana_provisioner = GrafanaProvisioner()
