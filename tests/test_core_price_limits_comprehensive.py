"""ALPHA BIST — services/core/price_limits kapsamlı test suite.

Test edilen bileşenler:
- PriceLimitResult: Fiyat limiti denetim sonucu veri modeli
- PriceLimitMonitor: Ana limit yönetici sınıfı
  - set_custom_limit(): Özel limit atama
  - set_market_type(): Pazar tipi atama
  - add_ipo_ticker(): Halka arz serbest marja alma
  - set_post_circuit_breaker_limit(): Devre kesici sonrası marj daraltma
  - get_effective_limit(): Efektif limit hesaplama
  - check_price_limit(): Tek hisse limit denetimi
  - check_price_limits_polars(): Toplu Polars vektörel denetim
- MARKET_LIMITS: Pazar bazlı limit haritası
"""

from __future__ import annotations

import orjson
import polars as pl
import pytest

from services.core.price_limits import (
    DEFAULT_LIMIT_PCT,
    DEFAULT_POST_CB_LIMIT_PCT,
    MARKET_LIMITS,
    PriceLimitMonitor,
    PriceLimitResult,
)

# ==============================================================================
# Sabit doğrulama testleri
# ==============================================================================


class TestRegulatoryConstants:
    """BIST fiyat limiti sabitlerinin doğrulanması."""

    def test_default_limit_pct(self) -> None:
        """Standart pazarlarda ±%10 limiti."""
        assert pytest.approx(10.0) == DEFAULT_LIMIT_PCT

    def test_post_cb_limit_pct(self) -> None:
        """Devre kesici sonrası ±%5 daraltılmış marj."""
        assert pytest.approx(5.0) == DEFAULT_POST_CB_LIMIT_PCT

    def test_market_limits_defined(self) -> None:
        """Tüm pazar tipleri için limit tanımlı."""
        required_markets = {"yildiz", "ana", "alt", "serbest"}
        assert required_markets.issubset(MARKET_LIMITS.keys())

    def test_serbest_market_has_no_limit(self) -> None:
        """Serbest İşlem pazarında limit yok (0.0)."""
        assert MARKET_LIMITS["serbest"] == 0.0

    def test_standard_markets_ten_percent(self) -> None:
        """Yıldız, Ana, Alt pazarlar %10 limiti."""
        for market in ("yildiz", "ana", "alt"):
            assert MARKET_LIMITS[market] == pytest.approx(10.0)


# ==============================================================================
# PriceLimitResult veri modeli testleri
# ==============================================================================


class TestPriceLimitResult:
    """PriceLimitResult dataclass veri modeli testleri."""

    def _make_result(
        self,
        limit_hit: bool = False,
        direction: str = "",
        ticker: str = "THYAO",
        current_price: float = 100.0,
        reference_price: float = 100.0,
    ) -> PriceLimitResult:
        return PriceLimitResult(
            limit_hit=limit_hit,
            direction=direction,
            change_pct=0.0,
            limit=10.0,
            reference_price=reference_price,
            current_price=current_price,
            upper_limit=110.0,
            lower_limit=90.0,
            ticker=ticker,
        )

    def test_creation_and_fields(self) -> None:
        r = self._make_result(limit_hit=True, direction="UP")
        assert r.limit_hit is True
        assert r.direction == "UP"
        assert r.ticker == "THYAO"

    def test_to_dict(self) -> None:
        r = self._make_result()
        d = r.to_dict()
        assert "ticker" in d
        assert "limit_hit" in d
        assert "direction" in d
        assert "upper_limit" in d
        assert "lower_limit" in d

    def test_to_orjson_bytes(self) -> None:
        r = self._make_result(ticker="GARAN")
        raw = r.to_orjson_bytes()
        assert isinstance(raw, bytes)
        parsed = orjson.loads(raw)
        assert parsed["ticker"] == "GARAN"

    def test_repr(self) -> None:
        r = self._make_result(limit_hit=True, direction="DOWN", ticker="AKBNK")
        repr_str = repr(r)
        assert "AKBNK" in repr_str
        assert "DOWN" in repr_str


# ==============================================================================
# PriceLimitMonitor temel testleri
# ==============================================================================


@pytest.fixture
def monitor() -> PriceLimitMonitor:
    """Test için PriceLimitMonitor örneği."""
    return PriceLimitMonitor(duckdb_path=":memory:")


class TestPriceLimitMonitorInit:
    """PriceLimitMonitor başlangıç durumu testleri."""

    def test_default_limit(self, monitor: PriceLimitMonitor) -> None:
        assert pytest.approx(10.0) == monitor.DEFAULT_LIMIT

    def test_post_cb_limit(self, monitor: PriceLimitMonitor) -> None:
        assert pytest.approx(5.0) == monitor.POST_CB_LIMIT


# ==============================================================================
# get_effective_limit testleri
# ==============================================================================


class TestGetEffectiveLimit:
    """get_effective_limit() metodu testleri."""

    def test_default_limit_unknown_ticker(self, monitor: PriceLimitMonitor) -> None:
        """Bilinmeyen hisse için varsayılan %10 limiti."""
        limit = monitor.get_effective_limit("UNKN")
        assert limit == pytest.approx(10.0)

    def test_custom_limit_applied(self, monitor: PriceLimitMonitor) -> None:
        """Özel limit belirlenmiş hisse için özel limit döner."""
        monitor.set_custom_limit("THYAO", 5.0)
        limit = monitor.get_effective_limit("THYAO")
        assert limit == pytest.approx(5.0)

    def test_ipo_ticker_zero_limit(self, monitor: PriceLimitMonitor) -> None:
        """Halka arz günü hisseler için limit yok (0.0)."""
        monitor.add_ipo_ticker("NEWCO")
        limit = monitor.get_effective_limit("NEWCO")
        assert limit == pytest.approx(0.0)

    def test_post_cb_limit_applied(self, monitor: PriceLimitMonitor) -> None:
        """Devre kesici sonrası ±%5 daraltılmış marj."""
        monitor.set_post_circuit_breaker_limit("BIMAS")
        limit = monitor.get_effective_limit("BIMAS")
        assert limit == pytest.approx(5.0)

    def test_market_type_limit(self, monitor: PriceLimitMonitor) -> None:
        """Pazar tipi bazlı limit."""
        monitor.set_market_type("ASELS", "yildiz")
        limit = monitor.get_effective_limit("ASELS")
        assert limit == pytest.approx(10.0)  # Yıldız Pazar %10

    def test_ipo_priority_over_custom(self, monitor: PriceLimitMonitor) -> None:
        """Halka arz günü diğer limitlerden önce gelir."""
        monitor.set_custom_limit("NEWCO", 5.0)
        monitor.add_ipo_ticker("NEWCO")
        limit = monitor.get_effective_limit("NEWCO")
        assert limit == pytest.approx(0.0)  # IPO priority

    def test_post_cb_priority_over_custom(self, monitor: PriceLimitMonitor) -> None:
        """Devre kesici sonrası marj, özel limitten önce gelir."""
        monitor.set_custom_limit("GARAN", 8.0)
        monitor.set_post_circuit_breaker_limit("GARAN")
        limit = monitor.get_effective_limit("GARAN")
        assert limit == pytest.approx(5.0)  # Post-CB priority


# ==============================================================================
# check_price_limit testleri
# ==============================================================================


class TestCheckPriceLimit:
    """check_price_limit() metodu testleri."""

    def test_price_within_limits_no_hit(self, monitor: PriceLimitMonitor) -> None:
        """Normal fiyat değişimi limiti aşmaz."""
        result = monitor.check_price_limit(
            ticker="THYAO",
            current_price=105.0,
            reference_price=100.0,
        )
        assert result.limit_hit is False
        assert result.direction == ""

    def test_upper_limit_hit(self, monitor: PriceLimitMonitor) -> None:
        """Tavan limitine ulaşma: %10 artış."""
        result = monitor.check_price_limit(
            ticker="THYAO",
            current_price=110.0,
            reference_price=100.0,
        )
        assert result.limit_hit is True
        assert result.direction == "UP"

    def test_lower_limit_hit(self, monitor: PriceLimitMonitor) -> None:
        """Taban limitine ulaşma: %10 düşüş."""
        result = monitor.check_price_limit(
            ticker="THYAO",
            current_price=90.0,
            reference_price=100.0,
        )
        assert result.limit_hit is True
        assert result.direction == "DOWN"

    def test_slightly_above_no_hit(self, monitor: PriceLimitMonitor) -> None:
        """Limitin içinde kalan küçük artış."""
        result = monitor.check_price_limit(
            ticker="THYAO",
            current_price=105.0,  # %5 artış
            reference_price=100.0,
        )
        assert result.limit_hit is False

    def test_change_pct_calculated(self, monitor: PriceLimitMonitor) -> None:
        """Değişim yüzdesi doğru hesaplanır."""
        result = monitor.check_price_limit(
            ticker="GARAN",
            current_price=105.0,
            reference_price=100.0,
        )
        assert result.change_pct == pytest.approx(5.0, abs=0.01)

    def test_zero_reference_price_safe(self, monitor: PriceLimitMonitor) -> None:
        """Sıfır referans fiyatta güvenli sonuç döner (sıfıra bölünme yok)."""
        result = monitor.check_price_limit(
            ticker="UNKN",
            current_price=10.0,
            reference_price=0.0,
        )
        assert result.limit_hit is False

    def test_zero_current_price_safe(self, monitor: PriceLimitMonitor) -> None:
        """Sıfır güncel fiyatta güvenli sonuç döner."""
        result = monitor.check_price_limit(
            ticker="UNKN",
            current_price=0.0,
            reference_price=100.0,
        )
        assert result.limit_hit is False

    def test_ipo_ticker_no_limit(self, monitor: PriceLimitMonitor) -> None:
        """Halka arz günü fiyat limiti uygulanmaz."""
        monitor.add_ipo_ticker("NEWCO")
        result = monitor.check_price_limit(
            ticker="NEWCO",
            current_price=200.0,  # %100 artış
            reference_price=100.0,
        )
        assert result.limit_hit is False
        assert result.limit == 0.0

    def test_post_cb_limit_tighter(self, monitor: PriceLimitMonitor) -> None:
        """Devre kesici sonrası ±%5 marj → %7 değişimde limit aşılır."""
        monitor.set_post_circuit_breaker_limit("BIMAS")
        result = monitor.check_price_limit(
            ticker="BIMAS",
            current_price=107.0,  # %7 artış → %5 sınır aşıldı
            reference_price=100.0,
        )
        assert result.limit_hit is True

    def test_ticker_in_result(self, monitor: PriceLimitMonitor) -> None:
        """Sonuçta ticker bilgisi doğru yer alır."""
        result = monitor.check_price_limit(
            ticker="AKBNK",
            current_price=50.0,
            reference_price=50.0,
        )
        assert result.ticker == "AKBNK"

    def test_upper_lower_limits_calculated(self, monitor: PriceLimitMonitor) -> None:
        """Tavan ve taban fiyatları referans fiyata göre doğru hesaplanır."""
        result = monitor.check_price_limit(
            ticker="FROTO",
            current_price=500.0,
            reference_price=500.0,
        )
        # ±%10 limitlerinde tavan ~550, taban ~450
        assert result.upper_limit > 500.0
        assert result.lower_limit < 500.0
        assert result.upper_limit <= 550.0 + 1.0  # BIST tick rounding nedeniyle küçük tolerans
        assert result.lower_limit >= 450.0 - 1.0


# ==============================================================================
# check_price_limits_polars testleri
# ==============================================================================


class TestCheckPriceLimitsPolars:
    """Toplu Polars vektörel limit denetimi testleri."""

    def test_basic_polars_check(self, monitor: PriceLimitMonitor) -> None:
        """Temel Polars DataFrame limit denetimi."""
        df = pl.DataFrame({
            "ticker": ["THYAO", "GARAN", "AKBNK"],
            "close": [110.0, 90.0, 100.0],
            "prev_close": [100.0, 100.0, 100.0],
        })
        result = monitor.check_price_limits_polars(df)
        assert isinstance(result, pl.DataFrame)
        assert "limit_hit" in result.columns
        assert "change_pct" in result.columns
        assert "upper_limit" in result.columns
        assert "lower_limit" in result.columns

    def test_polars_upper_limit_detected(self, monitor: PriceLimitMonitor) -> None:
        """Tavan limiti vektörel denetimde tespit edilir."""
        df = pl.DataFrame({
            "ticker": ["THYAO"],
            "close": [110.0],
            "prev_close": [100.0],
        })
        result = monitor.check_price_limits_polars(df)
        assert result["limit_hit"][0] is True

    def test_polars_lower_limit_detected(self, monitor: PriceLimitMonitor) -> None:
        """Taban limiti vektörel denetimde tespit edilir."""
        df = pl.DataFrame({
            "ticker": ["GARAN"],
            "close": [90.0],
            "prev_close": [100.0],
        })
        result = monitor.check_price_limits_polars(df)
        assert result["limit_hit"][0] is True

    def test_polars_no_limit_hit(self, monitor: PriceLimitMonitor) -> None:
        """Normal fiyat aralığında limit aşımı yok."""
        df = pl.DataFrame({
            "ticker": ["AKBNK"],
            "close": [105.0],
            "prev_close": [100.0],
        })
        result = monitor.check_price_limits_polars(df)
        assert result["limit_hit"][0] is False

    def test_polars_empty_dataframe(self, monitor: PriceLimitMonitor) -> None:
        """Boş DataFrame boş döner."""
        df = pl.DataFrame({
            "ticker": pl.Series([], dtype=pl.Utf8),
            "close": pl.Series([], dtype=pl.Float64),
            "prev_close": pl.Series([], dtype=pl.Float64),
        })
        result = monitor.check_price_limits_polars(df)
        assert result.is_empty()

    def test_polars_change_pct_correct(self, monitor: PriceLimitMonitor) -> None:
        """Değişim yüzdesi Polars hesabında doğru."""
        df = pl.DataFrame({
            "ticker": ["THYAO"],
            "close": [115.0],
            "prev_close": [100.0],
        })
        result = monitor.check_price_limits_polars(df)
        assert result["change_pct"][0] == pytest.approx(15.0, abs=0.01)


# ==============================================================================
# Ticker yönetimi testleri
# ==============================================================================


class TestTickerManagement:
    """Ticker yönetim operasyonları testleri."""

    def test_add_and_remove_ipo_ticker(self, monitor: PriceLimitMonitor) -> None:
        monitor.add_ipo_ticker("NEWCO")
        assert monitor.get_effective_limit("NEWCO") == 0.0
        monitor.remove_ipo_ticker("NEWCO")
        assert monitor.get_effective_limit("NEWCO") == pytest.approx(10.0)

    def test_add_and_clear_post_cb_limit(self, monitor: PriceLimitMonitor) -> None:
        monitor.set_post_circuit_breaker_limit("BIMAS")
        assert monitor.get_effective_limit("BIMAS") == pytest.approx(5.0)
        monitor.clear_post_circuit_breaker_limit("BIMAS")
        assert monitor.get_effective_limit("BIMAS") == pytest.approx(10.0)

    def test_add_corp_action_ticker(self, monitor: PriceLimitMonitor) -> None:
        monitor.add_corporate_action_ticker("SAHOL")
        # Kurumsal işlem sonrası standart limit geçerli
        monitor.remove_corporate_action_ticker("SAHOL")

    def test_multiple_custom_limits(self, monitor: PriceLimitMonitor) -> None:
        """Birden fazla hisse için özel limit."""
        tickers = {"THYAO": 3.0, "GARAN": 7.5, "AKBNK": 10.0}
        for ticker, limit in tickers.items():
            monitor.set_custom_limit(ticker, limit)
        for ticker, limit in tickers.items():
            assert monitor.get_effective_limit(ticker) == pytest.approx(limit)


# ==============================================================================
# Thread-safety testleri
# ==============================================================================


class TestThreadSafety:
    """PriceLimitMonitor eş zamanlı erişim güvenliği testleri."""

    def test_concurrent_check_price_limit(self, monitor: PriceLimitMonitor) -> None:
        """Eş zamanlı fiyat limit denetimi race condition vermez."""
        import threading
        results = []
        errors = []

        def check() -> None:
            try:
                r = monitor.check_price_limit("THYAO", 105.0, 100.0)
                results.append(r.limit_hit)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=check) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 20
