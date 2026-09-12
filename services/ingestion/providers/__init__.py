"""ALPHA BIST — Ingestion Data Providers Package.

Veri sağlayıcı modülleri: BIST, KAP, TCMB, yfinance, Matriks,
TradingView, Investing.com, İş Yatırım, haber, sosyal medya,
temel analiz ve makro veri sağlayıcıları.

Not: Import'lar lazy olarak gerçekleştirilir —providers ağır bağımlılıklar
(yfinance, requests vb.) gerektirdiğinden doğrudan yüklenmez.
"""

_PROVIDER_MAP: dict[str, str] = {
    "bist_provider": "bist_provider",
    "fundamental_provider": "fundamental_provider",
    "investing_provider": "investing_provider",
    "kap_provider": "kap_provider",
    "macro_provider": "macro_provider",
    "matriks_provider": "matriks_provider",
    "news_provider": "news_provider",
    "social_provider": "social_provider",
    "tcmb_provider": "tcmb_provider",
    "tradingview_provider": "tradingview_provider",
    "universe_updater": "universe_provider",
    "yfinance_provider": "yfinance_provider",
}

__all__ = list(_PROVIDER_MAP.keys())


def __getattr__(name: str) -> object:
    """Lazy import ile provider modüllerini yükler.

    Args:
        name: Modül veya singleton adı.

    Returns:
        İstenen modül/nesne.

    Raises:
        AttributeError: Bilinmeyen ad.
    """
    if name in _PROVIDER_MAP:
        import importlib

        module = importlib.import_module(f".{_PROVIDER_MAP[name]}", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
