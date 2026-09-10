"""ALPHA BIST — Abnormal Return.

AR = R_actual - E[R_expected]
MacKinlay (1997) metodolojisi ile abnormal return hesaplama.
"""

import numpy as np
import structlog

logger = structlog.get_logger()

# Varsayılan sabitler
DEFAULT_ALPHA: float = 0.0
DEFAULT_BETA_MARKET: float = 1.0
DEFAULT_BETA_FACTOR: float = 0.0
MIN_ARRAY_LENGTH: int = 1
EXPECTED_DTYPE: type = np.floating
ARRAY_DIM: int = 1


def _validate_array(arr: np.ndarray, name: str, min_len: int = MIN_ARRAY_LENGTH) -> None:
    """Array doğrulama — tip, boyut, boşluk, NaN/Inf kontrolü.

    Args:
        arr: Doğrulanacak array
        name: Array adı (hata mesajlarında kullanılır)
        min_len: Minimum uzunluk

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş, NaN/Inf içeriyorsa veya yanlış boyuttaysa
    """
    if not isinstance(arr, np.ndarray):
        logger.error("anormal_donuyor_tip_hatasi", beklenti="np.ndarray", gercek=type(arr).__name__, dizi=name)
        raise TypeError(f"{name} numpy array olmalı, gelen tip: {type(arr).__name__}")

    if arr.ndim != ARRAY_DIM:
        logger.error("anormal_donuyor_boyut_hatasi", beklenti=ARRAY_DIM, gercek=arr.ndim, dizi=name)
        raise ValueError(f"{name} tek boyutlu olmalı, gelen boyut: {arr.ndim}")

    if len(arr) < min_len:
        logger.error("anormal_donuyor_bos_dizi", dizi=name, uzunluk=len(arr))
        raise ValueError(f"{name} boş olamaz (minimum {min_len} eleman gerekli).")

    if np.any(np.isnan(arr)):
        logger.error("anormal_donuyor_nan_var", dizi=name)
        raise ValueError(f"{name} dizisinde NaN değeri var.")
    if np.any(np.isinf(arr)):
        logger.error("anormal_donuyor_inf_var", dizi=name)
        raise ValueError(f"{name} dizisinde Inf değeri var.")


def _validate_scalar(value: float, name: str) -> None:
    """Skaler değer doğrulama — NaN/Inf kontrolü.

    Args:
        value: Doğrulanacak değer
        name: Değer adı

    Raises:
        ValueError: NaN veya Inf ise
    """
    if np.isnan(value) or np.isinf(value):
        logger.error("anormal_donuyor_skaler_hatasi", deger_ad=name, deger=value)
        raise ValueError(f"{name} değeri NaN veya Inf olamaz: {value}")


def calculate_abnormal_return(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    alpha: float,
    beta: float,
    smb_returns: np.ndarray | None = None,
    hml_returns: np.ndarray | None = None,
    beta_smb: float = DEFAULT_BETA_FACTOR,
    beta_hml: float = DEFAULT_BETA_FACTOR,
) -> np.ndarray:
    """Abnormal Return hesapla.

    Market Model: AR = R_stock - (α + β × R_market)
    Fama-French:  AR = R_stock - (α + β_m×R_m + β_smb×SMB + β_hml×HML)

    Args:
        stock_returns: Hisse getirileri (tek boyutlu numpy array, float64 önerilir)
        market_returns: Piyasa getirileri (stock_returns ile aynı uzunlukta)
        alpha: Intercept (expected return modelinden)
        beta: Market beta
        smb_returns: SMB factor returns (opsiyonel, aynı uzunlukta)
        hml_returns: HML factor returns (opsiyonel, aynı uzunlukta)
        beta_smb: SMB beta katsayısı
        beta_hml: HML beta katsayısı

    Returns:
        Abnormal return array (float64 dtype)

    Raises:
        TypeError: Girdiler numpy array değilse
        ValueError: Boş array, uzunluk uyuşmazlığı, NaN/Inf varsa
    """
    # Tip doğrulama
    _validate_array(stock_returns, "stock_returns")
    _validate_array(market_returns, "market_returns")
    _validate_scalar(alpha, "alpha")
    _validate_scalar(beta, "beta")

    # Uzunluk uyumsuzluğu kontrolü
    if len(stock_returns) != len(market_returns):
        logger.error(
            "anormal_donuyor_uzunluk_uyusmazligi",
            hisse_uzunluk=len(stock_returns),
            piyasa_uzunluk=len(market_returns),
        )
        raise ValueError(
            f"Hisse ve piyasa getiri dizilerinin uzunlukları eşit olmalı: "
            f"stock={len(stock_returns)}, market={len(market_returns)}"
        )

    # dtype kontrolü — float64'e çevir (precision kaybı önleme)
    stock_f64 = np.asarray(stock_returns, dtype=np.float64)
    market_f64 = np.asarray(market_returns, dtype=np.float64)

    expected = alpha + beta * market_f64

    if smb_returns is not None:
        _validate_array(smb_returns, "smb_returns")
        if len(smb_returns) != len(stock_returns):
            logger.error(
                "anormal_donuyor_smb_uzunluk_uyusmazligi",
                smb_uzunluk=len(smb_returns),
                hisse_uzunluk=len(stock_returns),
            )
            raise ValueError(
                f"SMB dizisi uzunluğu uyuşmuyor: smb={len(smb_returns)}, stock={len(stock_returns)}"
            )
        expected += beta_smb * np.asarray(smb_returns, dtype=np.float64)

    if hml_returns is not None:
        _validate_array(hml_returns, "hml_returns")
        if len(hml_returns) != len(stock_returns):
            logger.error(
                "anormal_donuyor_hml_uzunluk_uyusmazligi",
                hml_uzunluk=len(hml_returns),
                hisse_uzunluk=len(stock_returns),
            )
            raise ValueError(
                f"HML dizisi uzunluğu uyuşmuyor: hml={len(hml_returns)}, stock={len(stock_returns)}"
            )
        expected += beta_hml * np.asarray(hml_returns, dtype=np.float64)

    ar = stock_f64 - expected

    logger.debug(
        "anormal_donuyor_hesaplandi",
        n=len(ar),
        ortalama_ar=float(np.mean(ar)),
        standart_sapma_ar=float(np.std(ar)),
    )

    return ar


def calculate_abnormal_return_batch(
    stocks_returns: dict[str, np.ndarray],
    market_returns: np.ndarray,
    params: dict[str, dict[str, float]],
    warn_on_default: bool = True,
) -> dict[str, np.ndarray]:
    """Birden fazla hisse için toplu abnormal return hesapla.

    Args:
        stocks_returns: {ticker: returns} sözlüğü
        market_returns: Piyasa getirileri
        params: {ticker: {"alpha": ..., "beta_market": ..., ...}} sözlüğü
        warn_on_default: Ticker bulunamadığında varsayılan parametre uyarısı

    Returns:
        {ticker: ar_array} sözlüğü

    Raises:
        TypeError: market_returns numpy array değilse
        ValueError: market_returns boşsa veya NaN/Inf içeriyorsa
    """
    if not stocks_returns:
        logger.warning("anormal_donuyor_toplu_bos_sozluk")
        return {}

    _validate_array(market_returns, "market_returns")

    market_f64 = np.asarray(market_returns, dtype=np.float64)

    results: dict[str, np.ndarray] = {}
    for ticker, stock_ret in stocks_returns.items():
        if ticker not in params:
            if warn_on_default:
                logger.warning(
                    "anormal_donuyor_toplu_varsayilan_kullanildi",
                    ticker=ticker,
                    varsayilan_alpha=DEFAULT_ALPHA,
                    varsayilan_beta=DEFAULT_BETA_MARKET,
                )
            p: dict[str, float] = {"alpha": DEFAULT_ALPHA, "beta_market": DEFAULT_BETA_MARKET}
        else:
            p = params[ticker]

        n = min(len(stock_ret), len(market_f64))
        if n < MIN_ARRAY_LENGTH:
            logger.warning("anormal_donuyor_toplu_kisa_atlanan", ticker=ticker, n=n)
            continue

        # Slicing uyarısı — caller veri kaybını bilmeli
        if len(stock_ret) > n:
            logger.info(
                "anormal_donuyor_toplu_kisaltildi",
                ticker=ticker,
                orijinal_uzunluk=len(stock_ret),
                kisaltilmis_uzunluk=n,
            )

        try:
            ar = calculate_abnormal_return(
                np.asarray(stock_ret[:n], dtype=np.float64),
                market_f64[:n],
                p["alpha"],
                p["beta_market"],
                beta_smb=p.get("beta_smb", DEFAULT_BETA_FACTOR),
                beta_hml=p.get("beta_hml", DEFAULT_BETA_FACTOR),
            )
            results[ticker] = ar
        except (ValueError, TypeError) as e:
            logger.error("anormal_donuyor_toplu_ticker_hatasi", ticker=ticker, hata=str(e))
            raise

    return results
