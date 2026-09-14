"""Piyasa API — Canlı piyasa verisi, radar, ısı haritası ve enstrüman bilgileri."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog
import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.swr_cache import SWRCache
from ..dependencies import check_rate_limit, get_current_user, get_service_orchestrator

logger = structlog.get_logger(__name__)

router = APIRouter()

# Bilinen şirket meta verileri
BILINEN_SIRKETLER: dict[str, dict[str, Any]] = {
    "THYAO": {"name": "Türk Hava Yolları A.O.", "sector": "Havacılık & Ulaştırma"},
    "ASELS": {"name": "Aselsan Elektronik Sanayi", "sector": "Savunma Sanayi"},
    "GARAN": {"name": "Garanti BBVA", "sector": "Bankacılık"},
    "AKBNK": {"name": "Akbank T.A.Ş.", "sector": "Bankacılık"},
    "ISCTR": {"name": "Türkiye İş Bankası", "sector": "Bankacılık"},
    "YKBNK": {"name": "Yapı ve Kredi Bankası", "sector": "Bankacılık"},
    "KCHOL": {"name": "Koç Holding", "sector": "Holding"},
    "SAHOL": {"name": "Sabancı Holding", "sector": "Holding"},
    "TUPRS": {"name": "Tüpraş Türkiye Petrol Rafinerileri", "sector": "Enerji & Petrol"},
    "EREGL": {"name": "Ereğli Demir ve Çelik Fabrikaları", "sector": "Demir & Çelik"},
    "BIMAS": {"name": "BİM Birleşik Mağazalar", "sector": "Perakende Ticaret"},
    "MGROS": {"name": "Migros Ticaret", "sector": "Perakende Ticaret"},
    "FROTO": {"name": "Ford Otosan", "sector": "Otomotiv"},
    "TOASO": {"name": "Tofaş Türk Otomobil Fabrikası", "sector": "Otomotiv"},
    "PGSUS": {"name": "Pegasus Hava Taşımacılığı", "sector": "Havacılık & Ulaştırma"},
    "SISE": {"name": "Türkiye Şişe ve Cam Fabrikaları", "sector": "Cam & Sanayi"},
    "TCELL": {"name": "Turkcell İletişim Hizmetleri", "sector": "Telekomünikasyon"},
    "TTKOM": {"name": "Türk Telekomünikasyon", "sector": "Telekomünikasyon"},
    "ASTOR": {"name": "Astor Enerji", "sector": "Elektrik & Enerji"},
    "ENJSA": {"name": "Enerjisa Enerji", "sector": "Elektrik & Enerji"},
}

def _sektor_etiketi_belirle(raw_sec: str) -> str:
    """BIST evreninden gelen dinamik sektör kodunu arayüz kategori adına eşler.

    Args:
        raw_sec: Dinamik kaynaklardan gelen ham sektör adı.

    Returns:
        str: Isı haritası standart sektör kategori adı.
    """
    s = (raw_sec or "").upper()
    if any(k in s for k in ["BANKA", "FINANS", "SIGORTA", "FAKTOR"]):
        return "Bankacılık & Finans"
    if "HOLD" in s:
        return "Holding & Yatırım"
    if any(k in s for k in ["HAVA", "ULAS", "LOJISTIK"]):
        return "Havacılık & Ulaştırma"
    if any(k in s for k in ["ENERJ", "PETROL", "GAZ", "ELEKTRIK"]):
        return "Enerji & Petrol Rafineri"
    if any(k in s for k in ["SAVUN", "TEKNO", "YAZIL", "BILISIM"]):
        return "Savunma & Teknoloji"
    if "OTO" in s:
        return "Otomotiv & Yan Sanayi"
    if any(k in s for k in ["GIDA", "PERAKENDE", "ICECEK", "MAGAZA", "TARIM", "TICARET"]):
        return "Perakende, Gıda & İçecek"
    if any(k in s for k in ["GYO", "GAYRIMENKUL", "INSAAT", "KONUT"]):
        return "GYO & Gayrimenkul"
    if any(k in s for k in ["TELEKOM", "ILETISIM"]):
        return "Telekomünikasyon & İletişim"
    if any(k in s for k in ["CIMENTO", "MADEN", "TAS", "TOPRAK"]):
        return "Çimento & Madencilik"
    if any(k in s for k in ["SANAYI", "DEMIR", "CELIK", "CAM", "KIMYA", "TEKSTIL", "METAL"]):
        return "Sanayi & Demir-Çelik"
    return "Diğer Sektörler"



def _hesapla_rsi(closes: list[float], period: int = 14) -> float:
    """RSI hesaplar.

    Args:
        closes: Kapanış fiyatları listesi.
        period: RSI periyodu (varsayılan 14).

    Returns:
        float: RSI değeri.
    """
    if len(closes) < period + 1:
        return 50.0
    arr = np.array(closes)
    deltas = np.diff(arr)
    gains = np.maximum(deltas, 0)
    losses = np.maximum(-deltas, 0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / (avg_loss + 1e-9)
    return round(100 - 100 / (1 + rs), 1)


def _hesapla_sma(closes: list[float], period: int) -> float:
    """Basit hareketli ortalama hesaplar.

    Args:
        closes: Kapanış fiyatları listesi.
        period: SMA periyodu.

    Returns:
        float: SMA değeri.
    """
    if len(closes) < period:
        return round(float(np.mean(closes)), 2) if closes else 0.0
    return round(float(np.mean(closes[-period:])), 2)


def _hesapla_macd(closes: list[float]) -> tuple[float, float, str]:
    """MACD hesaplar.

    Args:
        closes: Kapanış fiyatları listesi.

    Returns:
        tuple: (MACD değeri, sinyal değeri, sinyal açıklaması).
    """
    if len(closes) < 26:
        return 0.0, 0.0, "YETERSIZ_VERI"
    arr = np.array(closes)
    ema12 = float(np.mean(arr[-12:]))
    ema26 = float(np.mean(arr[-26:]))
    macd_val = round(ema12 - ema26, 2)
    sig_val = round(macd_val * 0.8, 2)
    if macd_val > sig_val:
        signal = "POZİTİF KESİŞİM (AL)"
    elif macd_val < sig_val:
        signal = "NEGATİF KESİŞİM (SAT)"
    else:
        signal = "NÖTR"
    return macd_val, sig_val, signal


def _hesapla_oneri(rsi_14: float, latest_price: float, sma_20: float, support: float) -> tuple[str, str, float]:
    """Al/sat/tut önerisi oluşturur.

    Args:
        rsi_14: RSI değeri.
        latest_price: Son fiyat.
        sma_20: 20 günlük SMA.
        support: Destek seviyesi.

    Returns:
        tuple: (İngilizce öneri, Türkçe öneri, skor).
    """
    if rsi_14 < 38 and latest_price >= support:
        return "STRONG_BUY", "GÜÇLÜ AL", round(70 + (38 - rsi_14) * 0.6, 1)
    elif latest_price > sma_20 and rsi_14 < 65:
        return "BUY", "AL", round(55 + (65 - rsi_14) * 0.4, 1)
    elif rsi_14 > 72:
        return "SELL", "SAT", round(50 - (rsi_14 - 72) * 0.5, 1)
    return "HOLD", "TUT", 50.0


# =====================================================
# Uç Noktalar
# =====================================================


async def _get_full_bist_breadth() -> dict[str, Any] | None:
    """TradingView Scanner API üzerinden Borsa İstanbul'daki tüm hisseleri (600+ hisse) tarayarak
    piyasa genişliği (advancing, declining, total, rsi_list) hesaplar.
    Sonuçlar 120 saniye boyunca Redis'te önbelleğe alınır.
    """
    from ...core.redis_helper import get_cached, set_cached

    cache_key = "bist:full:breadth"
    cached = get_cached(cache_key)
    if cached and isinstance(cached, dict) and cached.get("total", 0) > 0:
        return cached

    url = "https://scanner.tradingview.com/turkey/scan"
    payload = {
        "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
        "options": {"lang": "tr"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "change", "close", "RSI"],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "range": [0, 1000],
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                advancing = 0
                declining = 0
                total = 0
                rsi_list: list[float] = []

                for row in data:
                    cols = row.get("d", [])
                    if len(cols) < 4:
                        continue
                    chg = cols[1]
                    rsi = cols[3]

                    if chg is not None:
                        try:
                            chg_val = float(chg)
                            if chg_val > 0.001:
                                advancing += 1
                            elif chg_val < -0.001:
                                declining += 1
                            total += 1
                        except (ValueError, TypeError):
                            pass

                    if rsi is not None:
                        with contextlib.suppress(ValueError, TypeError):
                            rsi_list.append(float(rsi))

                if total > 0:
                    result = {
                        "advancing": advancing,
                        "declining": declining,
                        "total": total,
                        "rsi_list": rsi_list,
                    }
                    set_cached(cache_key, result, ttl=120)
                    return result
    except Exception as exc:
        logger.warning("BIST tam piyasa genisligi tarama hatasi", hata=str(exc))

    return None


@router.get("/state")
async def market_state(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Piyasa durumunu döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Rejim, breadth, advancing/declining, RSI ve risk iştahı.

    Raises:
        HTTPException: Piyasa durumu alınamazsa 500 hatası döner.
    """
    try:
        from ...core.redis_helper import get_cached
        from ...intelligence.regime import regime_engine

        regime = regime_engine.get_current_regime() if hasattr(regime_engine, "get_current_regime") else "UNKNOWN"
        if regime == "UNKNOWN" or not regime:
            regime = "BILINMEYEN"

        advancing = 0
        declining = 0
        total = 0
        rsi_list: list[float] = []

        # 1. Öncelik: Tüm BIST evrenini (600+ hisse) kapsayan tam piyasa genişliği
        full_breadth = await _get_full_bist_breadth()
        if full_breadth:
            advancing = full_breadth["advancing"]
            declining = full_breadth["declining"]
            total = full_breadth["total"]
            rsi_list = full_breadth.get("rsi_list", [])
        else:
            # 2. Öncelik Fallback: Radar verisi (Top 50)
            radar_items = get_cached("radar:data")
            if radar_items and isinstance(radar_items, list) and len(radar_items) > 0:
                for item in radar_items:
                    raw_chg = item.get("change_pct") if item.get("change_pct") is not None else item.get("change", 0.0)
                    try:
                        chg_val = float(raw_chg)
                    except (ValueError, TypeError):
                        chg_val = 0.0

                    if chg_val > 0.001:
                        advancing += 1
                    elif chg_val < -0.001:
                        declining += 1
                    total += 1

                    raw_rsi = item.get("rsi")
                    if raw_rsi is not None:
                        with contextlib.suppress(ValueError, TypeError):
                            rsi_list.append(float(raw_rsi))

        if total == 0:
            raise HTTPException(
                status_code=503,
                detail="Piyasa verisi henüz mevcut değil. Radar verisi bekleniyor.",
            )

        breadth = (advancing / max(total, 1)) * 100.0
        avg_rsi = float(np.mean(rsi_list)) if rsi_list else 50.0
        risk_appetite = round(max(0.1, min(0.95, breadth / 100.0)), 2)

        return {
            "regime": regime,
            "breadth_pct": round(breadth, 1),
            "advancing": advancing,
            "declining": declining,
            "avg_rsi": round(avg_rsi, 1),
            "anomaly_count": 0,
            "risk_appetite": risk_appetite,
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "ok",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("piyasa_durum_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Piyasa durumu alınamadı: {exc}",
        ) from exc


_instruments_cache = SWRCache(ttl_seconds=3600)


@router.get("/instruments")
async def instruments(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Tüm BIST enstrümanlarını döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: BIST-100 ve tüm hisse listeleri.
    """
    cached = _instruments_cache.get()
    if cached is not None:
        return cached
    try:
        from ...ingestion.bist_universe import bist_universe

        result = {
            "bist_100": getattr(bist_universe, "BIST_100_TICKERS", []),
            "all": getattr(bist_universe, "BIST_ALL_TICKERS", []),
            "count": len(getattr(bist_universe, "BIST_ALL_TICKERS", [])),
        }
        _instruments_cache.set(result)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("enstruman_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Enstrün listesi alınamadı: {exc}",
        ) from exc


@router.get("/instruments/{ticker}")
async def instrument_detail(
    ticker: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Enstrüman detayını döndürür.

    Args:
        ticker: Hisse sembolü.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Enstrüman detay bilgisi.
    """
    try:
        await get_service_orchestrator()
        meta = BILINEN_SIRKETLER.get(ticker.upper(), {})
        return {
            "ticker": ticker.upper(),
            "name": meta.get("name", ticker.upper()),
            "sector": meta.get("sector", "Bilinmeyen"),
            "available": True,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("enstruman_detay_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Enstrün detayı alınamadı: {exc}",
        ) from exc


@router.get("/instruments/{ticker}/ohlcv")
async def ohlcv(
    ticker: str,
    period: str = "6mo",
    interval: str = "1d",
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """OHLCV verisini döndürür.

    Args:
        ticker: Hisse sembolü.
        period: Tarihsel dönem (ör. 6mo, 1y).
        interval: Bar aralığı (ör. 1d, 1wk).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: OHLCV veri listesi.

    Raises:
        HTTPException: Veri bulunamazsa 404 hatası döner.
    """
    try:
        from ...data.data_source import data_source

        yf_ticker = f"{ticker}.IS" if not ticker.endswith(".IS") else ticker
        data = data_source.get_stock_data(yf_ticker, period=period, interval=interval)
        if data is None or (hasattr(data, "is_empty") and data.is_empty()) or len(data) == 0:
            raise HTTPException(status_code=404, detail=f"{ticker} için veri bulunamadı.")
        if hasattr(data, "iter_rows"):
            records = [
                {k: (str(v)[:10] if k == "Date" else v) for k, v in row.items()}
                for row in data.tail(100).iter_rows(named=True)
            ]
        elif hasattr(data, "to_dict"):
            records = data.tail(100).to_dict(orient="records")
        else:
            records = list(data.tail(100))
        return {"ticker": ticker, "data": records}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ohlcv_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"OHLCV verisi alınamadı: {exc}",
        ) from exc


@router.get("/instruments/{ticker}/live_intel")
@router.get("/instruments/{ticker}/full")
async def live_intel_analysis(
    ticker: str,
    period: str = Query("6mo", description="Tarihsel dönem: 1mo, 3mo, 6mo, 1y, 2y, 5y"),
    interval: str = Query("1d", description="Bar aralığı: 1d, 1wk, 1mo"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Gerçek zamanlı piyasa verisi ve teknik indikatörleri döndürür.

    Args:
        ticker: Hisse sembolü.
        period: Tarihsel dönem.
        interval: Bar aralığı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Fiyat, teknik indikatörler, mum grafikleri ve formasyonlar.

    Raises:
        HTTPException: Veri alınamazsa hata döner.
    """
    sym = ticker.upper().replace(".IS", "").strip()
    yf_ticker = f"{sym}.IS"
    meta = BILINEN_SIRKETLER.get(sym, {"name": f"{sym} Şirket Grubu", "sector": "BIST Sanayi & Ticaret"})

    try:
        import polars as pl

        from ...data.data_source import data_source

        raw_chart = data_source.get_stock_data(yf_ticker, period=period, interval=interval)
        if period == "6mo" and interval == "1d":
            raw_daily = raw_chart
        else:
            raw_daily = data_source.get_stock_data(yf_ticker, period="6mo", interval="1d")

        def _clean_polars_df(d: Any) -> pl.DataFrame | None:
            """Veri kaynağını standardize edilmiş Polars DataFrame'e dönüştürür."""
            if d is None:
                return None
            if hasattr(d, "to_pandas") and not isinstance(d, pl.DataFrame):
                try:
                    d = pl.from_pandas(d)
                except Exception as e:
                    logger.debug("from_pandas_failed", error=str(e))
            if isinstance(d, pl.DataFrame) and not d.is_empty():
                if "Date" in d.columns:
                    d = d.sort("Date")
                return d
            return None

        df_chart = _clean_polars_df(raw_chart)
        df = _clean_polars_df(raw_daily)

        if df is None or df.is_empty() or len(df) < 2:
            try:
                # Önbellek baypas edilerek doğrudan canlı Yahoo Finance kaynağından çekmeyi dene
                fallback_chart = data_source.get_stock_data(
                    yf_ticker, period=period, interval=interval, source_priority=["yahoo", "bist"]
                )
                if fallback_chart is not None and not fallback_chart.is_empty():
                    df_chart = _clean_polars_df(fallback_chart)
                if period == "6mo" and interval == "1d":
                    df = df_chart
                else:
                    fallback_daily = data_source.get_stock_data(
                        yf_ticker, period="6mo", interval="1d", source_priority=["yahoo", "bist"]
                    )
                    if fallback_daily is not None and not fallback_daily.is_empty():
                        df = _clean_polars_df(fallback_daily)
            except Exception as e:
                logger.debug("canli_kaynak_fallback_hatasi", hisse=ticker, hata=str(e))

        if df is None or df.is_empty() or len(df) < 2:
            df = df_chart

        if df is None or df.is_empty() or len(df) < 1:
            raise HTTPException(
                status_code=404,
                detail=f"{ticker} sembolü için piyasa fiyat verisi bulunamadı.",
            )

        df = df.drop_nulls(subset=["Close", "Open", "High", "Low"])
        if df.is_empty():
            raise HTTPException(
                status_code=404,
                detail=f"{ticker} için geçerli fiyat verisi yok.",
            )

        closes_list = [float(c) for c in df["Close"].to_list()]
        latest_price = round(closes_list[-1], 2)
        prev_price = round(closes_list[-2], 2) if len(closes_list) >= 2 else latest_price
        raw_change_pct = round(float(((latest_price - prev_price) / prev_price) * 100), 2) if (prev_price and prev_price > 0) else 0.0
        change_pct = max(-10.0, min(10.0, raw_change_pct))

        # Redis canlı tick senkronizasyonu
        try:
            from ...core.redis_helper import get_cached

            radar_items = get_cached("radar:data") or []
            live_item = next((x for x in radar_items if x.get("symbol") == sym), None)
            if live_item and live_item.get("price") and float(live_item.get("price")) > 0:
                latest_price = round(float(live_item["price"]), 2)
                if "change" in live_item:
                    change_pct = max(-10.0, min(10.0, round(float(live_item["change"]), 2)))
        except Exception as exc:
            logger.warning("canli_tick_hatasi: ticker=%s, hata=%s", sym, exc)

        rsi_14 = _hesapla_rsi(closes_list)
        sma_20 = _hesapla_sma(closes_list, 20)
        sma_50 = _hesapla_sma(closes_list, 50)

        # Destek & Direnç: Klasik Floor Pivot S1 & R1 hesaplaması (günlük tradable seviyeler)
        last_high = float(df["High"][-1]) if len(df) >= 1 else latest_price
        last_low = float(df["Low"][-1]) if len(df) >= 1 else latest_price
        last_close = float(df["Close"][-1]) if len(df) >= 1 else latest_price
        pivot = (last_high + last_low + last_close) / 3.0
        pivot_r1 = round(2.0 * pivot - last_low, 2)
        pivot_s1 = round(2.0 * pivot - last_high, 2)

        # Son 10 günlük swing low / swing high desteği ile harmanla
        lows_10 = [float(x) for x in df["Low"].tail(10).to_list()]
        highs_10 = [float(x) for x in df["High"].tail(10).to_list()]
        swing_support = round(min(lows_10), 2) if lows_10 else latest_price
        swing_resistance = round(max(highs_10), 2) if highs_10 else latest_price

        support = pivot_s1 if pivot_s1 < latest_price else swing_support
        resistance = pivot_r1 if pivot_r1 > latest_price else swing_resistance
        if support >= latest_price:
            support = round(latest_price * 0.96, 2)
        if resistance <= latest_price:
            resistance = round(latest_price * 1.04, 2)

        highs_14 = df["High"].tail(14)
        lows_14 = df["Low"].tail(14)
        atr_14 = round(float((highs_14 - lows_14).mean() or 0.0), 2)

        macd_val, sig_val, macd_signal = _hesapla_macd(closes_list)
        recommendation, rec_text, rec_score = _hesapla_oneri(rsi_14, latest_price, sma_20, support)

        # Temel Analiz ve Finansal Rasyolar (F/K, PD/DD, Piyasa Değeri)
        pe_ratio: float | None = None
        pb_ratio: float | None = None
        market_cap_str: str = "—"
        try:
            from ...ingestion.providers.fundamental_provider import FundamentalProvider

            fund_prov = FundamentalProvider()
            fund_data = await fund_prov.fetch_fundamentals(sym)
            if fund_data:
                pe_ratio = round(float(fund_data["pe_ratio"]), 2) if fund_data.get("pe_ratio") is not None else None
                pb_ratio = round(float(fund_data["pb_ratio"]), 2) if fund_data.get("pb_ratio") is not None else None
                mcap = fund_data.get("market_cap")
                if mcap and float(mcap) > 0:
                    val = float(mcap)
                    if val >= 1_000_000_000:
                        market_cap_str = f"₺{val / 1_000_000_000:.1f} Mr"
                    elif val >= 1_000_000:
                        market_cap_str = f"₺{val / 1_000_000:.1f} Mn"
                    else:
                        market_cap_str = f"₺{val:,.0f}"
        except Exception as f_err:
            logger.warning("fundamental_fetch_uyari: sym=%s, hata=%s", sym, f_err)

        # Mum grafikleri
        target_df = df_chart if df_chart is not None and not df_chart.is_empty() else df
        candles: list[dict[str, Any]] = []
        if target_df is not None and not target_df.is_empty():
            sorted_clean_df = target_df.drop_nulls(subset=["Open", "High", "Low", "Close"])
            if "Date" in sorted_clean_df.columns:
                sorted_clean_df = sorted_clean_df.sort("Date")
            for row in sorted_clean_df.tail(120).iter_rows(named=True):
                dt_val = row.get("Date")
                date_str = str(dt_val)[:10] if dt_val is not None else ""
                candles.append(
                    {
                        "time": date_str,
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "close": round(float(row["Close"]), 2),
                        "volume": int(row.get("Volume") or 100000),
                    }
                )

        # Mum formasyonları
        from ...intelligence.candle_patterns import candle_engine

        candle_res = candle_engine.analyze_dataframe(df, sym)

        return {
            "symbol": sym,
            "name": meta.get("name", sym),
            "sector": meta.get("sector", "GENEL"),
            "price": latest_price,
            "prev_price": prev_price,
            "change_pct": change_pct,
            "market_cap": market_cap_str,
            "pe_ratio": pe_ratio,
            "pb_ratio": pb_ratio,
            "rsi_14": rsi_14,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "support": support,
            "resistance": resistance,
            "atr_14": atr_14,
            "macd_val": macd_val,
            "macd_sig_val": sig_val,
            "macd_signal": macd_signal,
            "recommendation": recommendation,
            "recommendation_text": rec_text,
            "recommendation_score": rec_score,
            "candles": candles,
            "candle_patterns": candle_res.patterns_detected,
            "primary_pattern": candle_res.primary_pattern,
            "buyer_pressure_pct": candle_res.buyer_pressure_pct,
            "seller_pressure_pct": candle_res.seller_pressure_pct,
            "has_fvg": candle_res.has_fvg,
            "fvg_type": candle_res.fvg_type,
            "fvg_gap_range": list(candle_res.fvg_gap_range),
            "candle_evidence": candle_res.evidence,
            "is_real_data": True,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("live_intel_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Canlı analiz yapılamadı: {exc}",
        ) from exc


@router.get("/instruments/{ticker}/features")
async def features(
    ticker: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Enstrüman feature'larını döndürür.

    Args:
        ticker: Hisse sembolü.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Feature verisi.

    Raises:
        HTTPException: Feature verisi alınamazsa hata döner.
    """
    try:
        from ...intelligence.factor_engine import FactorEngine

        engine = FactorEngine()
        result = engine.get_features(ticker) if hasattr(engine, "get_features") else {}
        if result:
            return {"ticker": ticker, "features_available": True, "features": result}
        raise HTTPException(
            status_code=404,
            detail=f"{ticker} için feature verisi bulunamadı.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("feature_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Feature verisi alınamadı: {exc}",
        ) from exc


@router.get("/sectors")
async def sectors(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Sektör listesini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sektör listesi ve sayısı.
    """
    try:
        from ...ingestion.bist_universe import bist_universe

        sector_map = bist_universe.SECTOR_MAP
        unique_sectors = sorted(set(sector_map.values()))
        return {"sectors": unique_sectors, "count": len(unique_sectors)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("sektor_hatasi: hata=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Sektör listesi alınamadı: {exc}",
        ) from exc


@router.get("/calendar")
async def calendar(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """İşlem takvimi bilgisini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Piyasa açılış/kapanış saatleri ve saat dilimi.
    """
    return {"market_open": "09:40", "market_close": "18:00", "timezone": "Europe/Istanbul"}


@router.get("/events")
async def events(
    limit: int = Query(20, le=100),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Piyasa olaylarını döndürür.

    Args:
        limit: Maksimum olay sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Olay listesi ve sayısı.
    """
    try:
        from ...scanner.event_scanner import EventScanner

        scanner = EventScanner()
        pending = scanner.get_pending_rescans()
        return {"events": pending[:limit], "count": len(pending)}
    except Exception as exc:
        logger.error("olay_hatasi: hata=%s", exc)
        return {"events": [], "error": str(exc)}


@router.get("/radar")
async def market_radar(
    limit: int = Query(1000, le=1000),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Piyasa radarını döndürür — Redis cache'den anında döner.

    Args:
        limit: Maksimum hisse sayısı.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Radar verisi, sayısı ve durum bilgisi.
    """
    from ...core.redis_helper import get_cached

    # 1. Öncelik: Tam BIST piyasa radarı (600+ hisse)
    try:
        all_cached = get_cached("radar:market:all")
        if all_cached and isinstance(all_cached, list) and len(all_cached) > 50:
            cached_at_raw = get_cached("radar:market:updated_at")
            return {
                "data": all_cached[:limit],
                "count": len(all_cached),
                "errors": 0,
                "status": "ok",
                "cached_at": cached_at_raw,
                "from_cache": True,
            }
    except Exception as exc:
        logger.warning("radar_market_all_okuma_hatasi: hata=%s", exc)

    # 2. Canlı tarama dene (TradingView 649 hisse)
    fresh_res = await _fetch_radar_fresh(limit)
    if fresh_res.get("data") and len(fresh_res["data"]) > 0:
        return fresh_res

    # 3. Fallback: ML radar listesi (Top 50) normalize edilerek
    try:
        cached = get_cached("radar:data")
        if cached and isinstance(cached, list) and len(cached) > 0:
            normalized: list[dict[str, Any]] = []
            for item in cached:
                sym = item.get("symbol") or item.get("ticker", "BIST")
                price = float(item.get("price", 0.0))
                chg = float(item.get("change") if item.get("change") is not None else item.get("change_pct", 0.0))
                vol_ratio = float(item.get("volume_ratio", 1.0))
                vol = int(item.get("volume") if item.get("volume") is not None else round(vol_ratio * 1_000_000))
                high = float(item.get("high") if item.get("high") is not None else item.get("target_price", price * 1.02))
                low = float(item.get("low") if item.get("low") is not None else item.get("stop_loss", price * 0.98))
                rsi = float(item.get("rsi", 50.0)) if item.get("rsi") is not None else 50.0
                score = int(round(float(item.get("score", 50.0))))
                is_b100 = bool(item.get("isBist100") or item.get("is_bist100", False))
                normalized.append({
                    "symbol": sym,
                    "name": item.get("name", sym),
                    "price": price,
                    "change": chg,
                    "volume": vol,
                    "high": high,
                    "low": low,
                    "rsi": rsi,
                    "score": score,
                    "isBist100": is_b100,
                })

            return {
                "data": normalized[:limit],
                "count": len(normalized),
                "errors": 0,
                "status": "ok",
                "cached_at": None,
                "from_cache": True,
            }
    except Exception as exc:
        logger.warning("radar_fallback_okuma_hatasi: hata=%s", exc)

    return fresh_res


async def _fetch_radar_fresh(limit: int = 1000) -> dict[str, Any]:
    """Canlı TradingView ve yfinance ile TÜM BIST hisselerini çeker.

    Args:
        limit: Maksimum hisse sayısı.

    Returns:
        dict: Radar verisi ve durum bilgisi.
    """
    from concurrent.futures import ThreadPoolExecutor

    from ...ingestion.bist_universe import bist_universe

    bist100 = set(bist_universe.BIST_100_TICKERS)
    all_tickers = bist_universe.BIST_ALL_TICKERS
    tickers_to_fetch = all_tickers[:limit] if limit else all_tickers

    def _fetch_tradingview_live() -> list[dict[str, Any]] | None:
        """TradingView Turkey Scanner API üzerinden canlı veri çeker."""
        url = "https://scanner.tradingview.com/turkey/scan"
        payload = {
            "filter": [],
            "options": {"lang": "tr"},
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": [
                "name",
                "description",
                "close",
                "change",
                "change_abs",
                "volume",
                "high",
                "low",
                "open",
                "RSI",
                "Recommend.All",
            ],
            "sort": {"sortBy": "volume", "sortOrder": "desc"},
            "range": [0, 650],
        }
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            import httpx

            with httpx.Client(timeout=2.0) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                rows = data.get("data", [])
                results: list[dict[str, Any]] = []
                universe = bist_universe._updater.get_universe()

                for item in rows:
                    raw_sym = item.get("s", "")
                    pos_ticker = raw_sym.split(":")[-1].upper()
                    d = item.get("d", [])
                    if len(d) < 10:
                        continue
                    name = d[0] or pos_ticker
                    close = float(d[2]) if d[2] is not None else 0.0
                    change_pct = round(float(d[3]), 2) if d[3] is not None else 0.0
                    # BIST günlük marj sınırı koruması (bedelsiz/split veri sapmalarını filtrele)
                    if change_pct < -10.0:
                        change_pct = -10.0
                    elif change_pct > 10.0:
                        change_pct = 10.0
                    vol = int(d[5]) if d[5] is not None else 0
                    high = float(d[6]) if d[6] is not None else close
                    low = float(d[7]) if d[7] is not None else close
                    rsi = round(float(d[9]), 1) if d[9] is not None else 50.0
                    rec_score = float(d[10]) if len(d) > 10 and d[10] is not None else 0.0

                    norm_rsi_score = 80 if 40 <= rsi <= 65 else (90 if rsi < 30 else 40)
                    mom_score = min(100, max(0, 50 + change_pct * 5))
                    tech_score = int(min(100, max(0, 50 + rec_score * 50)))
                    score = int(round(tech_score * 0.4 + norm_rsi_score * 0.3 + mom_score * 0.3))

                    if pos_ticker in universe:
                        universe[pos_ticker].last_price = close

                    results.append(
                        {
                            "symbol": pos_ticker,
                            "name": name,
                            "price": close,
                            "change": change_pct,
                            "volume": vol,
                            "high": high,
                            "low": low,
                            "rsi": rsi,
                            "score": score,
                            "isBist100": pos_ticker in bist100,
                        }
                    )

                if len(results) > 50:
                    logger.info("tradinglive_tarama_basarili: adet=%d", len(results))
                    return results
        except Exception as exc:
            logger.warning("tradingview_tarama_hatasi: hata=%s", exc)
        return None

    def _batch_fetch() -> list[dict[str, Any]]:
        """TradingView veya yfinance ile toplu hisse verisi çeker.

        Returns:
            list: Hisse verisi listesi.
        """
        tv_results = _fetch_tradingview_live()
        if tv_results:
            return tv_results

        results: list[dict[str, Any]] = []
        chunk_size = 70
        chunks = [tickers_to_fetch[i : i + chunk_size] for i in range(0, len(tickers_to_fetch), chunk_size)]

        for chunk in chunks:
            yf_tickers = [f"{t}.IS" for t in chunk]
            try:
                raw = yf.download(
                    tickers=" ".join(yf_tickers),
                    period="5d",
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
                for pos_ticker, yf_ticker in zip(chunk, yf_tickers, strict=False):
                    try:
                        df = (
                            raw
                            if len(chunk) == 1
                            else (raw[yf_ticker] if yf_ticker in raw.columns.get_level_values(0) else None)
                        )
                        if df is None or df.empty or len(df) < 2:
                            continue
                        closes = df["Close"].dropna().tolist()
                        if len(closes) < 2:
                            continue
                        last_close = float(closes[-1])
                        prev_close = float(closes[-2])
                        change_pct = round((last_close - prev_close) / prev_close * 100, 2) if prev_close else 0.0
                        volume_clean = df["Volume"].dropna() if "Volume" in df.columns else None
                        volume = (
                            float(volume_clean.iloc[-1])
                            if volume_clean is not None and not volume_clean.empty
                            else 100000.0
                        )

                        high_clean = df["High"].dropna() if "High" in df.columns else None
                        high = (
                            float(high_clean.iloc[-1])
                            if high_clean is not None and not high_clean.empty
                            else last_close * 1.02
                        )

                        low_clean = df["Low"].dropna() if "Low" in df.columns else None
                        low = (
                            float(low_clean.iloc[-1])
                            if low_clean is not None and not low_clean.empty
                            else last_close * 0.98
                        )

                        rsi = _hesapla_rsi(closes)
                        ma20 = _hesapla_sma(closes, 20)
                        trend_score = 65 if last_close > ma20 else 45
                        rsi_score = 80 if (rsi and 40 < rsi < 65) else 50
                        mom_score = min(100, max(0, 50 + change_pct * 5))
                        score = round(trend_score * 0.4 + rsi_score * 0.3 + mom_score * 0.3)
                        results.append(
                            {
                                "symbol": str(pos_ticker),
                                "price": float(round(last_close, 2)),
                                "change": float(change_pct),
                                "volume": int(volume) if not np.isnan(volume) else 100000,
                                "high": float(round(high, 2))
                                if not np.isnan(high)
                                else float(round(last_close * 1.02, 2)),
                                "low": float(round(low, 2))
                                if not np.isnan(low)
                                else float(round(last_close * 0.98, 2)),
                                "rsi": float(rsi),
                                "score": int(score),
                                "isBist100": bool(pos_ticker in bist100),
                            }
                        )
                    except Exception as exc:
                        logger.debug("hisse_isleme_hatasi: ticker=%s, hata=%s", pos_ticker, exc)
                        continue
            except Exception as exc:
                logger.warning("batch_indirme_hatasi: hata=%s", exc)

        return results

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = await loop.run_in_executor(executor, _batch_fetch)

    results.sort(key=lambda x: x["score"], reverse=True)

    try:
        from ...core.redis_helper import set_cached

        now_iso = datetime.now(UTC).isoformat()
        set_cached("radar:market:all", results, ttl=180)
        set_cached("radar:market:updated_at", now_iso, ttl=180)
        set_cached("radar:data", results, ttl=180)
        set_cached("radar:updated_at", now_iso, ttl=180)
    except Exception as exc:
        logger.warning("radar_cache_yazma_hatasi: hata=%s", exc)

    return {
        "data": results,
        "count": len(results),
        "errors": 0,
        "status": "ok",
        "from_cache": False,
    }


@router.get("/regime")
async def regime(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Piyasa rejimini döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Piyasa rejimi bilgisi.
    """
    try:
        from ...intelligence.regime import regime_engine

        r = regime_engine.get_current_regime() if hasattr(regime_engine, "get_current_regime") else "UNKNOWN"
        return {"regime": r}
    except Exception as exc:
        logger.error("rejim_hatasi: hata=%s", exc)
        return {"regime": "UNKNOWN", "error": str(exc)}


_heatmap_cache = SWRCache(ttl_seconds=30)


@router.get("/heatmap")
async def market_heatmap(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """BIST-100 dinamik canlı sektör ısı haritasını döndürür.

    Args:
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Sektör bazlı ısı haritası verisi.
    """
    cached = _heatmap_cache.get()
    if cached is not None:
        return cached

    from ...core.redis_helper import get_cached
    from ...ingestion.bist_universe import bist_universe

    # 1. Öncelik: Tam BIST piyasa radarı (600+ hisse)
    stock_items = get_cached("radar:market:all")
    if not stock_items or not isinstance(stock_items, list) or len(stock_items) < 50:
        stock_items = get_cached("radar:data")

    # 2. Önbellek boşsa anlık taze tarama yap
    if not stock_items or not isinstance(stock_items, list) or len(stock_items) == 0:
        fresh = await _fetch_radar_fresh(1000)
        stock_items = fresh.get("data", [])

    if not stock_items:
        return {
            "status": "unavailable",
            "sectors": [],
            "message": "Canlı veri bekleniyor veya altyapı güncelleniyor.",
        }

    SEKTOR_AGIRLIK: dict[str, float] = {
        "Bankacılık & Finans": 22.5,
        "Holding & Yatırım": 18.0,
        "Havacılık & Ulaştırma": 14.5,
        "Enerji & Petrol Rafineri": 12.5,
        "Sanayi & Demir-Çelik": 11.0,
        "Savunma & Teknoloji": 8.5,
        "Otomotiv & Yan Sanayi": 7.0,
        "Perakende, Gıda & İçecek": 6.5,
        "GYO & Gayrimenkul": 4.5,
        "Telekomünikasyon & İletişim": 4.0,
        "Çimento & Madencilik": 3.5,
        "Diğer Sektörler": 2.5,
    }

    sec_map_raw = getattr(bist_universe, "SECTOR_MAP", {})
    sector_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    total_market_volume_val = 0

    for item in stock_items:
        sym = item.get("symbol") or item.get("ticker", "")
        if not sym:
            continue

        raw_sec = sec_map_raw.get(sym, item.get("sector", "DIGER"))
        sec_name = _sektor_etiketi_belirle(raw_sec)

        # Alan normalizasyonu
        price = float(item.get("price", 0.0))
        raw_chg = float(item.get("change") if item.get("change") is not None else item.get("change_pct", 0.0))
        chg = max(-10.0, min(10.0, raw_chg))
        vol = int(item.get("volume") if item.get("volume") is not None else round(float(item.get("volume_ratio", 1.0)) * 1_000_000))
        score = int(round(float(item.get("score", 50.0))))

        total_market_volume_val += vol

        sector_groups[sec_name].append({
            "symbol": sym,
            "name": item.get("name", sym),
            "price": price,
            "change": chg,
            "volume": vol,
            "score": score,
        })

    sectors: list[dict[str, Any]] = []
    for sec_name, weight in SEKTOR_AGIRLIK.items():
        items = sector_groups.get(sec_name, [])
        if not items:
            continue

        total_vol = sum(it.get("volume", 0) for it in items)
        raw_avg = float(np.mean([it.get("change", 0.0) for it in items])) if items else 0.0
        avg_chg = round(max(-10.0, min(10.0, raw_avg)), 2)

        stock_list: list[dict[str, Any]] = []
        for it in sorted(items, key=lambda x: x.get("volume", 0), reverse=True)[:16]:
            vol_val = it.get("volume", 0)
            vol_str = f"{(vol_val / 1000000):.1f}M ₺" if vol_val >= 1000000 else f"{(vol_val / 1000):.0f}K ₺"
            stock_list.append(
                {
                    "symbol": it.get("symbol"),
                    "name": it.get("name", it.get("symbol")),
                    "price": round(float(it.get("price", 0.0)), 2),
                    "change_pct": round(max(-10.0, min(10.0, float(it.get("change", 0.0)))), 2),
                    "volume": vol_str,
                    "score": it.get("score", 50),
                }
            )

        vol_total_str = (
            f"{(total_vol / 1000000000):.1f} Milyar ₺"
            if total_vol >= 1000000000
            else f"{(total_vol / 1000000):.0f} Milyon ₺"
        )
        sectors.append(
            {
                "name": sec_name,
                "weight": weight,
                "change_pct": avg_chg,
                "volume_total": vol_total_str,
                "stocks": stock_list,
            }
        )

    total_market_vol_str = (
        f"{(total_market_volume_val / 1000000000):.1f} Milyar ₺"
        if total_market_volume_val >= 1000000000
        else f"{(total_market_volume_val / 1000000):.0f} Milyon ₺"
    )

    top_sec = max(sectors, key=lambda s: s.get("change_pct", -999)) if sectors else None

    res: dict[str, Any] = {
        "status": "ok",
        "sectors": sectors,
        "total_volume": total_market_vol_str,
        "total_stocks": len(stock_items),
        "top_sector": top_sec.get("name") if top_sec else "Genel Piyasa",
        "top_sector_chg": top_sec.get("change_pct", 0.0) if top_sec else 0.0,
        "advancing_sectors": sum(1 for s in sectors if s.get("change_pct", 0) > 0),
        "declining_sectors": sum(1 for s in sectors if s.get("change_pct", 0) < 0),
    }
    _heatmap_cache.set(res)
    return res
