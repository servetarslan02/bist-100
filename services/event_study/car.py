"""ALPHA BIST — Cumulative Abnormal Return (CAR).

CAR[t1, t2] = Σ AR_it (t1'den t2'ye)
MacKinlay (1997) metodolojisi.

Sayısal kararlılık notları:
- float64 dtype zorunlu (kümülatif toplamda precision kaybı önler)
- Integer offset zorunlu (float mask hatalı sonuç verir)
- np.isfinite tek traversal NaN/Inf tespiti
"""

import numbers

import numpy as np
import structlog

logger = structlog.get_logger()

# Varsayılan sabitler
MIN_ARRAY_LENGTH: int = 1
DEFAULT_EMPTY_CAR: float = 0.0
ARRAY_DIM: int = 1


def _validate_array(arr: np.ndarray, name: str, min_len: int = MIN_ARRAY_LENGTH) -> None:
    """Array doğrulama — tip, boyut, boşluk, NaN/Inf kontrolü.

    NaN ve Inf tek traversal ile kontrol edilir (np.isfinite).

    Args:
        arr: Doğrulanacak array
        name: Array adı
        min_len: Minimum uzunluk

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş, NaN/Inf içeriyorsa veya yanlış boyuttaysa
    """
    if not isinstance(arr, np.ndarray):
        logger.error("kumulatif_anormal_donuyor_tip_hatasi", beklenti="np.ndarray", gercek=type(arr).__name__, dizi=name)
        raise TypeError(f"{name} numpy array olmalı, gelen tip: {type(arr).__name__}")

    if arr.ndim != ARRAY_DIM:
        logger.error("kumulatif_anormal_donuyor_boyut_hatasi", beklenti=ARRAY_DIM, gercek=arr.ndim, dizi=name)
        raise ValueError(f"{name} tek boyutlu olmalı, gelen boyut: {arr.ndim}")

    if len(arr) < min_len:
        logger.error("kumulatif_anormal_donuyor_bos_dizi", dizi=name, uzunluk=len(arr))
        raise ValueError(f"{name} boş olamaz (minimum {min_len} eleman gerekli).")

    # Tek traversal ile NaN ve Inf kontrolü (sadece numerik dtype'larda)
    if np.issubdtype(arr.dtype, np.number) and not np.all(np.isfinite(arr)):
        has_nan = bool(np.any(np.isnan(arr)))
        has_inf = bool(np.any(np.isinf(arr)))
        logger.error("kumulatif_anormal_donuyor_gecersiz_deger", dizi=name, nan_var=has_nan, inf_var=has_inf)
        raise ValueError(f"{name} dizisinde {'NaN' if has_nan else ''}{' ve ' if has_nan and has_inf else ''}{'Inf' if has_inf else ''} değeri var.")


def _validate_offsets(offsets: np.ndarray, name: str = "day_offsets") -> None:
    """Day offset array doğrulama — integer tip kontrolü.

    Integer array'lerde NaN/Inf olamaz, bu nedenle sadece tip kontrolü yapılır.

    Args:
        offsets: Gün offset dizisi
        name: Array adı

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş veya integer olmayan dtype ise
    """
    if not isinstance(offsets, np.ndarray):
        logger.error("kumulatif_anormal_donuyor_tip_hatasi", beklenti="np.ndarray", gercek=type(offsets).__name__, dizi=name)
        raise TypeError(f"{name} numpy array olmalı, gelen tip: {type(offsets).__name__}")

    if offsets.ndim != ARRAY_DIM:
        logger.error("kumulatif_anormal_donuyor_boyut_hatasi", beklenti=ARRAY_DIM, gercek=offsets.ndim, dizi=name)
        raise ValueError(f"{name} tek boyutlu olmalı, gelen boyut: {offsets.ndim}")

    if len(offsets) < MIN_ARRAY_LENGTH:
        logger.error("kumulatif_anormal_donuyor_bos_dizi", dizi=name, uzunluk=len(offsets))
        raise ValueError(f"{name} boş olamaz.")

    if not np.issubdtype(offsets.dtype, np.integer):
        logger.error("kumulatif_anormal_donuyor_offset_tip_hatasi", dtype=str(offsets.dtype))
        raise ValueError(f"{name} integer dtype olmalı, gelen dtype: {offsets.dtype}")


def _ensure_float64(arr: np.ndarray) -> np.ndarray:
    """Array'i float64'e dönüştür (zaten float64 ise kopyasız döndür).

    Args:
        arr: Dönüştürülecek array

    Returns:
        float64 dtype array
    """
    if arr.dtype == np.float64:
        return arr
    return arr.astype(np.float64, copy=False)


def calculate_car(abnormal_returns: np.ndarray) -> float:
    """CAR = Σ AR (tüm window).

    Kümülatif toplamda float64 dtype zorunlu — büyük array'lerde
    float32 ile kümülatif toplam precision kaybı yapar.

    Args:
        abnormal_returns: Abnormal return dizisi (tek boyutlu numpy array)

    Returns:
        Kümülatif abnormal return değeri (float64)

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş array, NaN/Inf içeriyorsa
    """
    _validate_array(abnormal_returns, "abnormal_returns")
    return float(np.sum(abnormal_returns, dtype=np.float64))


def calculate_car_window(
    abnormal_returns: np.ndarray,
    day_offsets: np.ndarray,
    start_day: int,
    end_day: int,
) -> float:
    """Belirli bir gün aralığı için CAR hesapla.

    Args:
        abnormal_returns: AR dizisi (tek boyutlu numpy array)
        day_offsets: Gün offset dizisi (integer numpy array, ör: [-5, -4, ..., 0, ..., +5])
        start_day: Başlangıç günü (ör: -3)
        end_day: Bitiş günü (ör: +3)

    Returns:
        CAR değeri (float64)

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş array, uzunluk uyuşmazlığı, NaN/Inf, integer offset hatası
    """
    _validate_array(abnormal_returns, "abnormal_returns")
    _validate_offsets(day_offsets, "day_offsets")

    if len(abnormal_returns) != len(day_offsets):
        logger.error(
            "kumulatif_anormal_donuyor_pencere_uzunluk_uyusmazligi",
            ar_uzunluk=len(abnormal_returns),
            offset_uzunluk=len(day_offsets),
        )
        raise ValueError(
            f"AR ve day_offset uzunlukları eşit olmalı: "
            f"ar={len(abnormal_returns)}, offsets={len(day_offsets)}"
        )

    if start_day > end_day:
        logger.error(
            "kumulatif_anormal_donuyor_pencere_siralama_hatasi",
            baslangic=start_day,
            bitis=end_day,
        )
        raise ValueError(f"start_day ({start_day}) end_day'den ({end_day}) büyük olamaz.")

    mask = (day_offsets >= start_day) & (day_offsets <= end_day)
    if not np.any(mask):
        logger.warning("kumulatif_anormal_donuyor_pencere_eslesen_gun_yok", baslangic=start_day, bitis=end_day)
        return DEFAULT_EMPTY_CAR

    return float(np.sum(abnormal_returns[mask], dtype=np.float64))


def calculate_car_sub_windows(
    abnormal_returns: np.ndarray,
    day_offsets: np.ndarray,
) -> dict[str, float]:
    """Alt pencereler için CAR hesapla (pre-event, event-day, post-event).

    Args:
        abnormal_returns: AR dizisi (tek boyutlu numpy array)
        day_offsets: Gün offset dizisi (integer numpy array)

    Returns:
        {"pre_event": car, "event_day": car, "post_event": car, "full": car}

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş array, uzunluk uyuşmazlığı, NaN/Inf, integer offset hatası
    """
    _validate_array(abnormal_returns, "abnormal_returns")
    _validate_offsets(day_offsets, "day_offsets")

    if len(abnormal_returns) != len(day_offsets):
        logger.error(
            "kumulatif_anormal_donuyor_alt_pencere_uzunluk_uyusmazligi",
            ar_uzunluk=len(abnormal_returns),
            offset_uzunluk=len(day_offsets),
        )
        raise ValueError(
            f"AR ve day_offset uzunlukları eşit olmalı: "
            f"ar={len(abnormal_returns)}, offsets={len(day_offsets)}"
        )

    results: dict[str, float] = {}

    # Pre-event: [start, -1]
    mask_pre = day_offsets < 0
    results["pre_event"] = (
        float(np.sum(abnormal_returns[mask_pre], dtype=np.float64)) if np.any(mask_pre) else DEFAULT_EMPTY_CAR
    )

    # Event day: [0, 0]
    mask_event = day_offsets == 0
    results["event_day"] = (
        float(np.sum(abnormal_returns[mask_event], dtype=np.float64)) if np.any(mask_event) else DEFAULT_EMPTY_CAR
    )

    # Post-event: [1, end]
    mask_post = day_offsets > 0
    results["post_event"] = (
        float(np.sum(abnormal_returns[mask_post], dtype=np.float64)) if np.any(mask_post) else DEFAULT_EMPTY_CAR
    )

    # Full window
    results["full"] = calculate_car(abnormal_returns)

    return results


def calculate_car_series(abnormal_returns: np.ndarray) -> np.ndarray:
    """CAR serisi (kümülatif toplam).

    Kümülatif toplamda float64 dtype zorunlu.

    Args:
        abnormal_returns: AR dizisi (tek boyutlu numpy array)

    Returns:
        CAR serisi — her gün için kümülatif AR toplamı (float64 dtype)

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş array veya NaN/Inf içeriyorsa
    """
    _validate_array(abnormal_returns, "abnormal_returns")
    return np.cumsum(abnormal_returns, dtype=np.float64)


def calculate_aar(car_dict: dict[str, float]) -> float:
    """Average Abnormal Return (AAR) — birden fazla event'in ortalaması.

    Args:
        car_dict: {event_id: car_value} sözlüğü (float veya int değerler)

    Returns:
        Ortalama CAR değeri (float64)

    Raises:
        TypeError: Değerler numerik değilse
        ValueError: Sözlük değerlerinde NaN/Inf varsa
    """
    if not car_dict:
        logger.warning("kumulatif_anormal_donuyor_aar_bos_sozluk")
        return DEFAULT_EMPTY_CAR

    values = list(car_dict.values())
    for i, v in enumerate(values):
        # numbers.Number ile numpy scalar dahil tüm numerik tipleri kabul et
        if not isinstance(v, numbers.Number):
            logger.error("kumulatif_anormal_donuyor_aar_tip_hatasi", index=i, tip=type(v).__name__)
            raise TypeError(f"AAR hesaplamasında {i}. değer numerik olmalı, gelen tip: {type(v).__name__}")
        if not np.isfinite(v):
            logger.error("kumulatif_anormal_donuyor_aar_nan_inf", index=i, deger=v)
            raise ValueError(f"AAR hesaplamasında {i}. değer geçersiz: {v}")

    return float(np.mean(values, dtype=np.float64))


def calculate_caar(
    car_dict: dict[str, np.ndarray],
) -> np.ndarray:
    """Cumulative Average Abnormal Return (CAAR).

    Farklı uzunluktaki serileri en kısa olana göre keser ve ortalamasını alır.

    Args:
        car_dict: {event_id: car_series} sözlüğü (numpy array seriler)

    Returns:
        CAAR serisi (float64 dtype)

    Raises:
        TypeError: Değerler numpy array değilse
        ValueError: Sözlük içinde boş array veya NaN/Inf varsa
    """
    if not car_dict:
        logger.warning("kumulatif_anormal_donuyor_caar_bos_sozluk")
        return np.array([], dtype=np.float64)

    series_list = list(car_dict.values())
    series_lengths = [len(s) for s in series_list]

    # Tip ve boşluk kontrolü
    for i, s in enumerate(series_list):
        if not isinstance(s, np.ndarray):
            logger.error("kumulatif_anormal_donuyor_caar_tip_hatasi", index=i, tip=type(s).__name__)
            raise TypeError(f"CAAR hesaplamasında {i}. seri numpy array olmalı, gelen tip: {type(s).__name__}")
        if len(s) < MIN_ARRAY_LENGTH:
            logger.error("kumulatif_anormal_donuyor_caar_bos_seri", index=i)
            raise ValueError(f"CAAR hesaplamasında {i}. seri boş.")
        # Tek traversal ile NaN/Inf kontrolü
        if np.issubdtype(s.dtype, np.number) and not np.all(np.isfinite(s)):
            has_nan = bool(np.any(np.isnan(s)))
            has_inf = bool(np.any(np.isinf(s)))
            logger.error("kumulatif_anormal_donuyor_caar_gecersiz_deger", index=i, nan_var=has_nan, inf_var=has_inf)
            raise ValueError(f"CAAR hesaplamasında {i}. seride {'NaN' if has_nan else ''}{' ve ' if has_nan and has_inf else ''}{'Inf' if has_inf else ''} değeri var.")

    min_len = min(series_lengths)

    # Farklı uzunluk uyarısı
    if len(set(series_lengths)) > 1:
        logger.warning(
            "kumulatif_anormal_donuyor_caar_farkli_uzunluk",
            uzunluklar=series_lengths,
            kisaltilmis=min_len,
        )

    stacked = np.array([_ensure_float64(s[:min_len]) for s in series_list])
    return np.mean(stacked, axis=0)
