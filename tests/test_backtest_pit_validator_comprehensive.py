"""ALPHA BIST — Point-in-Time (PIT) Doğrulayıcı Kapsamlı Test Paketi.

services/backtest/pit_validator.py modülünün tüm işlevlerini ve uç durumlarını sınar:
1. _parse_to_datetime yardımcı fonksiyonu (datetime, date, str ISO, str date, timezone normalize, TypeError).
2. PITRecord, PITViolation, PITValidationReport modelleri (to_dict, __repr__, lag_days, add_violation, sayaçlar).
3. PointInTimeValidator kayıt ve temel veri doğrulama:
   - register_fundamental_data, register_news_event, register_corporate_action
   - get_available_data_at, get_latest_fundamental
   - validate_fundamental_access (bulunamayan veri, yayınlanmamış gelecek veri, revizyon sızıntısı, geçerli erişim)
4. Feature seti doğrulama (validate_feature_set):
   - Boş df uyarısı, eksik timestamp sütunu hatası
   - Gelecek tarihli feature sızıntısı tespiti (critical)
   - NaN / null oranının DEFAULT_MAX_NAN_RATIO eşiğini aşması uyarısı (warning)
5. Etiket üretimi denetimi (validate_label_generation):
   - purge + horizon gereksinimini karşılamayan erken etiket sızıntısı kontrolü
   - negatif gün değeri doğrulama istisnası
6. PITDataAdapter (adapt_fundamental_data, adapt_price_data ile Polars dönüşümü).
7. Thread-safety (çoklu iş parçacığında eşzamanlı kayıt ve istatistik sorgulama).
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from services.backtest.pit_validator import (
    PITDataAdapter,
    PITRecord,
    PITValidationReport,
    PITViolation,
    PointInTimeValidator,
    _parse_to_datetime,
    pit_validator,
)


def test_parse_to_datetime():
    """Farklı girdi türlerinin naive datetime nesnesine dönüştürülmesi."""
    # 1. datetime (naive ve timezone-aware)
    dt_naive = datetime(2026, 9, 8, 10, 30, 0)
    assert _parse_to_datetime(dt_naive) == dt_naive

    dt_aware = datetime(2026, 9, 8, 10, 30, 0, tzinfo=UTC)
    parsed_aware = _parse_to_datetime(dt_aware)
    assert parsed_aware.tzinfo is None

    # 2. date nesnesi
    d = date(2026, 9, 8)
    assert _parse_to_datetime(d) == datetime(2026, 9, 8, 0, 0, 0)

    # 3. String (ISO ve standart YYYY-MM-DD)
    assert _parse_to_datetime("2026-09-08T12:00:00Z") == datetime(2026, 9, 8, 12, 0, 0)
    assert _parse_to_datetime("2026-09-08") == datetime(2026, 9, 8, 0, 0, 0)

    # 4. Geçersiz tip
    with pytest.raises(TypeError, match="Desteklenmeyen tarih tipi"):
        _parse_to_datetime(12345)


def test_pit_record_and_violation_models():
    """PITRecord, PITViolation ve PITValidationReport modellerinin alan ve serileştirme doğrulaması."""
    rep_date = datetime(2026, 3, 31, 0, 0, 0)
    pub_date = datetime(2026, 5, 10, 18, 0, 0)

    rec = PITRecord(
        data_id="THYAO_20260331_v1",
        ticker="THYAO",
        report_date=rep_date,
        publish_date=pub_date,
        data_type="fundamental",
        revision_version=1,
    )

    assert rec.lag_days == 40
    assert "THYAO" in repr(rec)
    d = rec.to_dict()
    assert d["data_id"] == "THYAO_20260331_v1"
    assert d["lag_days"] == 40
    assert d["is_original"] is True

    # Violation
    viol = PITViolation(
        violation_type="future_data",
        severity="critical",
        description="Yayınlanmamış bilanço",
        record=rec,
        decision_time=datetime(2026, 4, 15),
    )
    assert "critical" in repr(viol)
    v_dict = viol.to_dict()
    assert v_dict["type"] == "future_data"
    assert v_dict["record"]["data_id"] == "THYAO_20260331_v1"

    # Validation Report
    report = PITValidationReport()
    assert report.is_valid is True
    report.add_violation(viol)
    assert report.is_valid is False
    assert report.critical_count == 1

    report.add_violation(
        PITViolation(violation_type="timing_error", severity="warning", description="Eksik veri")
    )
    assert report.warning_count == 1
    assert "critical=1" in repr(report)


def test_validator_fundamental_data_and_access():
    """Temel analiz kayıtları, revizyonlar ve karar anı erişim denetimi."""
    val = PointInTimeValidator()
    ticker = "GARAN"
    q1_rep = datetime(2026, 3, 31)
    q1_pub = datetime(2026, 5, 5)

    # 1. Bilanço kaydı oluştur (v1)
    val.register_fundamental_data(ticker, q1_rep, q1_pub, revision_version=1)

    # 2. Henüz yayınlanmamışken karar anı (2026-04-15) -> future_data ihlali
    ok_before, viol_before = val.validate_fundamental_access(
        ticker, q1_rep, revision_version=1, decision_time=datetime(2026, 4, 15)
    )
    assert ok_before is False
    assert viol_before is not None
    assert viol_before.violation_type == "future_data"

    # 3. Yayınlandıktan sonra karar anı (2026-05-06) -> Başarılı
    ok_after, viol_after = val.validate_fundamental_access(
        ticker, q1_rep, revision_version=1, decision_time=datetime(2026, 5, 6)
    )
    assert ok_after is True
    assert viol_after is None

    # 4. Kütükte olmayan veri -> timing_error
    ok_missing, viol_missing = val.validate_fundamental_access(
        ticker, datetime(2025, 12, 31), revision_version=1, decision_time=datetime(2026, 5, 6)
    )
    assert ok_missing is False
    assert viol_missing.violation_type == "timing_error"

    # 5. Revizyon (v2) kaydı ekle (yayın tarihi: 2026-06-01)
    q1_v2_pub = datetime(2026, 6, 1)
    val.register_fundamental_data(ticker, q1_rep, q1_v2_pub, revision_version=2)

    # v2 yayınlanmadan önce v2'ye erişilmek istenirse -> future_data
    ok_v2_early, viol_v2_early = val.validate_fundamental_access(
        ticker, q1_rep, revision_version=2, decision_time=datetime(2026, 5, 15)
    )
    assert ok_v2_early is False
    assert viol_v2_early.violation_type == "future_data"

    # get_latest_fundamental testi
    latest_early = val.get_latest_fundamental(ticker, decision_time=datetime(2026, 5, 20))
    assert latest_early is not None
    assert latest_early.revision_version == 1

    latest_after_v2 = val.get_latest_fundamental(ticker, decision_time=datetime(2026, 6, 2))
    assert latest_after_v2 is not None
    assert latest_after_v2.revision_version == 2


def test_validator_news_and_corporate_actions():
    """Haber/KAP ve temettü/sermaye artırımı kayıtları ve sorgulaması."""
    val = PointInTimeValidator()
    ticker = "ASELS"

    ev_time = datetime(2026, 9, 1, 9, 30, 0)
    sys_time = datetime(2026, 9, 1, 9, 35, 0)

    val.register_news_event(ticker, ev_time, sys_time)

    # Sistem girişinden önce (09:32) henüz mevcut değil
    early_news = val.get_available_data_at(ticker, datetime(2026, 9, 1, 9, 32, 0), data_type="news")
    assert len(early_news) == 0

    # Sistem girişinden sonra (09:36) mevcut
    avail_news = val.get_available_data_at(ticker, datetime(2026, 9, 1, 9, 36, 0), data_type="news")
    assert len(avail_news) == 1

    # Corporate Action kaydı
    val.register_corporate_action(
        ticker=ticker,
        action_type="dividend",
        ex_date=datetime(2026, 10, 1),
        record_date=datetime(2026, 10, 2),
        details={"net_amount": 1.25},
    )
    stats = val.get_registry_stats()
    assert stats["corporate_actions"] == 1
    assert stats["total_tickers"] == 1


def test_validate_feature_set_leakage_and_nan():
    """Polars DataFrame tablosunda feature sızıntısı ve eksik veri (NaN) kontrolleri."""
    val = PointInTimeValidator()
    ticker = "BIMAS"
    decision_time = datetime(2026, 9, 5, 18, 0, 0)

    # 1. Boş dataframe durumu
    empty_df = pl.DataFrame()
    rep_empty = val.validate_feature_set(empty_df, ticker, decision_time, ["rsi"])
    assert rep_empty.is_valid is True
    assert rep_empty.warning_count == 1

    # 2. Timestamp sütunu olmayan dataframe
    no_ts_df = pl.DataFrame({"rsi": [50.0, 55.0]})
    rep_no_ts = val.validate_feature_set(no_ts_df, ticker, decision_time, ["rsi"])
    assert rep_no_ts.is_valid is False
    assert rep_no_ts.critical_count == 1

    # 3. Gelecek veri sızıntısı içeren feature seti
    t1 = datetime(2026, 9, 4, 18, 0, 0)
    t2 = datetime(2026, 9, 5, 18, 0, 0)
    t3 = datetime(2026, 9, 6, 18, 0, 0)  # Karar anından sonra!

    leaked_df = pl.DataFrame({
        "timestamp": [t1, t2, t3],
        "rsi": [45.0, 50.0, 55.0],
    })
    rep_leaked = val.validate_feature_set(leaked_df, ticker, decision_time, ["rsi"])
    assert rep_leaked.is_valid is False
    assert rep_leaked.critical_count == 1
    assert "karar anından sonrasına ait 1 satır saptandı" in rep_leaked.violations[0].description

    # 4. Yüksek NaN oranı uyarısı
    nan_df = pl.DataFrame({
        "timestamp": [t1, t2],
        "beta": [None, None],  # %100 eksik
    })
    rep_nan = val.validate_feature_set(nan_df, ticker, decision_time, ["beta"])
    assert rep_nan.is_valid is True  # Warning kritik sayılmaz, valid kalır
    assert rep_nan.warning_count >= 1
    assert any("eksik/NaN içeriyor" in v.description for v in rep_nan.violations)


def test_validate_label_generation_purge_embargo():
    """Etiket üretiminde purge_days ve label_horizon_days kontrolleri."""
    val = PointInTimeValidator()
    feat_ts = datetime(2026, 9, 1, 18, 0, 0)

    # 1. Erken etiket üretimi (gap=3 gün, purge=2 + horizon=5 = 7 gün gerekli)
    label_ts_early = feat_ts + timedelta(days=3)
    ok_early, viol_early = val.validate_label_generation(
        feature_timestamp=feat_ts,
        label_timestamp=label_ts_early,
        label_horizon_days=5,
        purge_days=2,
    )
    assert ok_early is False
    assert viol_early is not None
    assert "Etiket erken üretildi" in viol_early.description

    # 2. Doğru zamanlama (gap=8 gün >= 7 gün)
    label_ts_safe = feat_ts + timedelta(days=8)
    ok_safe, viol_safe = val.validate_label_generation(
        feature_timestamp=feat_ts,
        label_timestamp=label_ts_safe,
        label_horizon_days=5,
        purge_days=2,
    )
    assert ok_safe is True
    assert viol_safe is None

    # 3. Negatif parametre kontrolü
    with pytest.raises(ValueError, match="negatif olamaz"):
        val.validate_label_generation(feat_ts, label_ts_safe, -1, 5)


def test_pit_data_adapter():
    """PITDataAdapter sınıfının Polars DataFrame dönüşümleri."""
    # 1. Temel veri adaptasyonu
    fund_df = pl.DataFrame({
        "ticker": ["KCHOL", "SAHOL"],
        "report_date": ["2026-03-31", "2026-06-30"],
        "publish_date": ["2026-05-10", "2026-08-15"],
    })
    records = PITDataAdapter.adapt_fundamental_data(fund_df)
    assert len(records) == 2
    assert records[0].ticker == "KCHOL"
    assert records[0].data_type == "fundamental"

    # Eksik sütun hatası
    with pytest.raises(ValueError, match="Zorunlu sütunlar"):
        PITDataAdapter.adapt_fundamental_data(pl.DataFrame({"ticker": ["KCHOL"]}))

    # 2. Fiyat verisi adaptasyonu
    price_df = pl.DataFrame({
        "ticker": ["THYAO", "THYAO"],
        "date": ["2026-09-01", "2026-09-02"],
        "close": [300.0, 305.0],
    })
    price_records = PITDataAdapter.adapt_price_data(price_df)
    assert len(price_records) == 2
    assert price_records[0].data_type == "price"

    # Adapter __repr__
    assert repr(PITDataAdapter()) == "PITDataAdapter()"


def test_validator_concurrency():
    """PointInTimeValidator iş parçacığı güvenliği ve eşzamanlı kayıt."""
    val = PointInTimeValidator()
    n_threads = 6
    n_records_per_thread = 40

    def worker(tid: int):
        for i in range(n_records_per_thread):
            t_name = f"TICKER_{tid}"
            rep_d = datetime(2026, 1, 1) + timedelta(days=i)
            pub_d = rep_d + timedelta(days=30)
            val.register_fundamental_data(t_name, rep_d, pub_d, revision_version=1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(n_threads)]
        for f in futures:
            f.result()

    stats = val.get_registry_stats()
    assert stats["total_tickers"] == n_threads
    assert stats["total_records"] == n_threads * n_records_per_thread
    assert isinstance(pit_validator, PointInTimeValidator)
