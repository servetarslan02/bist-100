"""ALPHA BIST — services/core/debounce kapsamlı test suite.

Test edilen bileşenler:
- should_save(): İmperatif debounce izin denetimi
- debounced_save(): Senkron ve async fonksiyon dekoratörü
- get_remaining_debounce_time(): Kalan bekleme süresi
- reset_debounce(): Global durum sıfırlama
- get_debounce_stats(): İstatistik sözlüğü
- export_debounce_metrics_to_polars(): Polars DataFrame dışa aktarım
- export_debounce_to_orjson_bytes(): orjson serileştirme
- configure_duckdb_wal(): DuckDB WAL yapılandırma (SQL injection koruması)
"""

from __future__ import annotations

import asyncio

# ==============================================================================
# Test izolasyonu: Her test kendi debounce namespace'ini kullanır
# ==============================================================================
import itertools
import threading
import time

import duckdb
import polars as pl
import pytest

from services.core.debounce import (
    _WAL_PARAM_REGEX,
    DEFAULT_MIN_INTERVAL_SEC,
    configure_duckdb_wal,
    debounced_save,
    export_debounce_metrics_to_polars,
    export_debounce_to_orjson_bytes,
    get_debounce_stats,
    get_remaining_debounce_time,
    reset_debounce,
    should_save,
)

_KEY_COUNTER = itertools.count()


def _unique_key() -> str:
    """Her test için gerçekten benzersiz anahtar üretir."""
    return f"test_key_{next(_KEY_COUNTER)}"


@pytest.fixture(autouse=True)
def _clean_debounce_state() -> None:
    """Her testten önce ve sonra debounce durumunu sıfırla."""
    reset_debounce()  # Önce sıfırla
    yield
    reset_debounce()  # Sonra da sıfırla


# ==============================================================================
# Sabit doğrulama testleri
# ==============================================================================


class TestConstants:
    """Modül sabitlerinin doğrulanması."""

    def test_default_min_interval(self) -> None:
        """Varsayılan minimum interval 30 saniye."""
        assert DEFAULT_MIN_INTERVAL_SEC == 30.0

    def test_wal_param_regex_valid(self) -> None:
        """Geçerli WAL parametreleri regex'i geçer."""
        valid = ["2MB", "4MB", "1GB", "512KB", "100B"]
        for v in valid:
            assert _WAL_PARAM_REGEX.match(v), f"{v!r} geçerli olmalı"

    def test_wal_param_regex_invalid(self) -> None:
        """SQL injection girişimleri regex'i geçemez."""
        invalid = ["'; DROP TABLE--", "2MB; SELECT 1", "abc", "", "2MB OR 1=1"]
        for v in invalid:
            assert not _WAL_PARAM_REGEX.match(v), f"{v!r} geçersiz olmalı"


# ==============================================================================
# should_save testleri
# ==============================================================================


class TestShouldSave:
    """should_save() imperatif debounce testleri."""

    def test_first_call_returns_true(self) -> None:
        """İlk çağrıda her zaman True döner."""
        key = _unique_key()
        assert should_save(key, 60.0) is True

    def test_second_immediate_call_returns_false(self) -> None:
        """Süre dolmadan ikinci çağrıda False döner."""
        key = _unique_key()
        should_save(key, 60.0)  # İlk çağrı
        assert should_save(key, 60.0) is False

    def test_third_call_after_zero_interval_always_true(self) -> None:
        """Sıfır interval → her çağrıda True döner."""
        key = _unique_key()
        assert should_save(key, 0.0) is True
        assert should_save(key, 0.0) is True

    def test_true_updates_timestamp(self) -> None:
        """True dönen çağrı sonrası zaman damgası güncellenir."""
        key = _unique_key()
        should_save(key, 60.0)
        remaining = get_remaining_debounce_time(key, 60.0)
        assert remaining > 0.0

    def test_different_keys_independent(self) -> None:
        """Farklı anahtarlar bağımsız çalışır."""
        k1, k2 = _unique_key(), _unique_key()
        should_save(k1, 60.0)  # k1 kullanıldı
        # k2 hiç kullanılmadı, ilk çağrısı True dönmeli
        result = should_save(k2, 60.0)
        assert result is True  # k2 bağımsız

    def test_negative_interval_always_true(self) -> None:
        """Negatif interval → debounce yok."""
        key = _unique_key()
        should_save(key, -1.0)
        assert should_save(key, -1.0) is True


# ==============================================================================
# get_remaining_debounce_time testleri
# ==============================================================================


class TestGetRemainingDebounceTime:
    """get_remaining_debounce_time() testleri."""

    def test_unseen_key_returns_zero(self) -> None:
        """Bilinmeyen anahtar için kalan süre sıfırdır."""
        remaining = get_remaining_debounce_time("unknown_key_xyz", 60.0)
        assert remaining == 0.0

    def test_after_save_returns_positive(self) -> None:
        """should_save() sonrası kalan süre pozitif."""
        key = _unique_key()
        should_save(key, 60.0)
        remaining = get_remaining_debounce_time(key, 60.0)
        assert remaining > 0.0
        assert remaining <= 60.0

    def test_remaining_time_decreases(self) -> None:
        """Zaman geçtikçe kalan süre azalır."""
        key = _unique_key()
        should_save(key, 10.0)
        r1 = get_remaining_debounce_time(key, 10.0)
        time.sleep(0.1)
        r2 = get_remaining_debounce_time(key, 10.0)
        assert r2 < r1


# ==============================================================================
# reset_debounce testleri
# ==============================================================================


class TestResetDebounce:
    """reset_debounce() testleri."""

    def test_reset_single_key(self) -> None:
        """Tekil anahtar sıfırlama."""
        key = _unique_key()
        should_save(key, 60.0)
        assert should_save(key, 60.0) is False  # Debounce aktif
        reset_debounce(key)
        assert should_save(key, 60.0) is True  # Sıfırlandı

    def test_reset_all_keys(self) -> None:
        """Tüm anahtarları sıfırlama."""
        k1, k2 = _unique_key(), _unique_key()
        should_save(k1, 60.0)
        should_save(k2, 60.0)
        reset_debounce()  # Tüm anahtarlar sıfırlandı
        # Yeni çağrılar True dönmeli
        r1 = should_save(k1, 60.0)
        reset_debounce(k1)  # Sadece k1'i tekrar sıfırla
        r2 = should_save(k2, 60.0)
        assert r1 is True
        assert r2 is True

    def test_reset_unknown_key_no_error(self) -> None:
        """Bilinmeyen anahtar sıfırlaması hata vermez."""
        reset_debounce("_nonexistent_key_abc")  # Sessizce başarılı


# ==============================================================================
# get_debounce_stats testleri
# ==============================================================================


class TestGetDebounceStats:
    """get_debounce_stats() testleri."""

    def test_empty_stats_returns_empty_dict(self) -> None:
        """Kayıt yokken boş sözlük döner."""
        stats = get_debounce_stats()
        assert isinstance(stats, dict)
        assert len(stats) == 0

    def test_after_save_key_appears(self) -> None:
        """should_save() sonrası anahtar istatistiklerde görünür."""
        key = _unique_key()
        should_save(key, 60.0)
        stats = get_debounce_stats()
        assert key in stats

    def test_stats_has_required_fields(self) -> None:
        """İstatistik sözlüğü gerekli alanları içerir."""
        key = _unique_key()
        should_save(key, 60.0)
        stat = get_debounce_stats()[key]
        assert "key" in stat
        assert "elapsed_seconds" in stat
        assert "allowed_writes" in stat
        assert "debounced_calls" in stat

    def test_blocked_call_increments_debounced_count(self) -> None:
        """Engellenen çağrı debounced_calls sayacını artırır."""
        key = _unique_key()
        should_save(key, 60.0)
        should_save(key, 60.0)  # Engellendi
        stat = get_debounce_stats()[key]
        assert stat["debounced_calls"] >= 1

    def test_allowed_writes_count(self) -> None:
        """İzin verilen yazma sayısı doğru sayılır."""
        key = _unique_key()
        should_save(key, 0.0)
        should_save(key, 0.0)
        stat = get_debounce_stats()[key]
        assert stat["allowed_writes"] == 2


# ==============================================================================
# debounced_save dekoratörü testleri
# ==============================================================================


class TestDebouncedSaveDecorator:
    """@debounced_save dekoratörü testleri."""

    def test_sync_function_allowed_first_call(self) -> None:
        """Senkron fonksiyon ilk çağrıda çalışır."""
        key = _unique_key()
        results = []

        @debounced_save(key, 60.0)
        def save_data(v: int) -> int:
            results.append(v)
            return v

        result = save_data(42)
        assert result == 42
        assert 42 in results

    def test_sync_function_blocked_second_call(self) -> None:
        """Senkron fonksiyon ikinci çağrıda engellenir ve None döner."""
        key = _unique_key()
        call_count = [0]

        @debounced_save(key, 60.0)
        def expensive_save() -> str:
            call_count[0] += 1
            return "saved"

        expensive_save()
        result = expensive_save()
        assert result is None
        assert call_count[0] == 1

    def test_sync_function_zero_interval_always_runs(self) -> None:
        """Sıfır interval → her çağrıda çalışır."""
        key = _unique_key()
        call_count = [0]

        @debounced_save(key, 0.0)
        def always_save() -> None:
            call_count[0] += 1

        always_save()
        always_save()
        assert call_count[0] == 2

    def test_async_function_allowed_first_call(self) -> None:
        """Asenkron fonksiyon ilk çağrıda çalışır."""
        key = _unique_key()
        results: list[int] = []

        @debounced_save(key, 60.0)
        async def async_save(v: int) -> int:
            results.append(v)
            return v

        result = asyncio.run(async_save(99))
        assert result == 99
        assert 99 in results

    def test_async_function_blocked_second_call(self) -> None:
        """Asenkron fonksiyon ikinci çağrıda engellenir."""
        key = _unique_key()
        call_count = [0]

        @debounced_save(key, 60.0)
        async def async_expensive() -> None:
            call_count[0] += 1

        async def run() -> None:
            await async_expensive()
            await async_expensive()

        asyncio.run(run())
        assert call_count[0] == 1

    def test_preserves_function_metadata(self) -> None:
        """Dekoratör orijinal fonksiyon metadata'sını korur."""
        key = _unique_key()

        @debounced_save(key, 60.0)
        def documented_fn() -> None:
            """Belgelenmiş fonksiyon."""
            pass

        assert documented_fn.__name__ == "documented_fn"
        assert "Belgelenmiş" in (documented_fn.__doc__ or "")


# ==============================================================================
# export_debounce_metrics_to_polars testleri
# ==============================================================================


class TestExportDebounceMetricsToPolars:
    """Polars metrik dışa aktarım testleri."""

    def test_empty_returns_empty_dataframe(self) -> None:
        """Debounce kaydı yokken boş Polars DataFrame döner."""
        df = export_debounce_metrics_to_polars()
        assert isinstance(df, pl.DataFrame)
        assert df.is_empty()

    def test_after_save_returns_nonempty(self) -> None:
        """Kayıt sonrası veri içeren DataFrame döner."""
        key = _unique_key()
        should_save(key, 60.0)
        df = export_debounce_metrics_to_polars()
        assert len(df) >= 1

    def test_dataframe_has_correct_columns(self) -> None:
        """DataFrame beklenen sütunları içerir."""
        key = _unique_key()
        should_save(key, 60.0)
        df = export_debounce_metrics_to_polars()
        expected_cols = {"key", "elapsed_seconds", "allowed_writes", "debounced_calls"}
        assert expected_cols.issubset(set(df.columns))

    def test_dataframe_correct_types(self) -> None:
        """DataFrame sütun tipleri doğru."""
        key = _unique_key()
        should_save(key, 60.0)
        df = export_debounce_metrics_to_polars()
        assert df["key"].dtype == pl.Utf8
        assert df["elapsed_seconds"].dtype == pl.Float64
        assert df["allowed_writes"].dtype == pl.Int64
        assert df["debounced_calls"].dtype == pl.Int64


# ==============================================================================
# export_debounce_to_orjson_bytes testleri
# ==============================================================================


class TestExportDebounceToOrjson:
    """orjson serileştirme testleri."""

    def test_returns_bytes(self) -> None:
        key = _unique_key()
        should_save(key, 60.0)
        raw = export_debounce_to_orjson_bytes()
        assert isinstance(raw, bytes)

    def test_valid_json_structure(self) -> None:
        import orjson

        key = _unique_key()
        should_save(key, 60.0)
        raw = export_debounce_to_orjson_bytes()
        parsed = orjson.loads(raw)
        assert isinstance(parsed, dict)
        assert key in parsed


# ==============================================================================
# configure_duckdb_wal testleri
# ==============================================================================


class TestConfigureDuckdbWal:
    """DuckDB WAL yapılandırma ve SQL injection koruması testleri."""

    def test_valid_wal_params_no_error(self) -> None:
        """Geçerli WAL parametreleri hata vermez."""
        with duckdb.connect(":memory:") as conn:
            configure_duckdb_wal(conn, wal_size="2MB", checkpoint="4MB")

    def test_invalid_wal_size_raises(self) -> None:
        """Geçersiz wal_size hata fırlatır."""
        with duckdb.connect(":memory:") as conn:
            with pytest.raises(ValueError, match="Geçersiz wal_size"):
                configure_duckdb_wal(conn, wal_size="'; DROP TABLE--")

    def test_invalid_checkpoint_raises(self) -> None:
        """Geçersiz checkpoint parametresi hata fırlatır."""
        with duckdb.connect(":memory:") as conn:
            with pytest.raises(ValueError, match="Geçersiz checkpoint"):
                configure_duckdb_wal(conn, checkpoint="OR 1=1")

    def test_empty_wal_size_raises(self) -> None:
        with duckdb.connect(":memory:") as conn:
            with pytest.raises(ValueError):
                configure_duckdb_wal(conn, wal_size="")

    def test_common_sizes_accepted(self) -> None:
        """Yaygın boyut formatları kabul edilir."""
        sizes = ["1MB", "512KB", "2GB", "100B"]
        with duckdb.connect(":memory:") as conn:
            for size in sizes:
                configure_duckdb_wal(conn, wal_size=size, checkpoint="4MB")


# ==============================================================================
# Thread-safety testleri
# ==============================================================================


class TestThreadSafety:
    """Debounce eş zamanlı erişim güvenliği testleri."""

    def test_concurrent_should_save(self) -> None:
        """Eş zamanlı should_save çağrıları race condition vermez."""
        key = _unique_key()
        results = []
        errors = []

        def worker() -> None:
            try:
                r = should_save(key, 0.0)  # 0 interval → hepsi geçer
                results.append(r)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 20

    def test_concurrent_stats_export(self) -> None:
        """Eş zamanlı istatistik dışa aktarımı tutarlı."""
        key = _unique_key()
        for _ in range(10):
            should_save(key, 0.0)

        errors = []

        def export_worker() -> None:
            try:
                df = export_debounce_metrics_to_polars()
                assert len(df) >= 1
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=export_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
