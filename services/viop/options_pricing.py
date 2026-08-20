"""
ALPHA BIST — VIOP Options Pricing Wrapper

Black-Scholes opsiyon fiyatlaması.
Enhanced_options modülünden delegate eder.
"""

from .enhanced_options import black_scholes

__all__ = ["black_scholes"]
