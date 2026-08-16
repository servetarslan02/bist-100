from alpha_v4.source_catalog import OFFICIAL_SOURCE_SEEDS, seed_by_id


def test_official_source_seed_catalog_has_no_pre_awarded_reliability():
    assert len(OFFICIAL_SOURCE_SEEDS) >= 3
    assert all(seed.record.measured_reliability is None for seed in OFFICIAL_SOURCE_SEEDS)


def test_seed_catalog_contains_no_secret_values():
    evds = seed_by_id("tcmb-evds")

    assert evds.credential_env == "TCMB_EVDS_API_KEY"
    assert "api_key=" not in evds.http.base_url.lower()
    assert "token=" not in evds.http.base_url.lower()


def test_seed_catalog_does_not_impose_asset_or_source_limit():
    # The catalog only bootstraps trusted official sources; source registries can grow
    # without consulting or mutating this tuple.
    ids = {seed.record.source_id for seed in OFFICIAL_SOURCE_SEEDS}

    assert {"bist-official-public", "kap-official", "tcmb-evds"}.issubset(ids)
