# Keeping dependencies current — `make upgrade`

Versions live in more places than the two lockfiles. This is the full pass:
Python, JavaScript, the tools pinned beside them, the browsers, then the gate.

## Python

```bash
make upgrade             # relax the == pins, uv lock --upgrade, re-pin, print what moved
uv sync --all-groups
uv tree --outdated --depth 1 --all-groups   # empty when nothing is left
```

`make upgrade` backs up `pyproject.toml` and `uv.lock` in `.cache/upgrade/`; if
the lock fails halfway, copy both back. It only relaxes `==` pins:
`[tool.uv] constraint-dependencies` survives it, and each constraint says in its
comment when to lift it.

## JavaScript

```bash
npx npm-check-updates -u && npm install
node_modules/.bin/biome migrate --write   # after a Biome bump: moves the $schema in biome.json
npm audit
```

A major version is read before it is installed: its breaking changes against
what `static/js/` and the templates actually use.

## Pinned outside the lockfiles

| File                              | Pin                             | Kept in step with                                                                                      |
| --------------------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `scripts/.pre-commit-config.yaml` | `ruff-pre-commit` rev           | `ruff==` in `pyproject.toml` — `uv run pre-commit autoupdate --config scripts/.pre-commit-config.yaml` |
| `.github/workflows/ci.yml`        | action versions                 | latest release; `setup-uv` publishes full tags only (`@v10.1.0`), no major tag                         |
| `.github/workflows/ci.yml`        | `supabase/setup-cli` `version`  | `supabase --version` on the dev machine                                                                |
| `.github/workflows/ci.yml`        | Playwright cache key            | `playwright` version in `uv.lock`                                                                      |
| `pyproject.toml`                  | `requires-python`               | latest 3.14 patch                                                                                      |
| `.mcp.json`                       | `@playwright/mcp`, `safari-mcp` | latest on npm                                                                                          |

## Browsers

Playwright's own browser is Google's Chrome for Testing. After a `playwright`
bump it needs a download: `uv run playwright install chromium` for the suite,
`npx @playwright/mcp@<version> install-browser chrome-for-testing` for the MCP.

A machine that keeps a Chromium of its own skips both: `CHROMIUM_EXECUTABLE_PATH`
and `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` in the shell,
`PLAYWRIGHT_MCP_EXECUTABLE_PATH` in `.claude/settings.local.json` (README, local
setup notes).

## Verify

```bash
make finalize            # lint, pip-audit, unit + integration
make test-e2e            # the only lane that runs the JavaScript
```

A browser scenario that fails on a timeout is run through `make flakehunt`
before the upgrade is blamed for it: the suite has intermittent ones (ROADMAP).
