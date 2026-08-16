import pytest

from alpha_v4.drift import DriftPolicy, assess_numeric_drift


def policy():
    return DriftPolicy(
        policy_version="1.0",
        minimum_reference_samples=5,
        minimum_recent_samples=3,
        maximum_standardized_mean_shift=2.0,
        maximum_std_ratio=2.5,
    )


def test_insufficient_data_is_not_fabricated_as_stable_or_drift():
    result = assess_numeric_drift([1.0, 2.0], [3.0], policy=policy())

    assert result.status == "INSUFFICIENT_DATA"
    assert not result.detected
    assert result.reasons == ("insufficient_samples",)


def test_stable_distribution_is_not_flagged():
    result = assess_numeric_drift(
        [1, 2, 3, 4, 5, 6],
        [2, 3, 4, 5],
        policy=policy(),
    )

    assert result.status == "STABLE"
    assert not result.detected


def test_large_mean_shift_is_flagged():
    result = assess_numeric_drift(
        [0, 1, -1, 0.5, -0.5, 0.2, -0.2],
        [5, 6, 4, 5.5],
        policy=policy(),
    )

    assert result.detected
    assert "standardized_mean_shift_exceeded" in result.reasons


def test_variance_explosion_is_flagged_even_without_large_mean_shift():
    result = assess_numeric_drift(
        [-1, 0, 1, -1, 0, 1],
        [-10, 0, 10, -9, 9],
        policy=policy(),
    )

    assert result.detected
    assert "standard_deviation_ratio_exceeded" in result.reasons


def test_constant_reference_changing_level_is_not_divided_by_fake_std():
    result = assess_numeric_drift(
        [1, 1, 1, 1, 1],
        [2, 2, 2],
        policy=policy(),
    )

    assert result.detected
    assert result.standardized_mean_shift is None
    assert "reference_variance_zero_mean_changed" in result.reasons


def test_policy_thresholds_are_explicit_and_validated():
    with pytest.raises(ValueError):
        DriftPolicy(
            policy_version="1",
            minimum_reference_samples=5,
            minimum_recent_samples=3,
            maximum_standardized_mean_shift=1,
            maximum_std_ratio=0.5,
        )
