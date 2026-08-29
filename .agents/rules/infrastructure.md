# Infrastructure, Containers and Services

> bist-100 projesi için container, port ve servis kuralları.

1. **Docker Compose:**
   - Dosya: `docker-compose.yml` (Project: `bist-100-main`, Network: `alpha-net`)
   - Traefik (`alpha-traefik`): Web: `80`, SSL: `443`, Dashboard: `8080`
   - PostgreSQL (`alpha-postgres`): TimescaleDB PG17, Port: `5432`, DB: `alpha_bist`, User: `alpha`
   - Postgres Replica (`alpha-postgres-replica`): Port: `5433`
   - ClickHouse (`alpha-clickhouse`): HTTP: `8123`, Native: `9002`, DB: `alpha_bist`
   - Redis (`alpha-redis`): Port: `6379`, Sentinel: `26379`
   - Traefik API router rule: `/api`, `/health`, `/docs`, `/openapi.json` -> `api:8000`

2. **Terminal ve Host:**
   - Host işletim sistemi Windows PowerShell'dir.
   - Script çalıştırma: `uv run python <script_name>.py`
   - Asla Linux bash sözdizimi ile Windows terminalinde komut çalıştırma.
