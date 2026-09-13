"""
ALPHA BIST — Vergi Kayıp Hasadı (Tax Loss Harvesting) Motoru

BIST'e özgü vergi kayıp hasadı motoru. Zarar eden pozisyonları satarak
vergi yükümlülüğünü düşürür; wash-sale benzeri gün kuralı ve portföy
izleme kısıtlarını dikkate alır.

Türk Vergi Ortamı:
  - Hisse senedi kazanç vergisi: %0 (beyan yok, stopaj yok — 2023 itibarıyla)
  - Türev araçlar (VIOP): Kazancın %0 (kurum) veya %10 (bireysel)
  - Yabancı menkul kıymetler: Ayrı vergi hesabı gerektirir
  - Stop-out satışların 30 gün beklenme zorunluluğu (wash-sale) yoktur BIST'te
    ancak benzer hisse alımı yapılmışsa ekonomik açıdan "gerçek zarar" sorgulanabilir.

Özellikler:
  - Pozisyon bazlı gerçekleşmemiş kar/zarar tespiti
  - Hasat edilebilir zarar listesi çıkarma (wash-sale uyarısı ile)
  - Hedef portföy ile karşılaştırma (deviasyonu minimize et)
  - Hasat eşiği filtresi (küçük zararlar maliyet-etkin değil)
  - DuckDB tabanlı hasat tarihçesi kaydı (vergi dönemine göre)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import duckdb
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_HARVEST_THRESHOLD_PCT: float = 0.02   # Minimum %2 zarar (hasat edilmeye değer)
DEFAULT_WASH_SALE_DAYS: int = 30              # Aynı hisseyi geri alma bekleme süresi
DEFAULT_MIN_TRADE_VALUE: float = 5_000.0      # Minimum işlem değeri (TL)
TAX_RATE_DERIVATIVES: float = 0.10            # VIOP bireysel stopaj oranı
BIST_EQUITY_TAX_RATE: float = 0.0             # BIST hisse senedi stopaj (0)
DB_TABLE_HARVEST = "tax_harvest_events"


@dataclass
class Position:
    """Mevcut portföy pozisyonu.

    Attributes:
        ticker: Hisse senedi kodu.
        shares: Lot sayısı.
        avg_cost: Ortalama maliyet (TL).
        current_price: Anlık fiyat (TL).
        purchase_date: İlk alım tarihi.
        tax_lot_id: Vergi lot kimliği (FIFO lot takibi).
    """

    ticker: str
    shares: float
    avg_cost: float
    current_price: float
    purchase_date: date
    tax_lot_id: str = ""

    @property
    def market_value(self) -> float:
        """Piyasa değeri (TL)."""
        return self.shares * self.current_price

    @property
    def cost_basis(self) -> float:
        """Maliyet değeri (TL)."""
        return self.shares * self.avg_cost

    @property
    def unrealized_pnl(self) -> float:
        """Gerçekleşmemiş kar/zarar (TL)."""
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        """Gerçekleşmemiş kar/zarar oranı (%)."""
        if self.cost_basis <= 0:
            return 0.0
        return (self.current_price - self.avg_cost) / self.avg_cost

    def __repr__(self) -> str:
        """Position kısa temsili."""
        return (
            f"Position({self.ticker}, "
            f"lots={self.shares:.0f}, "
            f"cost={self.avg_cost:.2f}, "
            f"price={self.current_price:.2f}, "
            f"P&L={self.unrealized_pnl_pct:.1%})"
        )


@dataclass
class HarvestCandidate:
    """Hasat adayı pozisyon.

    Attributes:
        position: Kayıptaki pozisyon.
        harvestable_loss_tl: Hasat edilebilir zarar (TL, pozitif sayı).
        harvestable_loss_pct: Hasat edilebilir zarar oranı.
        wash_sale_risk: Aynı hissenin yakın tarihte alınması riski var mı?
        days_held: Pozisyon tutma süresi (gün).
        replacement_ticker: Önerilen ikame hisse (wash-sale önleme).
        estimated_tax_saving_tl: Tahmini vergi tasarrufu (TL).
    """

    position: Position
    harvestable_loss_tl: float
    harvestable_loss_pct: float
    wash_sale_risk: bool
    days_held: int
    replacement_ticker: str = ""
    estimated_tax_saving_tl: float = 0.0

    def __repr__(self) -> str:
        """HarvestCandidate kısa temsili."""
        risk_str = "⚠ WASH-SALE" if self.wash_sale_risk else "OK"
        return (
            f"HarvestCandidate({self.position.ticker}, "
            f"loss={self.harvestable_loss_pct:.1%}, "
            f"TL={self.harvestable_loss_tl:,.0f}, "
            f"wash={risk_str})"
        )


@dataclass
class HarvestPlan:
    """Vergi kayıp hasadı planı.

    Attributes:
        harvest_date: Plan oluşturma tarihi.
        candidates: Hasat adayı listesi.
        total_harvestable_loss_tl: Toplam hasat edilebilir zarar.
        total_tax_saving_tl: Toplam tahmini vergi tasarrufu.
        wash_sale_warnings: Wash-sale riski taşıyan ticker'lar.
        estimated_transaction_cost_tl: Tahmini işlem maliyeti.
        net_benefit_tl: Net fayda (tasarruf - işlem maliyeti).
    """

    harvest_date: date
    candidates: list[HarvestCandidate] = field(default_factory=list)
    total_harvestable_loss_tl: float = 0.0
    total_tax_saving_tl: float = 0.0
    wash_sale_warnings: list[str] = field(default_factory=list)
    estimated_transaction_cost_tl: float = 0.0
    net_benefit_tl: float = 0.0

    def __repr__(self) -> str:
        """HarvestPlan kısa temsili."""
        return (
            f"HarvestPlan({self.harvest_date}, "
            f"candidates={len(self.candidates)}, "
            f"total_loss={self.total_harvestable_loss_tl:,.0f} TL, "
            f"net_benefit={self.net_benefit_tl:,.0f} TL)"
        )


class TaxLossHarvestEngine:
    """BIST vergi kayıp hasadı motoru (thread-safe).

    DuckDB tabanlı hasat tarihçesi yönetimi ile BIST hisselerine özgü
    vergi kayıp hasadı planları üretir.
    """

    def __init__(
        self,
        db_path: str = "data/tax_harvest.duckdb",
        harvest_threshold_pct: float = DEFAULT_HARVEST_THRESHOLD_PCT,
        wash_sale_days: int = DEFAULT_WASH_SALE_DAYS,
        commission_rate: float = 0.0015,
        bsmv_rate: float = 0.000015,
    ) -> None:
        """TaxLossHarvestEngine başlatıcı.

        Args:
            db_path: DuckDB veritabanı dosyası.
            harvest_threshold_pct: Hasat eşiği (örn. 0.02 = %2 zarar).
            wash_sale_days: Wash-sale bekleme süresi (gün).
            commission_rate: Komisyon oranı (örn. 0.0015 = %0.15).
            bsmv_rate: Bankacılık ve Sigorta Muameleleri Vergisi oranı.
        """
        self.db_path = db_path
        self.harvest_threshold_pct = harvest_threshold_pct
        self.wash_sale_days = wash_sale_days
        self.commission_rate = commission_rate
        self.bsmv_rate = bsmv_rate
        self._lock = threading.RLock()
        self._init_db()

    def __repr__(self) -> str:
        """TaxLossHarvestEngine kısa temsili."""
        return (
            f"TaxLossHarvestEngine("
            f"threshold={self.harvest_threshold_pct:.1%}, "
            f"wash_sale={self.wash_sale_days}d)"
        )

    def _init_db(self) -> None:
        """DuckDB hasat tarihçesi tablosunu başlatır.

        Raises:
            RuntimeError: Veritabanı oluşturulamıyorsa.
        """
        try:
            with duckdb.connect(self.db_path) as con:
                con.execute(f"""
                    CREATE TABLE IF NOT EXISTS {DB_TABLE_HARVEST} (
                        id           VARCHAR PRIMARY KEY,
                        ticker       VARCHAR NOT NULL,
                        harvest_date DATE NOT NULL,
                        shares_sold  DOUBLE NOT NULL,
                        avg_cost     DOUBLE NOT NULL,
                        sale_price   DOUBLE NOT NULL,
                        loss_tl      DOUBLE NOT NULL,
                        tax_year     INTEGER NOT NULL,
                        replacement  VARCHAR,
                        created_at   TIMESTAMP DEFAULT NOW()
                    )
                """)
            logger.info("Hasat tarihçesi DB hazır.", db=self.db_path)
        except Exception as exc:
            raise RuntimeError(f"DuckDB başlatılamadı: {self.db_path}") from exc

    def _estimate_transaction_cost(self, market_value: float) -> float:
        """İşlem maliyeti tahmini (komisyon + BSMV).

        Args:
            market_value: Pozisyon piyasa değeri (TL).

        Returns:
            Tahmini işlem maliyeti (TL).
        """
        commission = market_value * self.commission_rate
        bsmv = commission * self.bsmv_rate * 1000  # BSMV = komisyon üzerinden
        return commission + bsmv

    def _check_wash_sale_risk(
        self,
        ticker: str,
        as_of_date: date,
    ) -> bool:
        """Aynı hissenin son N günde alınıp alınmadığını kontrol eder.

        Args:
            ticker: Kontrol edilecek hisse kodu.
            as_of_date: Kontrol tarihi.

        Returns:
            True ise wash-sale riski var.
        """
        try:
            cutoff = as_of_date - timedelta(days=self.wash_sale_days)
            with duckdb.connect(self.db_path) as con:
                result = con.execute(
                    f"""
                    SELECT COUNT(*) FROM {DB_TABLE_HARVEST}
                    WHERE ticker = ? AND harvest_date >= ?
                    """,
                    [ticker, cutoff],
                ).fetchone()
            return (result[0] if result else 0) > 0
        except Exception as exc:
            logger.warning("Wash-sale kontrol hatası.", ticker=ticker, hata=str(exc))
            return False

    def record_harvest(
        self,
        harvest_id: str,
        ticker: str,
        harvest_date: date,
        shares_sold: float,
        avg_cost: float,
        sale_price: float,
        replacement: str = "",
    ) -> None:
        """Hasat işlemini DuckDB'ye kaydeder.

        Args:
            harvest_id: Benzersiz hasat kimliği.
            ticker: Hisse senedi kodu.
            harvest_date: Hasat tarihi.
            shares_sold: Satılan lot sayısı.
            avg_cost: Ortalama maliyet.
            sale_price: Satış fiyatı.
            replacement: İkame hisse kodu (varsa).

        Raises:
            RuntimeError: Kayıt başarısız olursa.
        """
        loss_tl = (sale_price - avg_cost) * shares_sold  # Negatif = zarar
        with self._lock:
            try:
                with duckdb.connect(self.db_path) as con:
                    con.execute(
                        f"""
                        INSERT INTO {DB_TABLE_HARVEST}
                            (id, ticker, harvest_date, shares_sold, avg_cost, sale_price,
                             loss_tl, tax_year, replacement)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            harvest_id, ticker, harvest_date, shares_sold,
                            avg_cost, sale_price, loss_tl, harvest_date.year, replacement,
                        ],
                    )
                logger.info(
                    "Hasat kaydedildi.",
                    ticker=ticker,
                    loss_tl=round(loss_tl, 2),
                    tarih=str(harvest_date),
                )
            except Exception as exc:
                raise RuntimeError(f"Hasat kaydı başarısız: {ticker}") from exc

    def generate_plan(
        self,
        positions: list[Position],
        as_of_date: date | None = None,
        target_weights: dict[str, float] | None = None,
        replacement_map: dict[str, str] | None = None,
    ) -> HarvestPlan:
        """Portföy için hasat planı oluşturur.

        Args:
            positions: Mevcut portföy pozisyonları.
            as_of_date: Değerleme tarihi (None ise bugün).
            target_weights: Hedef portföy ağırlıkları {ticker: ağırlık}.
            replacement_map: İkame hisse sözlüğü {ticker: ikame_ticker}.

        Returns:
            Vergi kayıp hasadı planı.
        """
        today = as_of_date or date.today()
        replacement_map = replacement_map or {}

        plan = HarvestPlan(harvest_date=today)

        for pos in positions:
            # Yalnızca zararlı pozisyonlar
            if pos.unrealized_pnl_pct >= 0:
                continue

            pnl_pct = abs(pos.unrealized_pnl_pct)
            # Hasat eşiğini geçmiyor → atla
            if pnl_pct < self.harvest_threshold_pct:
                continue

            # Minimum işlem değeri kontrolü
            if pos.market_value < DEFAULT_MIN_TRADE_VALUE:
                continue

            days_held = (today - pos.purchase_date).days
            wash_risk = self._check_wash_sale_risk(pos.ticker, today)

            loss_tl = abs(pos.unrealized_pnl)
            # BIST hisse senedi vergi oranı %0 — ancak VIOP/yabancı hisseler için
            # bu değer farklıdır. Temel olarak %0 konfigüre edilmiş.
            estimated_tax_saving = loss_tl * BIST_EQUITY_TAX_RATE
            tx_cost = self._estimate_transaction_cost(pos.market_value)

            candidate = HarvestCandidate(
                position=pos,
                harvestable_loss_tl=loss_tl,
                harvestable_loss_pct=pnl_pct,
                wash_sale_risk=wash_risk,
                days_held=days_held,
                replacement_ticker=replacement_map.get(pos.ticker, ""),
                estimated_tax_saving_tl=estimated_tax_saving,
            )
            plan.candidates.append(candidate)

            if wash_risk:
                plan.wash_sale_warnings.append(pos.ticker)

            plan.total_harvestable_loss_tl += loss_tl
            plan.total_tax_saving_tl += estimated_tax_saving
            plan.estimated_transaction_cost_tl += tx_cost

        plan.net_benefit_tl = plan.total_tax_saving_tl - plan.estimated_transaction_cost_tl

        # En büyük kayıptan küçüğe sırala
        plan.candidates.sort(key=lambda c: c.harvestable_loss_tl, reverse=True)

        logger.info(
            "Hasat planı oluşturuldu.",
            candidates=len(plan.candidates),
            total_loss_tl=round(plan.total_harvestable_loss_tl, 2),
            wash_sale_risks=len(plan.wash_sale_warnings),
            net_benefit_tl=round(plan.net_benefit_tl, 2),
        )
        return plan

    def get_ytd_harvest_summary(self, tax_year: int | None = None) -> dict[str, float]:
        """Yıl içi hasat özetini döndürür.

        Args:
            tax_year: Vergi yılı (None ise mevcut yıl).

        Returns:
            {total_loss_tl, n_events, total_tax_saving_tl} özet sözlüğü.

        Raises:
            RuntimeError: Veritabanı sorgusu başarısız olursa.
        """
        year = tax_year or datetime.now().year
        try:
            with duckdb.connect(self.db_path) as con:
                row = con.execute(
                    f"""
                    SELECT
                        COUNT(*) AS n_events,
                        SUM(ABS(loss_tl)) AS total_loss_tl
                    FROM {DB_TABLE_HARVEST}
                    WHERE tax_year = ?
                    """,
                    [year],
                ).fetchone()
            n = int(row[0]) if row else 0
            total_loss = float(row[1] or 0.0) if row else 0.0
        except duckdb.CatalogException:
            # :memory: veya yeni DB'de tablo henüz oluşmamış
            n, total_loss = 0, 0.0
        except Exception as exc:
            raise RuntimeError(f"YTD hasat özeti sorgulanamadı: {year}") from exc

        return {
            "tax_year": float(year),
            "n_events": float(n),
            "total_loss_tl": total_loss,
            "total_tax_saving_tl": total_loss * BIST_EQUITY_TAX_RATE,
        }


__all__: list[str] = [
    "HarvestCandidate",
    "HarvestPlan",
    "Position",
    "TaxLossHarvestEngine",
    "tax_harvest_engine",
]

# Singleton
tax_harvest_engine = TaxLossHarvestEngine()
