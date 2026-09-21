"""Defaults a fresh checkout runs with, read from the declaration so no env file can mask them."""

from apps.shared.settings.env import TechnicalSettings


def test_the_fallback_log_dir_defaults_under_the_cache_dir():
    assert TechnicalSettings.model_fields["firehose_dir"].default == ".cache/firehose"
