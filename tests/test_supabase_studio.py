from apps.shared.supabase_studio import studio_base_url, studio_link


def test_local_url_maps_to_local_studio() -> None:
    assert studio_base_url("http://localhost:54321") == "http://localhost:54323/project/default"


def test_docker_host_maps_to_local_studio() -> None:
    base = studio_base_url("http://host.docker.internal:54321")
    assert base == "http://localhost:54323/project/default"


def test_hosted_url_maps_to_dashboard_with_project_ref() -> None:
    base = studio_base_url("https://abcdef.supabase.co")
    assert base == "https://supabase.com/dashboard/project/abcdef"


def test_studio_link_joins_path() -> None:
    assert studio_link("https://abcdef.supabase.co", "auth/users") == (
        "https://supabase.com/dashboard/project/abcdef/auth/users"
    )
    assert studio_link("http://localhost:54321", "/editor") == (
        "http://localhost:54323/project/default/editor"
    )
