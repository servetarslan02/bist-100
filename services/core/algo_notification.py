"""ALPHA BIST — SPK Algoritmik İşlem Bildirim Modülü (Enterprise-Grade).

Bu modül, Sermaye Piyasası Kurulu (SPK) mevzuatı ve BIST düzenlemeleri uyarınca,
otonom veya yarı otonom çalışan algoritmik alım-satım stratejilerinin
kayıt altına alınmasını, standart bildirim formatına dönüştürülmesini ve
DuckDB üzerinde denetim iziyle (audit trail) kalıcı olarak saklanmasını sağlar.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import duckdb
import orjson
import structlog
from opentelemetry import trace

if TYPE_CHECKING:
    import polars as pl

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.algo_notification")

# Standart SPK ve BIST Algoritmik İşlem Parametre Sabitleri
DEFAULT_STRATEGY_NAME = "GENERIC_BIST_ALGO"
DEFAULT_STRATEGY_TYPE = "QUANT_MOMENTUM"
DEFAULT_RISK_LEVEL = "MEDIUM"
DEFAULT_MARKET = "BIST_EQUITY"
DEFAULT_OPERATOR = "ALPHA_BIST_SYSTEM"
VALID_RISK_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})


@dataclass(slots=True)
class AlgoNotification:
    """SPK algoritmik işlem bildirimi veri modeli.

    Attributes:
        notification_id: Benzersiz SPK bildirim kayıt kimliği.
        notification_type: Bildirim türü (daima ALGO_TRADING).
        strategy_name: Algoritma veya model tanımlayıcısı.
        strategy_type: Strateji metodolojisi (momentum, arbitraj vb.).
        description: Strateji açıklaması ve işlem hedefi.
        risk_level: Risk seviyesi (LOW, MEDIUM, HIGH, CRITICAL).
        market: İşlem yapılan pazar (ör. BIST_EQUITY, BIST_VIOP).
        parameters: Stratejiye ait dinamik çalışma parametreleri.
        kill_switch_enabled: Acil durdurma anahtarı güvencesi.
        operator: İşlemden sorumlu sistem veya lisanslı kullanıcı.
        auto_generated: Sistemin otomatik ürettiği bildirimi belirtir.
        timestamp: Unix zaman damgası (saniye).
        timestamp_iso: UTC ISO-8601 zaman damgası.
        compliance_status: Mevzuata uygunluk durumu.
    """

    notification_id: str
    notification_type: str = "ALGO_TRADING"
    strategy_name: str = DEFAULT_STRATEGY_NAME
    strategy_type: str = DEFAULT_STRATEGY_TYPE
    description: str = "BIST otomatik algoritma stratejisi"
    risk_level: str = DEFAULT_RISK_LEVEL
    market: str = DEFAULT_MARKET
    parameters: dict[str, Any] = field(default_factory=dict)
    kill_switch_enabled: bool = True
    operator: str = DEFAULT_OPERATOR
    auto_generated: bool = True
    timestamp: float = field(default_factory=time.time)
    timestamp_iso: str = ""
    compliance_status: str = "COMPLIANT"

    def __post_init__(self) -> None:
        """Zaman damgası ve risk seviyesi doğrulamasını gerçekleştirir."""
        if not self.timestamp_iso:
            self.timestamp_iso = datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat()
        if self.risk_level.upper() not in VALID_RISK_LEVELS:
            self.risk_level = DEFAULT_RISK_LEVEL

    def to_dict(self) -> dict[str, Any]:
        """Bildirimi sözlük (dict) formatına dönüştürür."""
        return asdict(self)

    def __repr__(self) -> str:
        """Açıklayıcı nesne temsilini döndürür."""
        return (
            f"AlgoNotification(id={self.notification_id!r}, "
            f"strategy={self.strategy_name!r}, "
            f"risk={self.risk_level!r}, "
            f"status={self.compliance_status!r})"
        )


class AlgoNotificationStore:
    """DuckDB tabanlı, thread-safe algoritmik bildirim saklayıcı ve denetim motoru."""

    _instance: AlgoNotificationStore | None = None
    _init_lock = threading.Lock()

    def __init__(self, db_path: str = ":memory:") -> None:
        """Bildirim deposunu başlatır ve DuckDB şemasını hazırlar.

        Args:
            db_path: DuckDB veritabanı dosya yolu veya ':memory:'.
        """
        self._db_path = db_path
        self._lock = threading.RLock()
        self._is_closed = False
        self._conn = duckdb.connect(database=self._db_path)
        self._setup_schema()

    def _setup_schema(self) -> None:
        """Veritabanı tablosunu ve indekslerini oluşturur."""
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spk_algo_notifications (
                    notification_id VARCHAR PRIMARY KEY,
                    strategy_name VARCHAR NOT NULL,
                    strategy_type VARCHAR NOT NULL,
                    risk_level VARCHAR NOT NULL,
                    market VARCHAR NOT NULL,
                    description VARCHAR,
                    parameters_json VARCHAR,
                    kill_switch_enabled BOOLEAN,
                    operator VARCHAR,
                    compliance_status VARCHAR,
                    timestamp DOUBLE NOT NULL,
                    timestamp_iso VARCHAR NOT NULL
                );
                """
            )

    def save(self, notification: dict[str, Any] | AlgoNotification) -> None:
        """Bildirimi DuckDB tablosuna thread-safe olarak kaydeder.

        Args:
            notification: Kaydedilecek bildirim nesnesi veya sözlüğü.

        Raises:
            RuntimeError: Veritabanı bağlantısı kapalıysa.
        """
        with self._lock:
            if self._is_closed:
                raise RuntimeError("AlgoNotificationStore veritabanı bağlantısı kapalı.")

            data = notification.to_dict() if isinstance(notification, AlgoNotification) else notification
            params_json = orjson.dumps(data.get("parameters", {})).decode("utf-8")

            self._conn.execute(
                """
                INSERT OR REPLACE INTO spk_algo_notifications (
                    notification_id, strategy_name, strategy_type, risk_level,
                    market, description, parameters_json, kill_switch_enabled,
                    operator, compliance_status, timestamp, timestamp_iso
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                [
                    str(data.get("notification_id")),
                    str(data.get("strategy_name", DEFAULT_STRATEGY_NAME)),
                    str(data.get("strategy_type", DEFAULT_STRATEGY_TYPE)),
                    str(data.get("risk_level", DEFAULT_RISK_LEVEL)),
                    str(data.get("market", DEFAULT_MARKET)),
                    str(data.get("description", "")),
                    params_json,
                    bool(data.get("kill_switch_enabled", True)),
                    str(data.get("operator", DEFAULT_OPERATOR)),
                    str(data.get("compliance_status", "COMPLIANT")),
                    float(data.get("timestamp", time.time())),
                    str(data.get("timestamp_iso", "")),
                ],
            )

    def get_notification_by_id(self, notification_id: str) -> dict[str, Any] | None:
        """Belirtilen bildirim kimliğine sahip kaydı döndürür.

        Args:
            notification_id: SPK bildirim ID'si.

        Returns:
            dict[str, Any] | None: Bildirim kaydı veya bulunamazsa None.

        Raises:
            RuntimeError: Veritabanı bağlantısı kapalıysa.
        """
        with self._lock:
            if self._is_closed:
                raise RuntimeError("AlgoNotificationStore veritabanı bağlantısı kapalı.")

            cursor = self._conn.execute(
                """
                SELECT notification_id, strategy_name, strategy_type, risk_level,
                       market, description, parameters_json, kill_switch_enabled,
                       operator, compliance_status, timestamp, timestamp_iso
                FROM spk_algo_notifications
                WHERE notification_id = ?
                LIMIT 1;
                """,
                [str(notification_id)],
            )
            rows = cursor.fetchall()
            if not rows:
                return None
            cols = [desc[0] for desc in cursor.description]
            row = dict(zip(cols, rows[0], strict=False))
            params_raw = row.pop("parameters_json", None)
            if params_raw and isinstance(params_raw, str):
                try:
                    row["parameters"] = orjson.loads(params_raw)
                except Exception:
                    row["parameters"] = {}
            else:
                row["parameters"] = {}
            return row

    def list_notifications(
        self,
        strategy_name: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Kayıtlı bildirimleri filtreleyerek listeler.

        Args:
            strategy_name: Filtrelenecek strateji adı (opsiyonel).
            risk_level: Filtrelenecek risk seviyesi (opsiyonel).
            limit: Döndürülecek maksimum kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Bildirim kayıtlarının listesi.

        Raises:
            RuntimeError: Store bağlantısı kapalıysa.
        """
        with self._lock:
            if self._is_closed:
                raise RuntimeError("AlgoNotificationStore veritabanı bağlantısı kapalı.")

            query = """
                SELECT notification_id, strategy_name, strategy_type, risk_level,
                       market, description, parameters_json, kill_switch_enabled,
                       operator, compliance_status, timestamp, timestamp_iso
                FROM spk_algo_notifications
            """
            conditions: list[str] = []
            params: list[Any] = []

            if strategy_name:
                conditions.append("strategy_name = ?")
                params.append(str(strategy_name))
            if risk_level:
                conditions.append("risk_level = ?")
                params.append(str(risk_level).upper())

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY timestamp DESC LIMIT ?;"
            params.append(int(limit))

            cursor = self._conn.execute(query, params)
            cols = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

        results: list[dict[str, Any]] = []
        for r in rows:
            row = dict(zip(cols, r, strict=False))
            params_raw = row.pop("parameters_json", None)
            if params_raw and isinstance(params_raw, str):
                try:
                    row["parameters"] = orjson.loads(params_raw)
                except Exception:
                    row["parameters"] = {}
            else:
                row["parameters"] = {}
            results.append(row)
        return results

    def export_audit_log_to_polars(self, limit: int = 1000) -> pl.DataFrame:
        """Denetim izi bildirimlerini doğrudan yerel Polars DataFrame olarak dışa aktarır.

        Args:
            limit: Maksimum satır sayısı.

        Returns:
            pl.DataFrame: Polars DataFrame nesnesi.

        Raises:
            RuntimeError: Store bağlantısı kapalıysa.
        """
        with self._lock:
            if self._is_closed:
                raise RuntimeError("AlgoNotificationStore veritabanı bağlantısı kapalı.")
            return self._conn.execute(
                """
                SELECT notification_id, strategy_name, strategy_type, risk_level,
                       market, description, parameters_json, kill_switch_enabled,
                       operator, compliance_status, timestamp, timestamp_iso
                FROM spk_algo_notifications
                ORDER BY timestamp DESC
                LIMIT ?;
                """,
                [int(limit)],
            ).pl()

    def clear(self) -> None:
        """Test amaçlı tüm kayıtları siler.

        Raises:
            RuntimeError: Veritabanı bağlantısı kapalıysa.
        """
        with self._lock:
            if self._is_closed:
                raise RuntimeError("AlgoNotificationStore veritabanı bağlantısı kapalı.")
            self._conn.execute("DELETE FROM spk_algo_notifications;")

    def close(self) -> None:
        """DuckDB veritabanı bağlantısını güvenli biçimde kapatır."""
        with self._lock:
            if not self._is_closed:
                try:
                    self._conn.close()
                except Exception as exc:
                    logger.warning("algo_notification_store_kapatma_hatasi", hata=str(exc))
                finally:
                    self._is_closed = True

    def __enter__(self) -> AlgoNotificationStore:
        """Context manager giriş metodu."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager çıkışında veritabanı bağlantısını otomatik kapatır."""
        self.close()

    def __repr__(self) -> str:
        """Açıklayıcı nesne temsilini döndürür."""
        status = "kapali" if self._is_closed else "acik"
        return f"AlgoNotificationStore(db_path={self._db_path!r}, durum={status!r})"



_default_store: AlgoNotificationStore | None = None
_store_lock = threading.Lock()


def get_default_store() -> AlgoNotificationStore:
    """Tekil (singleton) bildirim deposunu döndürür."""
    global _default_store
    if _default_store is None:
        with _store_lock:
            if _default_store is None:
                _default_store = AlgoNotificationStore(db_path=":memory:")
    return _default_store


def generate_algo_notification(
    strategy: dict[str, Any] | None = None,
    persist: bool = False,
    store: AlgoNotificationStore | None = None,
) -> dict[str, Any]:
    """SPK mevzuatına uygun algoritmik işlem stratejisi bildirimi oluşturur.

    Args:
        strategy: Algoritma strateji parametreleri ve üst verileri.
            Beklenen anahtarlar: 'name', 'type', 'description', 'risk_level',
            'market', 'parameters', 'kill_switch_enabled', 'operator'.
        persist: Bildirimin kalıcı DuckDB deposuna kaydedilip kaydedilmeyeceği.
        store: Özel depo nesnesi (belirtilmezse varsayılan in-memory depo kullanılır).

    Returns:
        dict[str, Any]: SPK standartlarında benzersiz bildirim kaydı.

    Raises:
        ValueError: Strateji parametresi geçersiz bir tipte verildiğinde.
    """
    if strategy is None:
        strategy = {}
    elif not isinstance(strategy, dict):
        raise ValueError(
            f"Strateji parametresi bir sözlük (dict) olmalıdır, alınan tip: {type(strategy).__name__}"
        )

    with tracer.start_as_current_span("algo_notification.generate") as span:
        strategy_name = str(strategy.get("name") or DEFAULT_STRATEGY_NAME).strip()
        strategy_type = str(strategy.get("type") or DEFAULT_STRATEGY_TYPE).strip()

        raw_risk = str(strategy.get("risk_level") or DEFAULT_RISK_LEVEL).upper()
        if raw_risk not in VALID_RISK_LEVELS:
            logger.warning(
                "gecersiz_risk_seviyesi_varsayilana_cekildi",
                girilen_risk=raw_risk,
                varsayilan_risk=DEFAULT_RISK_LEVEL,
                strateji=strategy_name,
            )
            risk_level = DEFAULT_RISK_LEVEL
        else:
            risk_level = raw_risk

        market = str(strategy.get("market") or DEFAULT_MARKET).strip()
        description = str(strategy.get("description") or "BIST otomatik algoritma stratejisi").strip()
        parameters = strategy.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}

        kill_switch = bool(strategy.get("kill_switch_enabled", True))
        operator = str(strategy.get("operator") or DEFAULT_OPERATOR).strip()

        span.set_attribute("strategy.name", strategy_name)
        span.set_attribute("strategy.type", strategy_type)
        span.set_attribute("strategy.risk_level", risk_level)
        span.set_attribute("strategy.market", market)

        now = time.time()
        notification_id = f"spk_algo_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.fromtimestamp(now, tz=UTC).isoformat()

        notification_obj = AlgoNotification(
            notification_id=notification_id,
            notification_type="ALGO_TRADING",
            strategy_name=strategy_name,
            strategy_type=strategy_type,
            description=description,
            risk_level=risk_level,
            market=market,
            parameters=parameters,
            kill_switch_enabled=kill_switch,
            operator=operator,
            auto_generated=True,
            timestamp=now,
            timestamp_iso=now_iso,
            compliance_status="COMPLIANT",
        )

        notification_dict = notification_obj.to_dict()

        if persist:
            target_store = store or get_default_store()
            target_store.save(notification_dict)

        logger.info(
            "spk_algoritma_bildirimi_olusturuldu",
            notification_id=notification_id,
            strategy_name=strategy_name,
            strategy_type=strategy_type,
            risk_level=risk_level,
            market=market,
            persist=persist,
        )
        return notification_dict


def reset_default_store() -> None:
    """Varsayılan global bildirim deposunu kapatır ve sıfırlar."""
    global _default_store
    with _store_lock:
        if _default_store is not None:
            _default_store.close()
            _default_store = None


__all__ = [
    "DEFAULT_MARKET",
    "DEFAULT_OPERATOR",
    "DEFAULT_RISK_LEVEL",
    "DEFAULT_STRATEGY_NAME",
    "DEFAULT_STRATEGY_TYPE",
    "VALID_RISK_LEVELS",
    "AlgoNotification",
    "AlgoNotificationStore",
    "generate_algo_notification",
    "get_default_store",
    "reset_default_store",
]


