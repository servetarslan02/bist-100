"""Olay Çalışması API — KAP ve Makro Olay Analizi (Canlı Veri Akışı)."""

import asyncio
import logging
import math
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import numpy as np
import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.swr_cache import SWRCache
from ..dependencies import check_rate_limit, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Önbellek — 60 saniye TTL
_events_cache = SWRCache(ttl_seconds=60)

# Tanınmış şirket marka ve Türkçe unvan eşleşmeleri
MARKA_ESLESMELERI: dict[str, list[str]] = {
    "THYAO": ["turk hava yollari", "thy"],
    "ASELS": ["aselsan"],
    "TUPRS": ["tupras"],
    "EREGL": ["eregli"],
    "SISE": ["sisecam", "sise cam"],
    "BIMAS": ["bim birlesik", "bim magazalar"],
    "BRSAN": ["borusan"],
    "BOBET": ["bogazici beton", "bobet"],
    "TKFEN": ["tekfen"],
    "ALFAS": ["alfa solar"],
    "ZOREN": ["zorlu enerji"],
    "ASTOR": ["astor enerji"],
    "KONTR": ["kontrolmatik"],
    "EUPWR": ["europower"],
    "GESAN": ["girisim elektrik"],
    "SMRTG": ["smart gunes"],
    "FROTO": ["ford otosan"],
    "TOASO": ["tofas"],
    "CRFSA": ["carrefoursa", "carrefour"],
    "QUICK": ["quick sigorta"],
    "GARAN": ["garanti bbva", "garanti bankasi"],
    "AKBNK": ["akbank"],
    "YKBNK": ["yapi kredi"],
    "ISCTR": ["is bankasi", "isbank"],
    "KCHOL": ["koc holding"],
    "SAHOL": ["sabanci holding"],
    "TCELL": ["turkcell"],
    "TTKOM": ["turk telekom"],
    "PGSUS": ["pegasus"],
    "HEKTS": ["hektas"],
    "SASA": ["sasa polyester"],
    "KOZAL": ["koza altin"],
    "ENJSA": ["enerjisa"],
}

# Hariç tutulacak anahtar kelimeler (ticker eşleşmesinde)
HARIC_TUTULAN_KAP = {"KAP", "BIST", "BISTECH", "DEVRE", "KESICI", "BORSA"}
HARIC_TUTULAN_PARANTEZ = {"KAP", "BIST", "FED", "ECB", "TCMB", "TÜİK", "USD", "EUR", "TRY"}

# Makro anahtar kelimeler
MAKRO_ANAHTAR_KELIMELER = [
    "tcmb", "merkez bankası", "fed", "ecb", "faiz", "enflasyon", "tüik",
    "ppk", "politika faizi", "rezerv", "cari açık", "hazine", "bütçe açığı",
    "döviz kuru", "ihracat", "ithalat", "işsizlik", "istihdam",
    "büyüme oranı", "gdp", "makroekonomi", "küresel piyasa", "wall street",
    "para politikası", "tüketici güveni", "üretici fiyat",
]

# KAP anahtar kelimeler
KAP_ANAHTAR_KELIMELER = [
    "kap", "kamuyu aydınlatma", "bildirimi", "pay alım", "pay satım",
    "sermaye artırımı", "temettü", "genel kurul", "finansal sonuç",
    "bilanço", "özel durum açıklaması", "devre kesici", "borsa istanbul",
]


def _metin_icinde_var_mi(kelime: str, metin: str) -> bool:
    """Kelimenin metin içinde tam kelime olarak geçip geçmediğini kontrol eder."""
    return bool(re.search(r"\b" + re.escape(kelime) + r"\b", metin))


async def _canli_olaylari_getir(ticker: str | None = None) -> list[dict[str, Any]]:
    """Canlı KAP, finans haberleri ve makro takvim verilerini çeker.

    Args:
        ticker: Filtrelenecek hisse sembolü (None ise tümü).

    Returns:
        list: Olay listesi.
    """
    if not ticker:
        cached = _events_cache.get()
        if cached is not None:
            return cached

    events: list[dict[str, Any]] = []
    try:
        from ...ingestion.bist_universe import bist_universe
        from ...ingestion.providers.news_provider import (
            compute_financial_sentiment,
            is_relevant_to_bist_and_macro,
            news_provider,
        )

        tickers_set = set(bist_universe.get_tickers())

        if ticker:
            try:
                news_items = await asyncio.wait_for(
                    news_provider.fetch_news_for_ticker(ticker, max_items=25),
                    timeout=2.5,
                )
            except Exception as exc:
                logger.warning("ticker_haber_hatasi: ticker=%s, hata=%s", ticker, exc)
                news_items = []
        else:
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(
                        news_provider.fetch_official_kap_disclosures(max_items=25),
                        news_provider.fetch_official_tcmb_news(max_items=25),
                        news_provider.fetch_financial_news_rss(max_items=40),
                        return_exceptions=True,
                    ),
                    timeout=3.0,
                )
                news_items = []
                for res in results:
                    if isinstance(res, list):
                        news_items.extend(res)
                    elif isinstance(res, Exception):
                        logger.warning("haber_kaynagi_hatasi: hata=%s", res)
            except Exception as exc:
                logger.warning("toplu_haber_hatasi: hata=%s", exc)
                news_items = []

        # Kronolojik sıralama: en yeniden en eskiye
        news_items.sort(key=lambda x: x.get("published_epoch", 0.0), reverse=True)

        seen_titles: set[str] = set()
        for idx, item in enumerate(news_items, 1):
            title = item.get("title", "").strip()
            summary = item.get("summary", "")

            if not is_relevant_to_bist_and_macro(title, summary):
                continue

            norm_t = title.lower()[:60]
            if not norm_t or norm_t in seen_titles:
                continue
            seen_titles.add(norm_t)

            src = item.get("source", "Finans Akışı")
            src_lower = src.lower()
            if "bloomberght" in src_lower:
                src = "BloombergHT"
            elif "bigpara" in src_lower:
                src = "Bigpara"
            elif "investing" in src_lower:
                src = "Investing.com"
            elif "dunya" in src_lower:
                src = "Dünya Gazetesi"
            elif "trt" in src_lower:
                src = "TRT Finans"

            # Ticker eşleme
            matched = item.get("ticker") or item.get("matched_ticker")
            if not matched and not ticker:
                # KAP yıldız formatı: *** BOBET *** veya (BOBET)
                kap_stars = re.search(r"\*\*\*\s*([A-Z0-9]{3,6})\s*\*\*\*", title)
                if kap_stars:
                    cand = kap_stars.group(1).upper()
                    if cand in tickers_set and cand not in HARIC_TUTULAN_KAP:
                        matched = cand

                if not matched:
                    paren_m = re.search(r"\(([A-Z0-9]{3,6})\)", title)
                    if paren_m:
                        cand = paren_m.group(1).upper()
                        if cand in tickers_set and cand not in HARIC_TUTULAN_PARANTEZ:
                            matched = cand

                # Marka ve Türkçe unvan eşleşmesi
                if not matched:
                    title_norm = (
                        title.lower()
                        .replace("ı", "i")
                        .replace("ğ", "g")
                        .replace("ü", "u")
                        .replace("ş", "s")
                        .replace("ö", "o")
                        .replace("ç", "c")
                    )
                    for sym, aliases in MARKA_ESLESMELERI.items():
                        if any(_metin_icinde_var_mi(alias, title_norm) for alias in aliases):
                            matched = sym
                            break

            sent = item.get("sentiment_score")
            if sent is None:
                sent = compute_financial_sentiment(title, item.get("summary", ""))
            if sent is None:
                sent = 0.0

            pub_epoch = item.get("published_epoch", 0.0)
            if pub_epoch > 0:
                tr_tz = timezone(timedelta(hours=3))
                pub_time = datetime.fromtimestamp(pub_epoch, tz=UTC).astimezone(tr_tz).strftime("%d.%m %H:%M")
            else:
                pub_time = item.get("published") or datetime.now(UTC).strftime("%d.%m %H:%M")

            # Olay tipi belirleme
            event_type = item.get("type")
            if not event_type:
                text_check = f"{title} {item.get('summary', '')} {src}".lower()

                if any(_metin_icinde_var_mi(k, text_check) if " " not in k else k in text_check for k in MAKRO_ANAHTAR_KELIMELER):
                    event_type = "MACRO"
                elif matched or any(_metin_icinde_var_mi(k, text_check) if " " not in k else k in text_check for k in KAP_ANAHTAR_KELIMELER):
                    event_type = "KAP"
                else:
                    event_type = "NEWS"

            events.append(
                {
                    "id": str(idx),
                    "timestamp": pub_time,
                    "epoch": pub_epoch,
                    "type": event_type,
                    "source": src,
                    "title": title,
                    "ticker": matched or ticker,
                    "sentiment": sent,
                    "importance": 0.85 if (matched or event_type in ("KAP", "MACRO")) else 0.65,
                    "link": item.get("link", "#"),
                }
            )

        if not ticker and events:
            _events_cache.set(events)

    except Exception as exc:
        logger.warning("canli_olay_hatasi: hata=%s", exc)

    return events


@router.get("/events")
@router.get("/calendar")
async def event_calendar(
    ticker: str | None = Query(default=None),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Canlı olay akışı ve KAP bildirim takvimini döndürür.

    Args:
        ticker: Filtrelenecek hisse sembolü (None ise tümü).
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: Olay listesi, sayısı ve filtre bilgisi.
    """
    events = await _canli_olaylari_getir(ticker=ticker)
    return {
        "events": events,
        "count": len(events),
        "ticker": ticker,
    }


@router.get("/analyze/{ticker}")
async def event_study(
    ticker: str,
    event_type: str = Query("NEWS"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> dict[str, Any]:
    """Hisse bazlı kümülatif aşırı getiri (CAR/AAR) analizi yapar.

    Args:
        ticker: Hisse sembolü (ör. THYAO).
        event_type: Olay türü (ör. earnings) — raporlama amaçlıdır, hesaplamayı etkilemez.
        user: Kimliği doğrulanmış kullanıcı.

    Returns:
        dict: CAR, t-istatistiği, p-değeri ve istatistiksel anlamlılık.

    Raises:
        HTTPException: Veri alınamazsa veya hesaplama başarısız olursa 503 hatası döner.
    """
    try:
        sym = ticker.upper()
        sym_is = f"{sym}.IS" if not sym.endswith(".IS") else sym

        data = yf.download([sym_is, "XU100.IS"], period="3mo", interval="1d", auto_adjust=True, progress=False)
        if data.empty or "Close" not in data:
            logger.warning("event_study_veri_yok: ticker=%s", ticker)
            raise HTTPException(
                status_code=503,
                detail=f"{ticker} için fiyat verisi alınamadı.",
            )

        close_col = data["Close"]
        if sym_is not in close_col.columns:
            logger.warning("event_study_ticker_bulunamadi: ticker=%s, sembol=%s", ticker, sym_is)
            raise HTTPException(
                status_code=503,
                detail=f"{ticker} için fiyat verisi bulunamadı.",
            )

        stock_close = close_col[sym_is].dropna()
        bm_close = close_col["XU100.IS"].dropna()

        if len(stock_close) < 20 or len(bm_close) < 20:
            logger.warning(
                "event_study_yetersiz_veri: ticker=%s, stock=%d, bm=%d",
                ticker, len(stock_close), len(bm_close),
            )
            raise HTTPException(
                status_code=503,
                detail=f"{ticker} için yeterli veri yok (en az 20 gün gerekli).",
            )

        s_ret = stock_close.pct_change().dropna()
        b_ret = bm_close.pct_change().dropna()

        # Aşırı getiriler
        common_idx = s_ret.index.intersection(b_ret.index)
        excess = s_ret.loc[common_idx] - b_ret.loc[common_idx]

        car_val = float(excess.tail(10).sum())
        t_stat = float(car_val / (excess.std() * np.sqrt(10) + 1e-9))
        p_val = round(float(2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / np.sqrt(2))))), 3)

        return {
            "ticker": sym,
            "event_type": event_type,
            "car_cumulative_abnormal_return": round(car_val, 4),
            "t_statistic": round(t_stat, 2),
            "p_value": p_val,
            "is_statistically_significant": abs(t_stat) >= 1.96,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("event_study_hesaplama_hatasi: ticker=%s, hata=%s", ticker, exc)
        raise HTTPException(
            status_code=503,
            detail=f"{ticker} için CAR analizi yapılamadı: {exc}",
        ) from exc
