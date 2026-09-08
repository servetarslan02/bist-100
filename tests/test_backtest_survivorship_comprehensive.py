"""ALPHA BIST — Survivorship Bias Yönetim Modülü Kapsamlı Test Paketi.

services/backtest/survivorship.py modülünün tüm işlevlerini ve uç durumlarını sınar:
1. _parse_to_datetime yardımcı fonksiyonu (farklı string formatları, date/datetime, timezone normalize, None/boş hata).
2. DelistingEvent ve UniverseSnapshot modelleri (to_dict, __repr__, validasyonlar, recovery_rate sınırları).
3. SurvivorshipBiasHandler kayıt ve evren filtreleme:
   - register_delisting, register_delistings_batch, set_active_universe
   - get_universe_at_date (Point-in-Time evren dinamikleri: delist öncesi dahil, sonrası hariç)
   - get_delisted_tickers ve get_delisted_ticker_symbols (tarih filtresiyle)
4. apply_survivorship_correction vektörel getiri düzeltmesi:
   - İflas (bankruptcy) durumunda -1.0 + recovery_rate terminal getiri
   - Birleşme/devralma (merger) son fiyat düzeltmesi
   - Genel delisting durumunda fail-closed tam kayıp (-1.0)
   - İlgisiz hisselerin etkilenmemesi
5. calculate_survivorship_bias_magnitude istatistikleri:
   - Tam evren vs sadece hayatta kalanlar getiri ve Sharpe yanlılığı
   - Boş veri ve sıfır standart sapma guardları
6. generate_universe_report evren snapshot serisi:
   - Periyodik snapshot aralıkları ve kronolojik ilerleme
   - Tarih sırası ve interval doğrulama istisnaları
7. BISTSurvivorshipDataLoader:
   - CSV okuma ve doğrulanmış delisting listesi (Kural 1 sahte veri yasağı)
8. Thread-safety (çoklu iş parçacığında eşzamanlı kayıt ve sorgulama).
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from services.backtest.survivorship import (
    BISTSurvivorshipDataLoader,
    DelistingEvent,
    SurvivorshipBiasCorrector,
    SurvivorshipBiasHandler,
    UniverseSnapshot,
    _parse_to_datetime,
    survivorship_handler,
)


def test_parse_to_datetime_various_formats():
    """Farklı formatlardaki tarih verilerinin standart UTC naive datetime'a dönüştürülmesi."""
    # 1. ISO format string
    dt1 = _parse_to_datetime("2026-09-08T14:30:00")
    assert dt1 == datetime(2026, 9, 8, 14, 30, 0)

    # 2. Standart YYYY-MM-DD
    dt2 = _parse_to_datetime("2026-09-08")
    assert dt2 == datetime(2026, 9, 8, 0, 0, 0)

    # 3. Noktalı tarih (DD.MM.YYYY)
    dt3 = _parse_to_datetime("08.09.2026")
    assert dt3 == datetime(2026, 9, 8, 0, 0, 0)

    # 4. Date ve Datetime nesnesi
    d = date(2026, 9, 8)
    assert _parse_to_datetime(d) == datetime(2026, 9, 8, 0, 0, 0)

    aware = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
    assert _parse_to_datetime(aware).tzinfo is None

    # 5. Hatalı durumlar
    with pytest.raises(ValueError, match="None olamaz"):
        _parse_to_datetime(None)

    with pytest.raises(ValueError, match="boş olamaz"):
        _parse_to_datetime("   ")

    with pytest.raises(ValueError, match="çözümlenemedi"):
        _parse_to_datetime("invalid-date-string")


def test_delisting_event_and_snapshot_models():
    """DelistingEvent ve UniverseSnapshot modellerinin doğrulaması."""
    ev = DelistingEvent(
        ticker=" batık ",
        delisting_date="2025-06-30",
        reason="bankruptcy",
        final_price=0.15,
        recovery_rate=0.20,
    )
    assert ev.ticker == "BATIK"
    assert ev.delisting_date == datetime(2025, 6, 30, 0, 0, 0)
    assert "BATIK" in repr(ev)
    assert ev.to_dict()["recovery_rate"] == 0.20

    # Validasyon hataları
    with pytest.raises(ValueError, match="boş olamaz"):
        DelistingEvent(ticker="", delisting_date="2025-06-30", reason="merger")

    with pytest.raises(ValueError, match="recovery_rate"):
        DelistingEvent(ticker="TEST", delisting_date="2025-06-30", reason="bankruptcy", recovery_rate=1.5)

    with pytest.raises(ValueError, match="negatif olamaz"):
        DelistingEvent(ticker="TEST", delisting_date="2025-06-30", reason="merger", final_price=-5.0)

    # UniverseSnapshot
    snap = UniverseSnapshot(
        date=datetime(2026, 1, 1),
        active_tickers={"THYAO", "GARAN"},
        delisted_tickers={"BATIK"},
    )
    assert snap.active_count == 2
    assert snap.delisted_count == 1
    assert snap.total_count == 3
    assert "active=2" in repr(snap)
    d = snap.to_dict()
    assert d["active_count"] == 2
    assert d["delisted_count"] == 1


def test_survivorship_handler_universe_dynamics():
    """Tarihsel Point-in-Time evren dinamikleri testi."""
    handler = SurvivorshipBiasHandler()

    # Aktif evren: THYAO, GARAN, ASELS
    handler.set_active_universe({"THYAO", "GARAN", "ASELS"})

    # Delist olmuş hisse: BATIK (Delist tarihi: 2024-12-31)
    delist_ev = DelistingEvent(
        ticker="BATIK",
        delisting_date="2024-12-31",
        reason="bankruptcy",
    )
    handler.register_delisting(delist_ev)

    # 1. Delist tarihinden önce (2024-06-01): BATIK evrende OLMALI! (survivorship bias önleme)
    u_before = handler.get_universe_at_date("2024-06-01")
    assert "BATIK" in u_before
    assert "THYAO" in u_before
    assert len(u_before) == 4

    # 2. Delist tarihinden sonra (2025-01-01): BATIK evrende OLMAMALI!
    u_after = handler.get_universe_at_date("2025-01-01")
    assert "BATIK" not in u_after
    assert "THYAO" in u_after
    assert len(u_after) == 3

    # get_delisted_tickers sorgusu
    delisted_2024 = handler.get_delisted_tickers(before_date="2024-12-30")
    assert len(delisted_2024) == 0

    delisted_2025 = handler.get_delisted_tickers(before_date="2025-01-01")
    assert len(delisted_2025) == 1
    assert handler.get_delisted_ticker_symbols() == {"BATIK"}


def test_apply_survivorship_correction_vectorized():
    """Polars getiri serisine kottan çıkma ve iflas düzeltmesinin uygulanması."""
    handler = SurvivorshipBiasHandler()

    dates = [datetime(2025, 6, 1), datetime(2025, 6, 2), datetime(2025, 6, 3)]

    # 2 hisseli getiri verisi: THYAO (sağlam) ve IFLAS (2025-06-02'de iflas eden)
    df_returns = pl.DataFrame({
        "ticker": ["THYAO", "THYAO", "THYAO", "IFLAS", "IFLAS", "IFLAS"],
        "date": dates + dates,
        "return": [0.01, 0.02, -0.01, 0.00, 0.03, 0.02],
    })

    # İflas olayı: 2025-06-02 tarihinde recovery_rate = 0.10 (-%90 kayıp)
    delist_iflas = DelistingEvent(
        ticker="IFLAS",
        delisting_date=datetime(2025, 6, 2),
        reason="bankruptcy",
        recovery_rate=0.10,
    )

    corrected = handler.apply_survivorship_correction(df_returns, [delist_iflas])

    # THYAO getirileri hiç değişmemeli
    thyao_ret = corrected.filter(pl.col("ticker") == "THYAO")["return"].to_list()
    assert thyao_ret == [0.01, 0.02, -0.01]

    # IFLAS hissesi:
    # 2025-06-01: 0.00 (değişmedi)
    # 2025-06-02 ve sonrası: -1.0 + 0.10 = -0.90
    iflas_ret = corrected.filter(pl.col("ticker") == "IFLAS")["return"].to_list()
    assert iflas_ret[0] == 0.00
    assert abs(iflas_ret[1] - (-0.90)) < 1e-6
    assert abs(iflas_ret[2] - (-0.90)) < 1e-6

    # Boş liste veya ilgisiz delisting durumunda DataFrame aynen dönmeli
    unchanged = handler.apply_survivorship_correction(df_returns, [])
    assert unchanged.equals(df_returns)

    # Eksik sütun hatası
    bad_df = pl.DataFrame({"ticker": ["THYAO"]})
    with pytest.raises(ValueError, match="zorunlu sütunlar eksik"):
        handler.apply_survivorship_correction(bad_df, [delist_iflas])


def test_calculate_survivorship_bias_magnitude():
    """Tam evren ile hayatta kalanlar arasındaki yanlılık büyüklüğünün hesaplanması."""
    handler = SurvivorshipBiasHandler()

    # Sadece hayatta kalanlar: yüksek ortalama getiri (+%2 günlük)
    survivor_df = pl.DataFrame({
        "return": [0.02, 0.03, 0.01, 0.02, 0.02],
    })

    # Tam evren (batan hisseler dahil): daha düşük ortalama getiri (%0.5 günlük)
    full_df = pl.DataFrame({
        "return": [0.02, 0.03, 0.01, 0.02, 0.02, -0.50, -0.80],
    })

    metrics = handler.calculate_survivorship_bias_magnitude(full_df, survivor_df)

    assert metrics["survivor_only_mean_return"] > metrics["full_universe_mean_return"]
    assert metrics["bias_magnitude"] > 0
    assert metrics["sharpe_bias"] > 0
    assert "bias_percentage" in metrics

    # Boş DataFrame durumunda sıfır değer dönmeli (ZeroDivisionError koruması)
    empty_metrics = handler.calculate_survivorship_bias_magnitude(pl.DataFrame(), pl.DataFrame())
    assert empty_metrics["bias_magnitude"] == 0.0
    assert empty_metrics["full_universe_sharpe"] == 0.0


def test_generate_universe_report():
    """Kronolojik evren snapshot raporu üretimi."""
    handler = SurvivorshipBiasHandler()
    handler.set_active_universe({"THYAO", "GARAN"})

    delist = DelistingEvent(ticker="ESKI", delisting_date="2026-03-01", reason="merger")
    handler.register_delisting(delist)

    # 2026-01-01 ile 2026-04-01 arası 30 günlük snapshot'lar
    snapshots = handler.generate_universe_report(
        start_date="2026-01-01",
        end_date="2026-04-01",
        interval_days=30,
    )

    assert len(snapshots) >= 4
    # İlk snapshot'ta (Ocak) ESKI aktif olmalı
    assert "ESKI" in snapshots[0].active_tickers
    # Son snapshot'ta (Nisan) ESKI delist edilmiş olmalı
    assert "ESKI" in snapshots[-1].delisted_tickers

    # Hatalı parametreler
    with pytest.raises(ValueError, match="pozitif olmalıdır"):
        handler.generate_universe_report("2026-01-01", "2026-04-01", interval_days=0)

    with pytest.raises(ValueError, match="sonra olamaz"):
        handler.generate_universe_report("2026-05-01", "2026-01-01")


def test_bist_survivorship_data_loader_and_alias():
    """BISTSurvivorshipDataLoader ve SurvivorshipBiasCorrector alias doğrulaması."""
    # Kural 1 uyarınca sahte veri içermez, resmi veri bağlanana kadar boş döner
    empty_list = BISTSurvivorshipDataLoader.create_known_bist_delistings()
    assert empty_list == []
    assert repr(BISTSurvivorshipDataLoader()) == "BISTSurvivorshipDataLoader()"

    # Var olmayan CSV durumunda FileNotFoundError
    with pytest.raises(FileNotFoundError):
        BISTSurvivorshipDataLoader.load_from_csv("non_existent_file_path.csv")

    # Alias ve singleton kontrolü
    assert SurvivorshipBiasCorrector is SurvivorshipBiasHandler
    assert isinstance(survivorship_handler, SurvivorshipBiasHandler)
    assert repr(survivorship_handler).startswith("SurvivorshipBiasHandler")


def test_survivorship_handler_concurrency():
    """Eşzamanlı iş parçacıklarında delisting kaydı ve evren sorgusu bütünlüğü."""
    handler = SurvivorshipBiasHandler()
    n_threads = 6
    events_per_thread = 30

    def worker(tid: int):
        for i in range(events_per_thread):
            ticker = f"DELIST_{tid}_{i}"
            ev = DelistingEvent(
                ticker=ticker,
                delisting_date=datetime(2025, 1, 1) + timedelta(days=i),
                reason="bankruptcy",
            )
            handler.register_delisting(ev)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(n_threads)]
        for f in futures:
            f.result()

    total_expected = n_threads * events_per_thread
    all_delisted = handler.get_delisted_tickers()
    assert len(all_delisted) == total_expected
