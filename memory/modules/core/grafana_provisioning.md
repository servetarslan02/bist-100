# core/grafana_provisioning

**Dosya:** `services/core/grafana_provisioning.py`
**Satır:** 266

## Açıklama

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

## Sınıflar (4)

- `GrafanaConfig`
- `DatasourceConfig`
- `DashboardVersion`
- `GrafanaProvisioner`

## Fonksiyonlar (4)

- `to_grafana_payload()`
- `__init__()`
- `get_version_history()`
- `get_provisioning_status()`

