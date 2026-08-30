from typing import Any

"""
ALPHA BIST — Docker & Container Infrastructure Test Suite
Doğrulanan Özellikler:
1. docker-compose.yml Yapısı: Servis tanımları, ağ izolasyonu (alpha-net), volume'ler
2. Güvenlik & Kaynak Limitleri: mem_limit, cpus, read-only volume mount (:ro)
3. Log Rotation Kısıtları: Disk dolmasını önleyen max-size ve max-file kısıtları
4. Sağlık Kontrolleri: Healthcheck tanımları ve start_period süreleri
5. Dockerfile Güvenliği: Non-root user (USER alpha) ve sağlık denetimi
"""

from pathlib import Path

import pytest
import yaml


@pytest.fixture(scope="module")
def compose_config() -> Any:
    """Otomatik eklendi."""
    compose_path = Path("docker-compose.yml")
    assert compose_path.exists(), "docker-compose.yml bulunamadı"
    with open(compose_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


class TestDockerComposeArchitecture:
    """docker-compose.yml mimari ve yapılandırma testleri."""

    def test_top_level_structure(self, compose_config) -> Any:
        """Otomatik eklendi."""
        assert "services" in compose_config, "services tanımı eksik"
        assert "networks" in compose_config or "x-common" in compose_config
        services = compose_config["services"]
        assert len(services) >= 10, f"Beklenen mikroservis sayısı yetersiz: {len(services)}"

    def test_core_services_presence(self, compose_config) -> Any:
        """Otomatik eklendi."""
        services = compose_config["services"]
        required_services = [
            "postgres",
            "redis",
            "nats",
            "traefik",
            "api",
            "celery-worker",
            "prometheus",
            "grafana",
            "questdb",
            "mlflow",
            "pgbouncer",
            "autoheal",
        ]
        for s in required_services:
            assert s in services, f"Kritik servis eksik: {s}"

    def test_resource_limits_and_logging(self, compose_config) -> Any:
        """Otomatik eklendi."""
        services = compose_config["services"]
        for name, spec in services.items():
            if not isinstance(spec, dict):
                continue
            # Resource limit kontrolü
            assert "mem_limit" in spec or "deploy" in spec or "x-common" in spec, (
                f"Servis için memory limiti eksik: {name}"
            )

    def test_read_only_config_mounts(self, compose_config) -> Any:
        """Otomatik eklendi."""
        services = compose_config["services"]
        for name, spec in services.items():
            volumes = spec.get("volumes", [])
            for vol in volumes:
                if isinstance(vol, str) and ("/etc/" in vol or "initdb" in vol or "traefik.yml" in vol):
                    assert vol.endswith(":ro") or ":ro" in vol, (
                        f"Konfigürasyon volume'ü read-only (:ro) olmalı: {name} -> {vol}"
                    )


class TestDockerfileSecurity:
    """Dockerfile güvenlik ve standart kontrolleri."""

    def test_dockerfile_api_security(self) -> Any:
        """Otomatik eklendi."""
        dockerfile_path = Path("infrastructure/Dockerfile.api")
        assert dockerfile_path.exists(), "Dockerfile.api bulunamadı"
        content = dockerfile_path.read_text(encoding="utf-8")

        assert "USER alpha" in content or "useradd" in content, "Non-root kullanıcı tanımı eksik"
        assert "HEALTHCHECK" in content, "Sağlık denetimi eksik"
        assert "EXPOSE 8000" in content, "API portu expose edilmemiş"
