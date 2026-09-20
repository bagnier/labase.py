"""The Studio base is configuration first: `SUPABASE_STUDIO_URL` is browser-facing, so nothing
derived from the server-side `SUPABASE_API_URL` (a docker host, a worktree port) can stand in for
it. Empty means what it says — this deployment has no Studio — except for a hosted project, whose
dashboard URL really is derivable from the project ref, for everyone, forever."""

from apps.console.domain.studio import studio_base_url, studio_link


def test_an_explicit_studio_url_wins_whatever_the_api_url_says() -> None:
    base = studio_base_url("http://127.0.0.1:54323/project/default", "http://x.supabase.co")

    assert base == "http://127.0.0.1:54323/project/default"


def test_a_trailing_slash_does_not_double_in_links() -> None:
    base = studio_base_url("http://127.0.0.1:54323/project/default/", "http://any:54321")

    assert base == "http://127.0.0.1:54323/project/default"


def test_a_hosted_project_falls_back_to_its_dashboard() -> None:
    base = studio_base_url("", "https://abcdef.supabase.co")

    assert base == "https://supabase.com/dashboard/project/abcdef"


def test_no_studio_url_and_no_hosted_ref_means_no_studio() -> None:
    base = studio_base_url("", "http://host.docker.internal:54321")

    assert base is None


def test_studio_link_joins_path() -> None:
    link = studio_link("", "https://abcdef.supabase.co", "auth/users")

    assert link == "https://supabase.com/dashboard/project/abcdef/auth/users"


def test_studio_link_without_a_studio_is_none() -> None:
    link = studio_link("", "http://127.0.0.1:54421", "/editor")

    assert link is None
