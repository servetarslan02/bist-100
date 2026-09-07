"""ALPHA BIST — Merkezi Risk Kapısı Motoru (Risk Gate).

Merkezi risk kontrolü — her emir piyasaya veya aracı kuruma iletilmeden önce bu kapıdan geçer.
Fail-safe ve Fail-closed: En ufak belirsizlik veya hata durumunda emir engellenir.
DuckDB denetim günlüğü, Polars analitiği, orjson serileştirme ve RLock thread-safety içerir.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

try:
    from services.core.otel import otel_trace
except ImportError:
    import functools

    def otel_trace(name: str):
        """Merkezi OTel tracer bulunamadığında kullanılan yerel fallback dekoratörü."""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

logger = structlog.get_logger(__name__)

DEFAULT_MAX_POSITION_PCT: Final[float] = 10.0
DEFAULT_MAX_PORTFOLIO_EXPOSURE_PCT: Final[float] = 95.0
DEFAULT_MAX_SINGLE_ORDER_PCT: Final[float] = 5.0
DEFAULT_MIN_CONFIDENCE: Final[float] = 0.3
DEFAULT_MAX_DRAWDOWN_PCT: Final[float] = 20.0
DEFAULT_DAILY_LOSS_LIMIT_PCT: Final[float] = 5.0
DEFAULT_MACRO_STRESS_THRESHOLD_PCT: Final[float] = -15.0

DEFAULT_RISK_GATE_DUCKDB_PATH: Final[str] = "data/risk_gate_decisions.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint yapılandırmasını uygular."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("RiskGate DuckDB WAL pragma yapılandırma uyarısı", hata=str(exc))


def to_orjson_bytes(data: Any) -> bytes:
    """Herhangi bir Python nesnesini güvenli ve hızlı şekilde orjson bayt dizisine serileştirir."""
    return orjson.dumps(data, default=str)


@dataclass
class RiskDecision:
    """Emir risk denetim kararı modeli."""

    allowed: bool
    reason: str = ""
    checks_passed: int = 0
    checks_failed: int = 0
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"RiskDecision(allowed={self.allowed}, passed={self.checks_passed}, "
            f"failed={self.checks_failed}, reason='{self.reason}')"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)


class RiskGate:
    """Merkezi pre-trade risk kontrol motoru (Fail-Closed)."""

    def __init__(
        self,
        max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
        max_portfolio_exposure_pct: float = DEFAULT_MAX_PORTFOLIO_EXPOSURE_PCT,
        max_single_order_pct: float = DEFAULT_MAX_SINGLE_ORDER_PCT,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
        daily_loss_limit_pct: float = DEFAULT_DAILY_LOSS_LIMIT_PCT,
        macro_stress_threshold_pct: float = DEFAULT_MACRO_STRESS_THRESHOLD_PCT,
        duckdb_conn: duckdb.DuckDBPyConnection | None = None,
        duckdb_path: str = DEFAULT_RISK_GATE_DUCKDB_PATH,
    ) -> None:
        self._lock = threading.RLock()
        self.max_position_pct = max_position_pct
        self.max_portfolio_exposure_pct = max_portfolio_exposure_pct
        self.max_single_order_pct = max_single_order_pct
        self.min_confidence = min_confidence
        self.max_drawdown_pct = max_drawdown_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.macro_stress_threshold_pct = macro_stress_threshold_pct
        self._daily_pnl: float = 0.0
        self._macro_stress_result: dict[str, Any] | None = None
        self._duckdb_conn = duckdb_conn
        self._duckdb_path = duckdb_path
        if self._duckdb_conn is not None:
            self._init_duckdb_schema_conn(self._duckdb_conn)

    def set_duckdb_connection(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Risk kararları arşivi için DuckDB bağlantısını tanımlar."""
        with self._lock:
            self._duckdb_conn = conn
            self._init_duckdb_schema_conn(self._duckdb_conn)

    def _init_duckdb_schema_conn(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Belirtilen DuckDB bağlantısında risk karar denetim tablosunu ilklendirir."""
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_gate_decisions (
                    id BIGINT,
                    ticker VARCHAR,
                    side VARCHAR,
                    quantity INTEGER,
                    price DOUBLE,
                    allowed BOOLEAN,
                    reason VARCHAR,
                    checks_passed INTEGER,
                    checks_failed INTEGER,
                    details_json VARCHAR,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE SEQUENCE IF NOT EXISTS seq_risk_gate_decisions START 1;
            """)
        except Exception as exc:
            logger.error("RiskGate DuckDB şema oluşturma hatası", hata=str(exc))

    def _get_active_duckdb(self, writable: bool = False) -> tuple[duckdb.DuckDBPyConnection | None, bool]:
        """Aktif DuckDB bağlantısını ve bağlantının geçici (kapatılması gereken) olup olmadığını döner."""
        if self._duckdb_conn is not None:
            return self._duckdb_conn, False
        try:
            db_path = Path(self._duckdb_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            read_only = not writable
            conn = duckdb.connect(str(db_path), read_only=read_only)
            if writable:
                configure_duckdb_wal(conn)
                self._init_duckdb_schema_conn(conn)
            return conn, True
        except Exception as exc:
            logger.debug("RiskGate DuckDB dosya bağlantı hatası", yol=self._duckdb_path, hata=str(exc))
            return None, False

    def _record_decision(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        decision: RiskDecision,
    ) -> None:
        """Risk kararını DuckDB'ye kaydeder."""
        with self._lock:
            conn, should_close = self._get_active_duckdb(writable=True)
            if conn is None:
                return
            try:
                det_json = orjson.dumps(decision.details, default=str).decode("utf-8")
                conn.execute(
                    """
                    INSERT INTO risk_gate_decisions (
                        id, ticker, side, quantity, price, allowed,
                        reason, checks_passed, checks_failed, details_json, checked_at
                    ) VALUES (
                        nextval('seq_risk_gate_decisions'), ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        ticker,
                        side,
                        quantity,
                        price,
                        decision.allowed,
                        decision.reason,
                        decision.checks_passed,
                        decision.checks_failed,
                        det_json,
                        decision.checked_at,
                    ],
                )
            except Exception as exc:
                logger.debug("RiskGate DuckDB kayıt hatası", ticker=ticker, hata=str(exc))
            finally:
                if should_close:
                    with contextlib.suppress(Exception):
                        conn.close()

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"RiskGate(max_pos={self.max_position_pct}%, max_exp={self.max_portfolio_exposure_pct}%, "
                f"min_conf={self.min_confidence}, daily_pnl={self._daily_pnl:.2f})"
            )

    @otel_trace("risk_gate.check_order")
    def check_order(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        portfolio_value: float,
        current_positions: dict[str, Any] | None = None,
        model_confidence: float = 0.5,
        market_open: bool = True,
        data_valid: bool = True,
        circuit_open: bool = False,
        mc_var_95: float = 0.0,
        mc_cvar_95: float = 0.0,
    ) -> RiskDecision:
        """Piyasa emrinin risk denetimini gerçekleştirir (Fail-Closed)."""
        with self._lock:
            positions = current_positions or {}

            # Günlük P&L senkronizasyonu
            self.sync_daily_pnl()

            # 1. Devre Kesici Kontrolleri
            early_exit = self._check_circuit_breakers(circuit_open, ticker)
            if early_exit:
                self._record_decision(ticker, side, quantity, price, early_exit)
                return early_exit

            # Temel Piyasa ve Parametre Kontrolleri
            if not market_open:
                res = RiskDecision(False, "Piyasa kapalı", 0, 1, {"market": "closed"})
                self._record_decision(ticker, side, quantity, price, res)
                return res

            if not data_valid:
                res = RiskDecision(False, "Geçersiz veya bayat piyasa verisi", 0, 1, {"data": "invalid"})
                self._record_decision(ticker, side, quantity, price, res)
                return res

            if quantity <= 0 or price <= 0:
                res = RiskDecision(
                    False,
                    f"Geçersiz emir parametreleri: adet={quantity}, fiyat={price}",
                    0,
                    1,
                    {"order": "invalid_parameters"},
                )
                self._record_decision(ticker, side, quantity, price, res)
                return res

            checks_passed = 3
            checks_failed = 0
            details: dict[str, Any] = {}
            reasons: list[str] = []
            order_value = float(quantity * price)

            # 2. Pozisyon ve Maruziyet Limitleri
            cp, cf, det, rea = self._check_position_limits(
                ticker, side, quantity, price, portfolio_value, positions, model_confidence
            )
            checks_passed += cp
            checks_failed += cf
            details.update(det)
            reasons.extend(rea)

            # 3. Günlük Zarar Limiti
            daily_loss_pct = (abs(self._daily_pnl) / portfolio_value * 100.0) if portfolio_value > 0 else 0.0
            if self._daily_pnl < 0 and daily_loss_pct > self.daily_loss_limit_pct:
                checks_failed += 1
                reasons.append(f"Günlük zarar limiti aşıldı: %{daily_loss_pct:.1f} > %{self.daily_loss_limit_pct:.1f}")
            else:
                checks_passed += 1

            # 4. BIST ve SPK Mevzuat Kuralları
            cp, cf, det, rea_bist = self._check_bist_rules(ticker, side, price, order_value, portfolio_value, positions)
            checks_passed += cp
            checks_failed += cf
            details.update(det)
            reasons.extend(rea_bist)

            # 5. Monte Carlo VaR / CVaR Kontrolü
            cp, cf, rea_mc = self._check_monte_carlo_var(mc_var_95, mc_cvar_95)
            checks_passed += cp
            checks_failed += cf
            reasons.extend(rea_mc)
            if mc_var_95 != 0.0:
                details["mc_var_95"] = round(mc_var_95, 2)
            if mc_cvar_95 != 0.0:
                details["mc_cvar_95"] = round(mc_cvar_95, 2)

            # 6. Makro Stres Testi
            if self._macro_stress_result:
                worst_impact = float(self._macro_stress_result.get("worst_scenario", {}).get("impact_pct", 0.0))
                if worst_impact < self.macro_stress_threshold_pct:
                    checks_failed += 1
                    reasons.append(
                        f"Makro stres testi kritik kayıp riski: %{abs(worst_impact):.1f} (Eşik: %{abs(self.macro_stress_threshold_pct):.0f})"
                    )
                else:
                    checks_passed += 1
                details["macro_stress_worst"] = worst_impact

            allowed = checks_failed == 0
            reason_str = "; ".join(reasons) if reasons else "Tüm risk denetimleri başarıyla geçti"
            decision = RiskDecision(allowed, reason_str, checks_passed, checks_failed, details)

            self._record_decision(ticker, side, quantity, price, decision)
            if not allowed:
                logger.warn(
                    "Emir risk kapısı tarafından REDDEDİLDİ",
                    ticker=ticker,
                    side=side,
                    adet=quantity,
                    fiyat=price,
                    sebep=reason_str,
                )
            return decision

    def _check_circuit_breakers(self, circuit_open: bool, ticker: str) -> RiskDecision | None:
        """Devre kesici ve tavan/taban sınır kontrollerini yürütür."""
        if circuit_open:
            return RiskDecision(False, "Devre kesici devrede (Circuit breaker OPEN)", 0, 1, {"circuit": "open"})

        try:
            from services.core.auto_circuit_breaker import auto_circuit_breaker

            if auto_circuit_breaker.get_status().get("ebdks_active", False):
                return RiskDecision(False, "EBDKS aktif — tüm işlemler durduruldu", 0, 1, {"ebdks": "active"})
        except Exception as exc:
            logger.warn("Devre kesici kontrolü sorgulanamadı", hata=str(exc))

        return None

    def _check_position_limits(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        portfolio_value: float,
        current_positions: dict[str, Any],
        model_confidence: float,
    ) -> tuple[int, int, dict[str, Any], list[str]]:
        """Pozisyon büyüklüğü, tekil emir ve portföy maruziyeti limitlerini denetler."""
        passed = failed = 0
        details: dict[str, Any] = {}
        reasons: list[str] = []

        pv = max(portfolio_value, 1e-6)

        # Portföy Toplam Maruziyeti
        current_exposure = sum(
            float(p.get("qty", 0)) * float(p.get("avg_cost", 0.0)) for p in current_positions.values()
        )
        exposure_pct = (current_exposure / pv) * 100.0
        if exposure_pct > self.max_portfolio_exposure_pct:
            failed += 1
            reasons.append(f"Portföy maruziyeti %{exposure_pct:.1f} > %{self.max_portfolio_exposure_pct:.1f}")
        else:
            passed += 1
        details["exposure_pct"] = round(exposure_pct, 2)

        # Tekil Emir Boyutu
        order_pct = (quantity * price / pv) * 100.0
        if order_pct > self.max_single_order_pct:
            failed += 1
            reasons.append(f"Emir boyutu %{order_pct:.1f} > %{self.max_single_order_pct:.1f}")
        else:
            passed += 1
        details["order_pct"] = round(order_pct, 2)

        # Tekil Hisse Pozisyon Tavanı
        pos = current_positions.get(ticker, {})
        existing_qty = int(pos.get("qty", 0))
        new_qty = existing_qty + quantity if side == "BUY" else existing_qty - quantity
        position_pct = (new_qty * price / pv) * 100.0
        if position_pct > self.max_position_pct:
            failed += 1
            reasons.append(f"Hisse pozisyon tavanı %{position_pct:.1f} > %{self.max_position_pct:.1f}")
        else:
            passed += 1
        details["position_pct"] = round(position_pct, 2)

        # Asgari Model Güveni
        if model_confidence < self.min_confidence:
            failed += 1
            reasons.append(f"Model güveni {model_confidence:.2f} < {self.min_confidence:.2f}")
        else:
            passed += 1
        details["confidence"] = round(model_confidence, 4)

        return passed, failed, details, reasons

    def _check_bist_rules(
        self,
        ticker: str,
        side: str,
        price: float,
        order_value: float,
        portfolio_value: float,
        current_positions: dict[str, Any],
    ) -> tuple[int, int, dict[str, Any], list[str]]:
        """BIST kuralları: açığa satış, işlem durdurma (halt), SPK uyumluluğu."""
        passed = failed = 0
        details: dict[str, Any] = {}
        reasons: list[str] = []

        try:
            from services.core.compliance import compliance_checker
            from services.core.halt_monitor import halt_monitor
            from services.core.short_selling import short_selling_monitor

            # Açığa Satış Yasağı Kontrolü
            if side == "SELL" and ticker not in current_positions:
                ss = short_selling_monitor.can_short_sell(ticker, price, last_trade_price=price)
                if not ss.allowed:
                    failed += 1
                    reasons.append(f"Açığa satış engeli: {ss.reason}")

            # İşlem Durdurma (Halt) Kontrolü
            halt = halt_monitor.check_halt(ticker)
            if halt.halted:
                failed += 1
                reasons.append(f"Hisse işlemleri durdurulmuş (Halt): {halt.reason}")

            # SPK Mevzuat ve Bildirim Kontrolü
            current_pos_pct = 0.0
            if ticker in current_positions and portfolio_value > 0:
                pos_val = float(current_positions[ticker].get("qty", 0)) * float(
                    current_positions[ticker].get("avg_cost", 0.0)
                )
                current_pos_pct = pos_val / portfolio_value
            comp = compliance_checker.check_spk_compliance(side, ticker, order_value, portfolio_value, current_pos_pct)
            if comp.action == "BLOCK":
                failed += 1
                reasons.append(f"SPK kuralı engeli: {comp.reason}")
            elif comp.notification_required:
                details["spk_notification"] = comp.reason

            if failed == 0:
                passed += 1
        except Exception as exc:
            # Fail-closed: Mevzuat denetimi sorgulanamazsa işlem kesinlikle durdurulur!
            logger.error("BIST mevzuat denetimi hatası — emir engelleniyor (Fail-Closed)", hata=str(exc))
            failed += 1
            reasons.append(f"BIST mevzuat denetim hatası: {exc}")

        return passed, failed, details, reasons

    def _check_monte_carlo_var(self, mc_var_95: float, mc_cvar_95: float) -> tuple[int, int, list[str]]:
        """Monte Carlo VaR / CVaR risk tavanı denetimi."""
        passed = failed = 0
        reasons: list[str] = []
        threshold = 15.0

        if mc_var_95 != 0.0:
            var_abs = abs(mc_var_95)
            if var_abs > threshold:
                reasons.append(f"Monte Carlo VaR95 %{var_abs:.1f} > %{threshold:.0f} (Aşırı risk)")
                failed += 1
            else:
                passed += 1

        return passed, failed, reasons

    @otel_trace("risk_gate.set_macro_stress_result")
    def set_macro_stress_result(self, stress_result: dict[str, Any]) -> None:
        """Makro stres testi sonucunu risk kapısına tanımlar."""
        with self._lock:
            self._macro_stress_result = stress_result

    @otel_trace("risk_gate.check_macro_stress")
    def check_macro_stress(self, portfolio: dict[str, Any]) -> dict[str, Any]:
        """Makro stres testini tetikler ve sonucunu saklar."""
        try:
            from services.macro.stress_test import macro_stress_test

            report = macro_stress_test.get_report(portfolio)
            with self._lock:
                self._macro_stress_result = report
            return report
        except Exception as exc:
            logger.warn("Makro stres testi yürütme hatası", hata=str(exc))
            return {"error": str(exc)}

    @otel_trace("risk_gate.update_daily_pnl")
    def update_daily_pnl(self, pnl: float) -> None:
        """Günlük kâr/zarar değerini günceller."""
        with self._lock:
            self._daily_pnl = float(pnl)

    @otel_trace("risk_gate.sync_daily_pnl")
    def sync_daily_pnl(self) -> None:
        """PortfolioManager üzerinden günlük P&L değerini otomatik senkronize eder."""
        try:
            from services.portfolio.portfolio_manager import portfolio_manager

            if portfolio_manager is not None:
                snapshots = portfolio_manager.get_equity_snapshots(limit=2)
                if len(snapshots) >= 2:
                    today_equity = float(snapshots[-1]["total_equity"])
                    yesterday_equity = float(snapshots[-2]["total_equity"])
                    with self._lock:
                        self._daily_pnl = today_equity - yesterday_equity
                else:
                    with self._lock:
                        self._daily_pnl = 0.0
        except Exception as exc:
            logger.debug("Günlük PnL senkronizasyonu atlandı", hata=str(exc))

    @otel_trace("risk_gate.reset_daily")
    def reset_daily(self) -> None:
        """Günlük P&L sayacını sıfırlar."""
        with self._lock:
            self._daily_pnl = 0.0

    def export_decisions_to_polars(self) -> pl.DataFrame:
        """DuckDB üzerindeki risk kararlarını Polars DataFrame olarak dışa aktarır."""
        return self.read_decisions_from_duckdb()

    def read_decisions_from_duckdb(self, limit: int = 1000) -> pl.DataFrame:
        """DuckDB üzerindeki risk kararlarını okur ve Polars DataFrame olarak döner."""
        empty_df = pl.DataFrame(
            schema={
                "ticker": pl.Utf8,
                "side": pl.Utf8,
                "quantity": pl.Int64,
                "price": pl.Float64,
                "allowed": pl.Boolean,
                "reason": pl.Utf8,
                "checks_passed": pl.Int64,
                "checks_failed": pl.Int64,
                "checked_at": pl.Datetime("ms"),
            }
        )
        with self._lock:
            conn, should_close = self._get_active_duckdb(writable=False)
            if conn is None:
                return empty_df
            try:
                query = f"""
                    SELECT ticker, side, quantity, price, allowed, reason, checks_passed, checks_failed, checked_at
                    FROM risk_gate_decisions
                    ORDER BY id DESC
                    LIMIT {int(limit)}
                """
                return conn.execute(query).pl()
            except Exception as exc:
                logger.error("DuckDB risk kararları Polars sorgu hatası", hata=str(exc))
                return empty_df
            finally:
                if should_close:
                    with contextlib.suppress(Exception):
                        conn.close()

    def clear_decisions_duckdb(self) -> None:
        """DuckDB üzerindeki risk kararlarını temizler."""
        with self._lock:
            conn, should_close = self._get_active_duckdb(writable=True)
            if conn is None:
                return
            try:
                conn.execute("DELETE FROM risk_gate_decisions;")
            except Exception as exc:
                logger.error("DuckDB risk kararları temizleme hatası", hata=str(exc))
            finally:
                if should_close:
                    with contextlib.suppress(Exception):
                        conn.close()


def read_risk_gate_decisions_from_duckdb(
    duckdb_path: str = DEFAULT_RISK_GATE_DUCKDB_PATH,
    limit: int = 1000,
) -> pl.DataFrame:
    """Doğrudan DuckDB dosyasından risk kararlarını okur."""
    empty_df = pl.DataFrame(
        schema={
            "ticker": pl.Utf8,
            "side": pl.Utf8,
            "quantity": pl.Int64,
            "price": pl.Float64,
            "allowed": pl.Boolean,
            "reason": pl.Utf8,
            "checks_passed": pl.Int64,
            "checks_failed": pl.Int64,
            "checked_at": pl.Datetime("ms"),
        }
    )
    p = Path(duckdb_path)
    if not p.exists():
        return empty_df
    try:
        conn = duckdb.connect(str(p), read_only=True)
        try:
            query = f"""
                SELECT ticker, side, quantity, price, allowed, reason, checks_passed, checks_failed, checked_at
                FROM risk_gate_decisions
                ORDER BY id DESC
                LIMIT {int(limit)}
            """
            return conn.execute(query).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB doğrudan risk kararları okuma hatası", yol=duckdb_path, hata=str(exc))
        return empty_df


def clear_risk_gate_decisions_duckdb(
    duckdb_path: str = DEFAULT_RISK_GATE_DUCKDB_PATH,
) -> None:
    """Doğrudan DuckDB dosyasındaki risk kararları tablosunu temizler."""
    p = Path(duckdb_path)
    if not p.exists():
        return
    try:
        conn = duckdb.connect(str(p), read_only=False)
        configure_duckdb_wal(conn)
        try:
            conn.execute("DELETE FROM risk_gate_decisions;")
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB doğrudan risk kararları temizleme hatası", yol=duckdb_path, hata=str(exc))


# Global Singleton
risk_gate = RiskGate()

__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_DAILY_LOSS_LIMIT_PCT",
    "DEFAULT_MACRO_STRESS_THRESHOLD_PCT",
    "DEFAULT_MAX_DRAWDOWN_PCT",
    "DEFAULT_MAX_PORTFOLIO_EXPOSURE_PCT",
    "DEFAULT_MAX_POSITION_PCT",
    "DEFAULT_MAX_SINGLE_ORDER_PCT",
    "DEFAULT_MIN_CONFIDENCE",
    "DEFAULT_RISK_GATE_DUCKDB_PATH",
    "DEFAULT_WAL_SIZE",
    "RiskDecision",
    "RiskGate",
    "clear_risk_gate_decisions_duckdb",
    "configure_duckdb_wal",
    "read_risk_gate_decisions_from_duckdb",
    "risk_gate",
    "to_orjson_bytes",
]
