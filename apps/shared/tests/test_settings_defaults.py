"""Defaults a fresh checkout runs with, read from the declaration so no env file can mask them."""

import pytest
from pydantic import ValidationError

from apps.shared.settings.env import TechnicalSettings


def test_the_fallback_log_dir_defaults_under_the_cache_dir():
    assert TechnicalSettings.model_fields["firehose_dir"].default == ".cache/firehose"


def test_a_zero_backup_storage_page_size_is_rejected():
    with pytest.raises(ValidationError, match="backup_storage_page_size"):
        TechnicalSettings(
            supabase_api_url="https://abcdefgh.supabase.co",
            supabase_publishable_key="sb_publishable_" + "x" * 32,
            supabase_secret_key="sb_secret_" + "x" * 32,
            supabase_database_user_url="postgresql+asyncpg://user@db/postgres",
            backup_storage_page_size=0,
        )
