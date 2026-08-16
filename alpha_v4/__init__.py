"""ALPHA v4 clean-core package.

This package is intentionally isolated from legacy runtime code while the repository
is migrated under memory/SYSTEM-CONSTITUTION.md and memory/TARGET-ARCHITECTURE.md.
"""

from .contracts import CanonicalEvent, EvidenceRef, RawBar, ValidationStatus
from .data_quality import validate_raw_bar, masked_log_returns
from .event_intelligence import CompanyContext, ContractFacts, analyze_contract_event

__all__ = [
    "CanonicalEvent",
    "EvidenceRef",
    "RawBar",
    "ValidationStatus",
    "validate_raw_bar",
    "masked_log_returns",
    "CompanyContext",
    "ContractFacts",
    "analyze_contract_event",
]
