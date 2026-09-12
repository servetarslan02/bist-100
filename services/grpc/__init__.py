"""ALPHA BIST — gRPC Servis Katmanı v1.0

Servisler arası hızlı iletişim için gRPC + Protobuf.
JSON'dan 10x küçük, 10x hızlı.

Modül bileşenleri:
    - server: gRPC sunucu başlatma ve servis handler'ları
    - client: İstemci sınıfları (Market, Signal, Portfolio, Risk)
    - generated: Protobuf tarafından üretilen kod

Kullanım:
    from services.grpc import start_grpc_server
    from services.grpc import MarketClient, SignalClient
"""

from .client import MarketClient, PortfolioClient, RiskClient, SignalClient
from .server import start_grpc_server

__all__: list[str] = [
    "MarketClient",
    "PortfolioClient",
    "RiskClient",
    "SignalClient",
    "start_grpc_server",
]
