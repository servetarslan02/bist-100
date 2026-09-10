"""ALPHA BIST — Multi-Factor Expected Return (Fama-French).

Fama-French 3-Factor ve 5-Factor modeli ile expected return hesaplama.
BIST için SMB (Small Minus Big) ve HML (High Minus Low) factor'leri.
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# --- Sabitler ---
VALID_MODEL_TYPES: tuple[str, ...] = ("market", "fama_french_3", "fama_french_5")

# classify_stocks threshold sınırları
THRESHOLD_MIN: float = 0.0
THRESHOLD_MAX: float = 1.0
DEFAULT_SIZE_THRESHOLD: float = 0.5
DEFAULT_BM_THRESHOLD_LOW: float = 0.3
DEFAULT_BM_THRESHOLD_HIGH: float = 0.7

# predict fonksiyonu beklenen key'ler
PREDICT_REQUIRED_KEYS: tuple[str, ...] = ("alpha", "beta_market", "beta_smb", "beta_hml", "beta_rmw", "beta_cma")


def _validate_model_type(model_type: str) -> None:
    """Model tipi doğrulama.

    Args:
        model_type: Kontrol edilecek model tipi

    Raises:
        TypeError: String değilse
        ValueError: Geçerli model tiplerinden biri değilse
    """
    if not isinstance(model_type, str):
        raise TypeError(f"model_type string olmalı, alınan: {type(model_type).__name__}")
    if model_type not in VALID_MODEL_TYPES:
        raise ValueError(
            f"model_type geçerli değil: '{model_type}'. Geçerli tipler: {VALID_MODEL_TYPES}"
        )


def _validate_array(arr: Any, name: str, min_size: int = 1) -> np.ndarray:
    """Array doğrulama (tip, boşluk, NaN/Inf).

    Args:
        arr: Kontrol edilecek array (ndarray, list veya tuple)
        name: Array adı
        min_size: Minimum boyut

    Returns:
        Doğrulanmış numpy array

    Raises:
        TypeError: Desteklenmeyen tip ise
        ValueError: Boş, yetersiz veya NaN/Inf içeriyorsa
    """
    if isinstance(arr, (list, tuple)):
        arr = np.asarray(arr, dtype=float)
    if not isinstance(arr, np.ndarray):
        raise TypeError(f"{name} numpy.ndarray, list veya tuple olmalı, alınan: {type(arr).__name__}")
    if arr.size == 0:
        raise ValueError(f"{name} boş olamaz")
    if arr.size < min_size:
        raise ValueError(f"{name} en az {min_size} örneklem içermeli, alınan: {arr.size}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} NaN veya Inf değerler içeriyor")
    return arr


def _validate_equal_length(arrays: list[tuple[str, np.ndarray]]) -> None:
    """Array'lerin uzunluk uyumsuzluğu kontrolü.

    Args:
        arrays: [(isim, array)] listesi

    Raises:
        ValueError: Uzunluklar farklı ise
    """
    if len(arrays) < 2:
        return
    lengths = {name: arr.size for name, arr in arrays}
    unique_lengths = set(lengths.values())
    if len(unique_lengths) > 1:
        raise ValueError(f"Array uzunlukları uyumsuz: {lengths}")


def _validate_float(value: float, name: str) -> float:
    """Float değer için tip ve NaN/Inf kontrolü.

    Args:
        value: Kontrol edilecek değer
        name: Değerin adı

    Returns:
        Doğrulanmış float

    Raises:
        TypeError: Sayısal değilse
        ValueError: NaN veya Inf ise
    """
    if not isinstance(value, (int, float, np.integer, np.floating)):
        raise TypeError(f"{name} sayısal olmalı, alınan: {type(value).__name__} ({value})")
    if not np.isfinite(value):
        raise ValueError(f"{name} sonlu değil: {value}")
    return float(value)


def _validate_threshold(value: float, name: str) -> None:
    """Threshold aralık kontrolü.

    Args:
        value: Kontrol edilecek değer
        name: Parametre adı

    Raises:
        TypeError: Sayısal değilse
        ValueError: [0, 1] aralığında değilse
    """
    _validate_float(value, name)
    if not (THRESHOLD_MIN <= value <= THRESHOLD_MAX):
        raise ValueError(f"{name} [{THRESHOLD_MIN}, {THRESHOLD_MAX}] aralığında olmalı, alınan: {value}")


def _validate_factor_returns(arr: np.ndarray | None, name: str) -> np.ndarray | None:
    """Opsiyonel factor return doğrulama (None geçerli).

    Args:
        arr: Kontrol edilecek array veya None
        name: Parametre adı

    Returns:
        Doğrulanmış numpy array veya None

    Raises:
        TypeError: Desteklenmeyen tip ise
        ValueError: NaN/Inf içeriyorsa
    """
    if arr is None:
        return None
    return _validate_array(arr, name)


class MultiFactorModel:
    """Fama-French Multi-Factor Model."""

    def __init__(self, model_type: str = "fama_french_3") -> None:
        """Multi-Factor Model başlat.

        Args:
            model_type: "market", "fama_french_3", "fama_french_5"

        Raises:
            TypeError: model_type string değilse
            ValueError: Geçersiz model_type ise
        """
        _validate_model_type(model_type)
        self.model_type: str = model_type
        self.params: dict[str, float] | None = None

    def fit(
        self,
        stock_returns: np.ndarray,
        market_returns: np.ndarray,
        smb_returns: np.ndarray | None = None,
        hml_returns: np.ndarray | None = None,
        rmw_returns: np.ndarray | None = None,
        cma_returns: np.ndarray | None = None,
    ) -> dict[str, float]:
        """Modeli estimation window verisi ile eğit.

        Args:
            stock_returns: Hisse getirileri
            market_returns: BIST-100 getirileri
            smb_returns: Small Minus Big
            hml_returns: High Minus Low
            rmw_returns: Robust Minus Weak (FF5)
            cma_returns: Conservative Minus Aggressive (FF5)

        Returns:
            Model parametreleri

        Raises:
            TypeError: Array tipleri uygun değilse
            ValueError: Array'ler boş, yetersiz, NaN/Inf içeriyorsa veya uzunluklar uyumsuzsa
        """
        from .expected_return import calculate_expected_return

        # --- Validasyon ---
        sr = _validate_array(stock_returns, "stock_returns")
        mr = _validate_array(market_returns, "market_returns")
        smb_returns = _validate_factor_returns(smb_returns, "smb_returns")
        hml_returns = _validate_factor_returns(hml_returns, "hml_returns")
        rmw_returns = _validate_factor_returns(rmw_returns, "rmw_returns")
        cma_returns = _validate_factor_returns(cma_returns, "cma_returns")

        # Uzunluk uyumsuzluğu kontrolü
        arrays: list[tuple[str, np.ndarray]] = [("stock_returns", sr), ("market_returns", mr)]
        if smb_returns is not None:
            arrays.append(("smb_returns", smb_returns))
        if hml_returns is not None:
            arrays.append(("hml_returns", hml_returns))
        if rmw_returns is not None:
            arrays.append(("rmw_returns", rmw_returns))
        if cma_returns is not None:
            arrays.append(("cma_returns", cma_returns))
        _validate_equal_length(arrays)

        self.params = calculate_expected_return(
            stock_returns=sr,
            market_returns=mr,
            model=self.model_type,
            smb_returns=smb_returns,
            hml_returns=hml_returns,
            rmw_returns=rmw_returns,
            cma_returns=cma_returns,
        )

        logger.debug(
            "cok_faktorlu_model_egitildi",
            model=self.model_type,
            r_squared=round(self.params["r_squared"], 4),
            n_obs=self.params["n_obs"],
        )

        return self.params

    def predict(
        self,
        market_return: float,
        smb: float = 0.0,
        hml: float = 0.0,
        rmw: float = 0.0,
        cma: float = 0.0,
    ) -> float:
        """Expected return tahmini.

        E[R] = α + β_m×R_m + β_smb×SMB + β_hml×HML + β_rmw×RMW + β_cma×CMA

        Args:
            market_return: Piyasa getirisi
            smb: Small Minus Big
            hml: High Minus Low
            rmw: Robust Minus Weak
            cma: Conservative Minus Aggressive

        Returns:
            Expected return

        Raises:
            ValueError: Model henüz eğitilmemişse
        """
        if self.params is None:
            raise ValueError("Model henüz eğitilmedi — fit() çağrılmalı")

        # params key'lerini kontrol et
        missing = [k for k in PREDICT_REQUIRED_KEYS if k not in self.params]
        if missing:
            raise ValueError(f"Model parametreleri eksik: {missing}")

        return (
            self.params["alpha"]
            + self.params["beta_market"] * market_return
            + self.params["beta_smb"] * smb
            + self.params["beta_hml"] * hml
            + self.params["beta_rmw"] * rmw
            + self.params["beta_cma"] * cma
        )

    def get_params(self) -> dict[str, float]:
        """Model parametrelerini döndür.

        Returns:
            Model parametreleri sözlüğü (eğitilmemişse boş sözlük)
        """
        return self.params if self.params is not None else {}


class FamaFrenchFactors:
    """BIST için Fama-French factor hesaplama."""

    @staticmethod
    def _validate_factor_pair(
        arr1: Any, arr2: Any, name1: str, name2: str
    ) -> tuple[np.ndarray, np.ndarray]:
        """Factor çifti doğrulama (tip, NaN/Inf, uzunluk).

        Args:
            arr1: Birinci array
            arr2: İkinci array
            name1: Birinci array adı
            name2: İkinci array adı

        Returns:
            Doğrulanmış numpy array çifti

        Raises:
            TypeError: Desteklenmeyen tip ise
            ValueError: Boş, NaN/Inf veya uzunluk uyumsuzsa
        """
        a1 = _validate_array(arr1, name1)
        a2 = _validate_array(arr2, name2)
        if a1.size != a2.size:
            raise ValueError(f"{name1} ({a1.size}) ve {name2} ({a2.size}) uzunlukları eşit olmalı")
        return a1, a2

    @staticmethod
    def calculate_smb(
        small_cap_returns: np.ndarray,
        large_cap_returns: np.ndarray,
    ) -> np.ndarray:
        """SMB (Small Minus Big) = Small Cap Return - Large Cap Return.

        Args:
            small_cap_returns: Küçük şirket getirileri
            large_cap_returns: Büyük şirket getirileri

        Returns:
            SMB serisi

        Raises:
            TypeError: Array tipi uygun değilse
            ValueError: Boş, NaN/Inf veya uzunluk uyumsuzsa
        """
        s, l = FamaFrenchFactors._validate_factor_pair(
            small_cap_returns, large_cap_returns, "small_cap_returns", "large_cap_returns"
        )
        return s - l

    @staticmethod
    def calculate_hml(
        value_returns: np.ndarray,
        growth_returns: np.ndarray,
    ) -> np.ndarray:
        """HML (High Minus Low) = Value Return - Growth Return.

        Args:
            value_returns: Değer hisseleri getirileri
            growth_returns: Büyüme hisseleri getirileri

        Returns:
            HML serisi

        Raises:
            TypeError: Array tipi uygun değilse
            ValueError: Boş, NaN/Inf veya uzunluk uyumsuzsa
        """
        v, g = FamaFrenchFactors._validate_factor_pair(
            value_returns, growth_returns, "value_returns", "growth_returns"
        )
        return v - g

    @staticmethod
    def calculate_rmw(
        robust_returns: np.ndarray,
        weak_returns: np.ndarray,
    ) -> np.ndarray:
        """RMW (Robust Minus Weak) = Robust Return - Weak Return.

        Args:
            robust_returns: Güçlü şirket getirileri
            weak_returns: Zayıf şirket getirileri

        Returns:
            RMW serisi

        Raises:
            TypeError: Array tipi uygun değilse
            ValueError: Boş, NaN/Inf veya uzunluk uyumsuzsa
        """
        r, w = FamaFrenchFactors._validate_factor_pair(
            robust_returns, weak_returns, "robust_returns", "weak_returns"
        )
        return r - w

    @staticmethod
    def calculate_cma(
        conservative_returns: np.ndarray,
        aggressive_returns: np.ndarray,
    ) -> np.ndarray:
        """CMA (Conservative Minus Aggressive) = Conservative Return - Aggressive Return.

        Args:
            conservative_returns: Muhafazakar şirket getirileri
            aggressive_returns: Agresif şirket getirileri

        Returns:
            CMA serisi

        Raises:
            TypeError: Array tipi uygun değilse
            ValueError: Boş, NaN/Inf veya uzunluk uyumsuzsa
        """
        c, a = FamaFrenchFactors._validate_factor_pair(
            conservative_returns, aggressive_returns, "conservative_returns", "aggressive_returns"
        )
        return c - a

    @staticmethod
    def classify_stocks(
        market_caps: np.ndarray,
        book_to_market: np.ndarray,
        size_threshold: float = DEFAULT_SIZE_THRESHOLD,
        bm_threshold_low: float = DEFAULT_BM_THRESHOLD_LOW,
        bm_threshold_high: float = DEFAULT_BM_THRESHOLD_HIGH,
    ) -> dict[str, np.ndarray]:
        """Hisseleri Fama-French kategorilerine ayır.

        Args:
            market_caps: Piyasa değerleri
            book_to_market: Book-to-market oranları
            size_threshold: Boyut eşik değeri (median)
            bm_threshold_low: B/M alt eşik
            bm_threshold_high: B/M üst eşik

        Returns:
            {"small": mask, "big": mask, "value": mask, "growth": mask}

        Raises:
            TypeError: Array veya threshold tipleri uygun değilse
            ValueError: Array'ler boş, NaN/Inf içeriyorsa, uzunluklar uyumsuzsa
                     veya threshold [0,1] aralığında değilse
        """
        mc = _validate_array(market_caps, "market_caps")
        bm = _validate_array(book_to_market, "book_to_market")
        if mc.size != bm.size:
            raise ValueError(
                f"market_caps ({mc.size}) ve book_to_market ({bm.size}) uzunlukları eşit olmalı"
            )
        _validate_threshold(size_threshold, "size_threshold")
        _validate_threshold(bm_threshold_low, "bm_threshold_low")
        _validate_threshold(bm_threshold_high, "bm_threshold_high")
        if bm_threshold_low >= bm_threshold_high:
            raise ValueError(
                f"bm_threshold_low ({bm_threshold_low}) < bm_threshold_high ({bm_threshold_high}) olmalı"
            )

        median_cap = np.median(mc)

        small = mc <= median_cap
        big = mc > median_cap

        value = bm >= bm_threshold_high
        growth = bm <= bm_threshold_low

        return {
            "small": small,
            "big": big,
            "value": value,
            "growth": growth,
        }
