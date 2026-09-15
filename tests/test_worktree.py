"""A worktree's tests run on a stack of their own: its `.env.test` names that stack's ports.

The main checkout's committed `.env.test` holds the 544xx block; a worktree gets a block above it.
"""

from scripts import worktree


def test_test_stack_settings_lay_the_services_on_the_block():
    assert worktree.test_stack_settings(54500) == {
        "SUPABASE_API_URL": "http://127.0.0.1:54521",
        "SUPABASE_DATABASE_USER_URL": "postgresql+asyncpg://postgres:postgres@127.0.0.1:54522/postgres",
        "SUPABASE_DATABASE_ADMIN_URL": "postgresql+asyncpg://postgres:postgres@127.0.0.1:54522/postgres",
        "MAILPIT_URL": "http://127.0.0.1:54524",
        "SMTP_PORT": "54525",
    }


def test_a_worktree_block_sits_above_the_main_checkout_on_a_hundred_boundary():
    base = worktree.test_block_base("calendar")

    assert (base % 100, 54500 <= base <= 59400) == (0, True)
