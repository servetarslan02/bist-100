"""Bootstrap source catalog for ALPHA v4.

This is a seed list, never a coverage cap. Reliability is not pre-awarded; it remains
unknown until observations accumulate. Credentials are referenced by environment-key
name only and are never stored here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Tuple

from .acquisition import HttpSourceConfig
from .source_registry import SourceKind, SourceRecord


@dataclass(frozen=True)
class SourceSeed:
    record: SourceRecord
    http: HttpSourceConfig
    credential_env: Optional[str]
    role: str


OFFICIAL_SOURCE_SEEDS: Tuple[SourceSeed, ...] = (
    SourceSeed(
        record=SourceRecord(
            source_id="bist-official-public",
            kind=SourceKind.MARKET,
            owner="Borsa Istanbul",
            access_method="official-public-web",
            timezone_name="Europe/Istanbul",
            freshness_limit=timedelta(minutes=30),
        ),
        http=HttpSourceConfig(
            source_id="bist-official-public",
            base_url="https://www.borsaistanbul.com",
        ),
        credential_env=None,
        role="official market/reference pages and public delayed data discovery",
    ),
    SourceSeed(
        record=SourceRecord(
            source_id="kap-official",
            kind=SourceKind.KAP,
            owner="KAP / MKK",
            access_method="official-public-web",
            timezone_name="Europe/Istanbul",
            freshness_limit=timedelta(minutes=5),
        ),
        http=HttpSourceConfig(
            source_id="kap-official",
            base_url="https://www.kap.org.tr",
        ),
        credential_env=None,
        role="issuer disclosures, financial reports and corporate-action events",
    ),
    SourceSeed(
        record=SourceRecord(
            source_id="tcmb-evds",
            kind=SourceKind.OFFICIAL_MACRO,
            owner="TCMB",
            access_method="official-web-service",
            timezone_name="Europe/Istanbul",
            freshness_limit=timedelta(days=1),
        ),
        http=HttpSourceConfig(
            source_id="tcmb-evds",
            base_url="https://evds3.tcmb.gov.tr",
        ),
        credential_env="TCMB_EVDS_API_KEY",
        role="Turkey macroeconomic and financial time-series data",
    ),
)


def seed_by_id(source_id: str) -> SourceSeed:
    for seed in OFFICIAL_SOURCE_SEEDS:
        if seed.record.source_id == source_id:
            return seed
    raise KeyError(source_id)
