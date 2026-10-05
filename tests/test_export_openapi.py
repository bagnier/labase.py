"""`make client-gen` describes every app, including those switched off, whose routes mount would
skip."""

import ast
from pathlib import Path

from apps.shared.settings.store import BOOL_FALSE, BOOL_TRUE, ENABLED_KEY
from scripts.export_openapi import force_all_apps_enabled

_SOURCE = (Path(__file__).resolve().parents[1] / "scripts" / "export_openapi.py").read_text()


def test_force_all_apps_enabled_overrides_a_disabled_apps_persisted_value():
    wrapped = force_all_apps_enabled(lambda app: {ENABLED_KEY: BOOL_FALSE})

    assert wrapped("some_app") == {ENABLED_KEY: BOOL_TRUE}


def test_the_apps_main_import_is_protected_by_the_enabled_patch_and_its_restore():
    """Read from the source: ``apps.main`` is already imported, so behaviour cannot show the
    import moving outside the patch."""
    (try_node,) = [node for node in ast.parse(_SOURCE).body if isinstance(node, ast.Try)]

    imports_apps_main_in_try_body = any(
        isinstance(stmt, ast.ImportFrom) and stmt.module == "apps.main" for stmt in try_node.body
    )
    restores_read_values_in_finally = any(
        isinstance(stmt, ast.Assign) and ast.unparse(stmt.targets[0]) == "settings_live.read_values"
        for stmt in try_node.finalbody
    )

    assert (imports_apps_main_in_try_body, restores_read_values_in_finally) == (True, True)
