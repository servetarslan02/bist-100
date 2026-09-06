"""ALPHA BIST — Broker Soyutlama ve Paper Broker Simülasyon Altyapısı v1.0

Bu modül, Borsa İstanbul (BIST) işlem emirleri için aracı kurumdan bağımsız
(broker-agnostic) tip güvenli emir iletimi, iptali, durum sorgulama ve portföy/pozisyon
yönetimi arayüzünü sağlar.

Özellikler:
- `BrokerInterface`: Kurumsal aracı kurum API'leri için standart soyut arayüz.
- `PaperBroker`: Kayma (slippage) payı, ortalama maliyet hesabı, idempotency ve bakiye
  denetimleri içeren thread-safe emir ve portföy simülatörü.
- Polars & DuckDB Entegrasyonu: Emir geçmişi ve açık pozisyonların yüksek hızlı OLAP
  analitiği ve kalıcı depolanması.
- OpenTelemetry Entegrasyonu: Dağıtık izleme ve span desteği.
"""

import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# --- Varsayılan Yapılandırma Sabitleri ---
DEFAULT_INITIAL_CAPITAL: float = 1_000_000.0
DEFAULT_SLIPPAGE_BPS: float = 5.0  # 5 baz puan = %0.05
DEFAULT_PRICE_DECIMALS: int = 4
DEFAULT_DUCKDB_PATH: Path = Path("data/broker.duckdb")


class OrderSide(StrEnum):
    """Emir yönü (Alış / Satış) enum tanımı."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    """Emir işlem durumları enum tanımı."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(slots=True)
class Position:
    """Tekil hisse senedi pozisyon veri modeli.

    Attributes:
        ticker: Hisse senedi sembolü.
        quantity: Sahip olunan hisse adedi (lot).
        avg_cost: Ortalama alış maliyeti.
        updated_at: Son güncelleme zaman damgası.
    """

    ticker: str
    quantity: int
    avg_cost: float
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Pozisyon modelini sözlük yapısına dönüştürür."""
        return {
            "ticker": self.ticker,
            "quantity": self.quantity,
            "avg_cost": round(self.avg_cost, DEFAULT_PRICE_DECIMALS),
            "updated_at": self.updated_at,
        }

    def to_orjson_bytes(self) -> bytes:
        """Pozisyon modelini orjson ile ikili bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def to_json(self) -> str:
        """Pozisyon modelini JSON dizgisine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Position":
        """Sözlük verisinden Position nesnesi üretir."""
        return cls(
            ticker=str(data.get("ticker", "")).strip().upper(),
            quantity=int(data.get("quantity", 0)),
            avg_cost=float(data.get("avg_cost", 0.0)),
            updated_at=float(data.get("updated_at", time.time())),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> "Position":
        """JSON verisinden Position nesnesi oluşturur."""
        return cls.from_dict(orjson.loads(json_str_or_bytes))

    def __repr__(self) -> str:
        """Açıklayıcı Türkçe metin gösterimi."""
        return (
            f"<Position ticker='{self.ticker}' adet={self.quantity} "
            f"maliyet={self.avg_cost:.4f}>"
        )


@dataclass(slots=True)
class Order:
    """BIST alım/satım emri veri modeli.

    Attributes:
        order_id: Benzersiz emir tanımlayıcı kimliği.
        ticker: Hisse kodu (örn. 'THYAO', 'GARAN').
        side: Emir yönü (BUY veya SELL).
        quantity: Lot cinsi emir büyüklüğü.
        price: Birim emir fiyatı.
        status: Emir gerçekleşme durumu.
        filled_quantity: Gerçekleşen lot miktarı.
        avg_fill_price: Gerçekleşen ortalama fiyat.
        reject_reason: Varsa ret sebebi açıklaması.
        created_at: Emrin oluşturulma zaman damgası.
        idempotency_key: Mükerrer emir engelleme anahtarı.
    """

    order_id: str
    ticker: str
    side: OrderSide | str
    quantity: int
    price: float
    status: OrderStatus | str = OrderStatus.PENDING.value
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    reject_reason: str = ""
    created_at: float = field(default_factory=time.time)
    idempotency_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Emir modelini sözlük yapısına dönüştürür."""
        side_val = self.side.value if isinstance(self.side, OrderSide) else str(self.side)
        status_val = self.status.value if isinstance(self.status, OrderStatus) else str(self.status)
        return {
            "order_id": self.order_id,
            "ticker": self.ticker,
            "side": side_val,
            "quantity": self.quantity,
            "price": self.price,
            "status": status_val,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "reject_reason": self.reject_reason,
            "created_at": self.created_at,
            "idempotency_key": self.idempotency_key,
        }

    def to_orjson_bytes(self) -> bytes:
        """Emir modelini orjson ile ikili bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def to_json(self) -> str:
        """Emir modelini JSON dizgisine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Order":
        """Sözlük verisinden Order nesnesi üretir."""
        side_raw = str(data.get("side", OrderSide.BUY.value)).upper()
        status_raw = str(data.get("status", OrderStatus.PENDING.value)).upper()
        return cls(
            order_id=str(data.get("order_id", "")),
            ticker=str(data.get("ticker", "")).strip().upper(),
            side=OrderSide(side_raw) if side_raw in OrderSide._value2member_map_ else side_raw,
            quantity=int(data.get("quantity", 0)),
            price=float(data.get("price", 0.0)),
            status=OrderStatus(status_raw) if status_raw in OrderStatus._value2member_map_ else status_raw,
            filled_quantity=int(data.get("filled_quantity", 0)),
            avg_fill_price=float(data.get("avg_fill_price", 0.0)),
            reject_reason=str(data.get("reject_reason", "")),
            created_at=float(data.get("created_at", time.time())),
            idempotency_key=str(data.get("idempotency_key", "")),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> "Order":
        """JSON verisinden Order nesnesi oluşturur."""
        return cls.from_dict(orjson.loads(json_str_or_bytes))

    def __repr__(self) -> str:
        """Açıklayıcı Türkçe metin gösterimi."""
        return (
            f"<Order id='{self.order_id}' ticker='{self.ticker}' yon={self.side} "
            f"adet={self.quantity} fiyat={self.price:.2f} durum={self.status}>"
        )


class BrokerInterface:
    """Aracı kurum bağlantıları için temel soyut arayüz."""

    def submit_order(self, order: Order) -> Order:
        """Yeni bir alım/satım emrini aracı kuruma iletir.

        Args:
            order: İletilecek emir nesnesi.

        Returns:
            Güncellenmiş emir nesnesi.

        Raises:
            NotImplementedError: Alt sınıflar tarafından uygulanmalıdır.
        """
        logger.warning("submit_order alt sınıfta henüz uygulanmadı")
        raise NotImplementedError("submit_order metodu alt sınıfta uygulanmalıdır.")

    def cancel_order(self, order_id: str) -> bool:
        """Aktif bir emri iptal eder.

        Args:
            order_id: İptal edilecek emir kimliği.

        Returns:
            İptal başarılıysa True, aksi halde False.

        Raises:
            NotImplementedError: Alt sınıflar tarafından uygulanmalıdır.
        """
        logger.warning("cancel_order alt sınıfta henüz uygulanmadı")
        raise NotImplementedError("cancel_order metodu alt sınıfta uygulanmalıdır.")

    def get_order_status(self, order_id: str) -> Order | None:
        """Emrin güncel durumunu sorgular.

        Args:
            order_id: Sorgulanacak emir kimliği.

        Returns:
            Emir bulunduysa Order nesnesi, bulunamadıysa None.

        Raises:
            NotImplementedError: Alt sınıflar tarafından uygulanmalıdır.
        """
        logger.warning("get_order_status alt sınıfta henüz uygulanmadı")
        raise NotImplementedError("get_order_status metodu alt sınıfta uygulanmalıdır.")

    def get_positions(self) -> dict[str, dict[str, Any]]:
        """Mevcut portföydeki açık hisse pozisyonlarını döndürür.

        Returns:
            Hisse bazında miktar ve maliyet sözlüğü.

        Raises:
            NotImplementedError: Alt sınıflar tarafından uygulanmalıdır.
        """
        logger.warning("get_positions alt sınıfta henüz uygulanmadı")
        raise NotImplementedError("get_positions metodu alt sınıfta uygulanmalıdır.")

    def get_capital(self) -> float:
        """Kullanılabilir nakit bakiyeyi döndürür.

        Returns:
            Nakit bakiye tutarı.

        Raises:
            NotImplementedError: Alt sınıflar tarafından uygulanmalıdır.
        """
        logger.warning("get_capital alt sınıfta henüz uygulanmadı")
        raise NotImplementedError("get_capital metodu alt sınıfta uygulanmalıdır.")

    def is_connected(self) -> bool:
        """Aracı kurum bağlantı durumunu bildirir.

        Returns:
            Bağlantı aktifse True, aksi halde False.

        Raises:
            NotImplementedError: Alt sınıflar tarafından uygulanmalıdır.
        """
        logger.warning("is_connected alt sınıfta henüz uygulanmadı")
        raise NotImplementedError("is_connected metodu alt sınıfta uygulanmalıdır.")


class PaperBroker(BrokerInterface):
    """BIST Paper Broker — Gerçek emir göndermeyen simülatör.

    Özellikler:
    - Slippage simülasyonu (alışta yukarı, satışta aşağı kayma).
    - Idempotency denetimi ile mükerrer emir bloklama.
    - Ortalama alış maliyeti (FIFO/ağırlıklı maliyet) hesabı.
    - Nakit bakiye ve pozisyon yeterlilik kontrolleri.
    - Thread-safe durum yönetimi (`threading.RLock`).
    - Polars ve DuckDB analitik dışa aktarımı.
    """

    def __init__(
        self,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    ) -> None:
        """Paper Broker simülatörünü başlatır.

        Args:
            initial_capital: Başlangıç nakit sermayesi (TL).
            slippage_bps: Kayma oranı (baz puan, 5 bps = %0.05).
        """
        self._lock = threading.RLock()
        self._initial_capital = float(initial_capital)
        self._capital: float = float(initial_capital)
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._idempotency_keys: dict[str, str] = {}
        self._slippage_bps: float = float(slippage_bps)

    @otel_trace("broker.submit_order")
    def submit_order(self, order: Order) -> Order:
        """Emri doğrular, kayma uygular ve portföye/bakiyeye yansıtır.

        Args:
            order: İletilmek istenen emir nesnesi.

        Returns:
            Durumu güncellenmiş (FILLED veya REJECTED) emir nesnesi.
        """
        with self._lock:
            # 1. Idempotency Kontrolü
            if order.idempotency_key:
                existing_id = self._idempotency_keys.get(order.idempotency_key)
                if existing_id and existing_id in self._orders:
                    existing = self._orders[existing_id]
                    if existing.status in (OrderStatus.SUBMITTED, OrderStatus.FILLED):
                        logger.info(
                            "Mükerrer emir engellendi (idempotency)",
                            idempotency_key=order.idempotency_key,
                            order_id=existing_id,
                        )
                        return existing

            # 2. Temel Giriş Validasyonları
            clean_ticker = order.ticker.strip().upper() if order.ticker else ""
            if not clean_ticker:
                order.status = OrderStatus.REJECTED
                order.reject_reason = "Geçersiz hisse kodu: ticker boş olamaz."
                self._record_order(order)
                return order

            if order.quantity <= 0:
                order.status = OrderStatus.REJECTED
                order.reject_reason = f"Geçersiz emir miktarı: {order.quantity}. Pozitif tamsayı olmalıdır."
                self._record_order(order)
                return order

            if (
                not isinstance(order.price, (int, float))
                or math.isnan(order.price)
                or math.isinf(order.price)
                or order.price <= 0
            ):
                order.status = OrderStatus.REJECTED
                order.reject_reason = f"Geçersiz emir fiyatı: {order.price}. Pozitif sayı olmalıdır."
                self._record_order(order)
                return order

            side_norm = (
                order.side.value if isinstance(order.side, OrderSide) else str(order.side).strip().upper()
            )
            if side_norm not in (OrderSide.BUY.value, OrderSide.SELL.value):
                order.status = OrderStatus.REJECTED
                order.reject_reason = f"Geçersiz emir yönü: {order.side}. BUY veya SELL olmalıdır."
                self._record_order(order)
                return order

            order.ticker = clean_ticker
            order.side = OrderSide(side_norm)
            order.order_id = order.order_id or str(uuid.uuid4())[:12]
            order.status = OrderStatus.SUBMITTED

            # 3. Kayma (Slippage) Hesabı
            slippage_mult = (
                1.0 + (self._slippage_bps / 10_000.0)
                if order.side == OrderSide.BUY
                else 1.0 - (self._slippage_bps / 10_000.0)
            )
            fill_price = round(order.price * slippage_mult, DEFAULT_PRICE_DECIMALS)

            # 4. Alış / Satış Yürütme Mantığı
            if order.side == OrderSide.BUY:
                cost = order.quantity * fill_price
                if cost > self._capital:
                    order.status = OrderStatus.REJECTED
                    order.reject_reason = (
                        f"Yetersiz bakiye: Gereken {cost:.2f} TL, Mevcut {self._capital:.2f} TL."
                    )
                else:
                    self._capital -= cost
                    order.status = OrderStatus.FILLED
                    order.filled_quantity = order.quantity
                    order.avg_fill_price = fill_price

                    pos = self._positions.get(order.ticker)
                    if pos is None:
                        self._positions[order.ticker] = Position(
                            ticker=order.ticker,
                            quantity=order.quantity,
                            avg_cost=fill_price,
                        )
                    else:
                        total_qty = pos.quantity + order.quantity
                        if total_qty > 0:
                            pos.avg_cost = (
                                (pos.quantity * pos.avg_cost) + cost
                            ) / total_qty
                        pos.quantity = total_qty
                        pos.updated_at = time.time()

            elif order.side == OrderSide.SELL:
                pos = self._positions.get(order.ticker)
                if not pos or pos.quantity < order.quantity:
                    order.status = OrderStatus.REJECTED
                    cur_qty = pos.quantity if pos else 0
                    order.reject_reason = (
                        f"Yetersiz hisse pozisyonu: Satılmak istenen {order.quantity}, "
                        f"Mevcut {cur_qty}."
                    )
                else:
                    revenue = order.quantity * fill_price
                    self._capital += revenue
                    pos.quantity -= order.quantity
                    pos.updated_at = time.time()

                    order.status = OrderStatus.FILLED
                    order.filled_quantity = order.quantity
                    order.avg_fill_price = fill_price  # Düzeltildi: order.price ile ezilmez!

                    if pos.quantity == 0:
                        pos.avg_cost = 0.0

            self._record_order(order)
            logger.info(
                "Paper emir işlendi",
                order_id=order.order_id,
                status=str(order.status),
                ticker=order.ticker,
                side=str(order.side),
                qty=order.quantity,
                fill_price=order.avg_fill_price,
                kalan_bakiye=self._capital,
            )
            return order

    def _record_order(self, order: Order) -> None:
        """Emri iç dizinlere kaydeder."""
        self._orders[order.order_id] = order
        if order.idempotency_key:
            self._idempotency_keys[order.idempotency_key] = order.order_id

    @otel_trace("broker.cancel_order")
    def cancel_order(self, order_id: str) -> bool:
        """Bekleyen veya iletilen emri iptal eder.

        Args:
            order_id: İptal edilecek emir kimliği.

        Returns:
            İptal edildiyse True, edilemediyse False.
        """
        with self._lock:
            order = self._orders.get(order_id)
            if order and order.status in (OrderStatus.SUBMITTED, OrderStatus.PENDING):
                order.status = OrderStatus.CANCELLED
                logger.info("Emir iptal edildi", order_id=order_id)
                return True
            return False

    @otel_trace("broker.get_order_status")
    def get_order_status(self, order_id: str) -> Order | None:
        """Kayıtlı emrin durumunu döndürür.

        Args:
            order_id: Emir kimliği.

        Returns:
            Order nesnesi veya None.
        """
        with self._lock:
            return self._orders.get(order_id)

    @otel_trace("broker.get_positions")
    def get_positions(self) -> dict[str, dict[str, Any]]:
        """Mevcut hisse pozisyonlarını sözlük olarak döndürür."""
        with self._lock:
            return {ticker: pos.to_dict() for ticker, pos in self._positions.items() if pos.quantity > 0}

    def get_position_models(self) -> dict[str, Position]:
        """Mevcut hisse pozisyonlarını tip güvenli Position modelleri olarak döndürür."""
        with self._lock:
            return {ticker: pos for ticker, pos in self._positions.items() if pos.quantity > 0}

    def get_capital(self) -> float:
        """Mevcut nakit bakiyeyi döndürür."""
        with self._lock:
            return self._capital

    def is_connected(self) -> bool:
        """Paper broker her zaman hazırdır."""
        return True

    def reset(self, initial_capital: float | None = None) -> None:
        """Broker durumunu, pozisyonlarını ve emir geçmişini sıfırlar.

        Args:
            initial_capital: İsteğe bağlı yeni başlangıç sermayesi.
        """
        with self._lock:
            cap = self._initial_capital if initial_capital is None else float(initial_capital)
            self._capital = cap
            self._positions.clear()
            self._orders.clear()
            self._idempotency_keys.clear()
            logger.info("Paper broker durumu sıfırlandı", baslangic_sermayesi=self._capital)

    def export_orders_to_polars(self) -> pl.DataFrame:
        """Tüm emir geçmişini Polars DataFrame olarak dışa aktarır.

        Returns:
            Polars DataFrame.
        """
        with self._lock:
            schema = {
                "order_id": pl.Utf8,
                "ticker": pl.Utf8,
                "side": pl.Utf8,
                "quantity": pl.Int64,
                "price": pl.Float64,
                "status": pl.Utf8,
                "filled_quantity": pl.Int64,
                "avg_fill_price": pl.Float64,
                "reject_reason": pl.Utf8,
                "created_at": pl.Float64,
                "idempotency_key": pl.Utf8,
            }
            if not self._orders:
                return pl.DataFrame(schema=schema)

            records = [order.to_dict() for order in self._orders.values()]
            return pl.DataFrame(records, schema=schema)

    def export_positions_to_polars(self) -> pl.DataFrame:
        """Tüm açık pozisyonları Polars DataFrame olarak dışa aktarır.

        Returns:
            Polars DataFrame.
        """
        with self._lock:
            schema = {
                "ticker": pl.Utf8,
                "quantity": pl.Int64,
                "avg_cost": pl.Float64,
                "updated_at": pl.Float64,
            }
            active_positions = [pos.to_dict() for pos in self._positions.values() if pos.quantity > 0]
            if not active_positions:
                return pl.DataFrame(schema=schema)

            return pl.DataFrame(active_positions, schema=schema)

    def export_orders_to_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_paper_orders",
    ) -> int:
        """Emir geçmişini DuckDB tablosuna kaydeder.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            table_name: Hedef tablo adı.

        Returns:
            Yazılan emir sayısı.
        """
        with self._lock:
            df = self.export_orders_to_polars()
            if len(df) == 0:
                return 0

            target_path = Path(db_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            if target_path.exists() and target_path.stat().st_size == 0:
                target_path.unlink()

            conn = duckdb.connect(str(target_path))
            try:
                conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df WHERE 1=0;")
                conn.register("df_orders", df)
                conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_orders;")
                return len(df)
            finally:
                conn.close()

    def query_orders_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_paper_orders",
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB'den emir geçmişini Polars DataFrame olarak sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.
            limit: Maksimum satır sayısı.

        Returns:
            Polars DataFrame.
        """
        target_path = Path(db_path)
        schema = {
            "order_id": pl.Utf8,
            "ticker": pl.Utf8,
            "side": pl.Utf8,
            "quantity": pl.Int64,
            "price": pl.Float64,
            "status": pl.Utf8,
            "filled_quantity": pl.Int64,
            "avg_fill_price": pl.Float64,
            "reject_reason": pl.Utf8,
            "created_at": pl.Float64,
            "idempotency_key": pl.Utf8,
        }

        if not target_path.exists():
            return pl.DataFrame(schema=schema)

        if target_path.stat().st_size == 0:
            target_path.unlink()
            return pl.DataFrame(schema=schema)

        conn = duckdb.connect(str(target_path), read_only=True)
        try:
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                [table_name],
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(schema=schema)

            arrow_table = conn.execute(
                f"SELECT * FROM {table_name} ORDER BY created_at DESC LIMIT {int(limit)}"
            ).fetch_arrow_table()
            return pl.from_arrow(arrow_table)
        finally:
            conn.close()

    def __repr__(self) -> str:
        """Açıklayıcı Türkçe metin gösterimi."""
        with self._lock:
            active_pos_count = sum(1 for p in self._positions.values() if p.quantity > 0)
            return (
                f"<PaperBroker bakiye={self._capital:.2f} TL "
                f"aktif_pozisyon={active_pos_count} toplam_emir={len(self._orders)} "
                f"kayma_bps={self._slippage_bps}>"
            )


# Singleton Örnek
paper_broker = PaperBroker()


# --- Modül Seviyesinde Kolaylık Fonksiyonları ---

def submit_order(order: Order) -> Order:
    """Singleton broker üzerinden emir iletir."""
    return paper_broker.submit_order(order)


def cancel_order(order_id: str) -> bool:
    """Singleton broker üzerinden emir iptal eder."""
    return paper_broker.cancel_order(order_id)


def get_order_status(order_id: str) -> Order | None:
    """Singleton broker üzerinden emir durumunu sorgular."""
    return paper_broker.get_order_status(order_id)


def get_positions() -> dict[str, dict[str, Any]]:
    """Singleton broker üzerinden mevcut pozisyonları döndürür."""
    return paper_broker.get_positions()


def get_capital() -> float:
    """Singleton broker üzerinden mevcut nakit bakiyeyi döndürür."""
    return paper_broker.get_capital()


def is_connected() -> bool:
    """Broker bağlantı durumunu bildirir."""
    return paper_broker.is_connected()


def reset_broker(initial_capital: float | None = None) -> None:
    """Broker simülasyon durumunu sıfırlar."""
    paper_broker.reset(initial_capital)


def export_orders_to_polars() -> pl.DataFrame:
    """Emir geçmişini Polars DataFrame olarak döndürür."""
    return paper_broker.export_orders_to_polars()


def export_positions_to_polars() -> pl.DataFrame:
    """Açık pozisyonları Polars DataFrame olarak döndürür."""
    return paper_broker.export_positions_to_polars()


def export_orders_to_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_paper_orders",
) -> int:
    """Emir geçmişini DuckDB tablosuna kaydeder."""
    return paper_broker.export_orders_to_duckdb(db_path, table_name)


def query_broker_orders_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_paper_orders",
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB'den emir kayıtlarını sorgular."""
    return paper_broker.query_orders_duckdb(db_path, table_name, limit)


def get_paper_broker() -> PaperBroker:
    """Singleton PaperBroker örneğini döndürür."""
    return paper_broker


__all__ = [
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_SLIPPAGE_BPS",
    "DEFAULT_PRICE_DECIMALS",
    "DEFAULT_DUCKDB_PATH",
    "OrderSide",
    "OrderStatus",
    "Position",
    "Order",
    "BrokerInterface",
    "PaperBroker",
    "paper_broker",
    "submit_order",
    "cancel_order",
    "get_order_status",
    "get_positions",
    "get_capital",
    "is_connected",
    "reset_broker",
    "export_orders_to_polars",
    "export_positions_to_polars",
    "export_orders_to_duckdb",
    "query_broker_orders_duckdb",
    "get_paper_broker",
]
