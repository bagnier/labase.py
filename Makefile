.PHONY: check flakehunt dev up down logs env db-start db-stop db-reset db-seed promote-admin migrate schema schema-supabase test test-e2e perf-smoke ci install cloud-setup js-build lint fix finalize coverage-erase coverage-xml coverage-html cert letsencrypt upgrade act client-gen worktree worktree-rm provision-test deadcode doctor upgrade-base preflight backup-storage

# Each worktree runs on the single shared Supabase stack but with its own schema/bucket/port.
# Compose is isolated per checkout so several `make dev` can run at once.
# Docker compose project names allow only [a-z0-9_-], so sanitise the dir name (e.g. "labase.py").
WORKTREE := $(subst .,-,$(notdir $(CURDIR)))
COMPOSE := docker compose --env-file .env --project-name labase-$(WORKTREE) --file docker/docker-compose.yml

# --- Setup ---
install: db-start
	uv sync --all-groups
	pre-commit install --config scripts/.pre-commit-config.yaml
	npm install
	$(MAKE) env
	$(MAKE) js-build

js-build:
	mkdir --parents static/css static/fonts static/js
	npm run build

# cloud-setup: provisioning for a remote "Claude Code on the web" VM.
# No local Supabase (DB via injected environment variables, see docs/REMOTE.md)
# — lighter than `install`. Paste as the setup script in the web UI:
# `make cloud-setup`.
cloud-setup:
	uv sync --all-groups
	npm install
	$(MAKE) js-build
	uv run playwright install --with-deps chromium

# Exports under ENV_FILE=.env.test: TechnicalSettings has required fields with
# no defaults, so importing the app needs a complete env — .env.test is the one
# committed config (CI has no .env). Routes are env-independent, so the schema is
# identical either way.
client-gen:
	ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/export_openapi.py /tmp/openapi.json
	uv run openapi-python-client generate --path /tmp/openapi.json --output-path client/ --overwrite

# --- Local Supabase ---
db-start:
	supabase start

env:
	uv run python scripts/gen_env.py

db-stop:
	supabase stop

db-reset:
	supabase db reset

db-seed:
	PYTHONPATH=. uv run python scripts/seed.py

# Create the user if missing, then promote to server admin: make promote-admin EMAIL=you@example.com [PASSWORD=…]
# Runs from the host, so targets localhost (.env.test). Override with ENV_FILE=.env to hit a linked remote.
promote-admin:
	ENV_FILE=$(if $(ENV_FILE),$(ENV_FILE),.env.test) PYTHONPATH=. uv run python scripts/promote_admin.py $(EMAIL) $(PASSWORD)

migrate:
	supabase db push

schema:
	tbls doc --rm-dist --config scripts/.tbls.yml
	uv run python scripts/tbls_postprocess.py

schema-supabase:
	tbls doc --rm-dist --config scripts/.tbls.supabase.yml

# --- App ---
dev: db-start js-build
	$(COMPOSE) up --build

up:
	$(COMPOSE) up --detach

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --follow app

# --- Worktrees (isolated schema/bucket/port on the shared Supabase) ---
worktree:
	uv run python scripts/worktree.py create $(NAME)

worktree-rm:
	uv run python scripts/worktree.py remove $(NAME)

# Clone the current public schema into this checkout's test schema (+ its bucket).
provision-test:
	env ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/provision_schema.py --reset

# --- Quality ---
# lint: read-only, fails on non-conforming code (used by `make ci`).
# Per file type: ruff/ty/pyright (Python), sqlfluff (SQL migrations, lint-light — no reformat),
# yamllint (YAML), validate-pyproject (pyproject schema), zizmor (GitHub Actions security),
# biome (JS/CSS/JSON), gherkin-lint (.feature), djlint (Jinja2). Dockerfiles are linted by
# droast, which runs as a self-contained GitHub Action in CI (see .github/workflows/ci.yml).
# All Python linters are pinned dev-deps in pyproject.toml, so they resolve once in uv.lock
# and run straight from the project env — no per-invocation resolution.
# Depends on client-gen because client/ is generated and gitignored: pyright resolves
# scripts/smoke.py's import through it, so a tree that never generated it lints red.
lint: client-gen
	uv run ruff check .
	uv run ruff format --check .
	uv run lint-imports --cache-dir .cache/import-linter
	uv run ty check apps/
	uv run pyright
	uv run sqlfluff lint --config scripts/.sqlfluff supabase/migrations/
	uv run yamllint -c scripts/.yamllint .github docker scripts
	uv run validate-pyproject pyproject.toml
	uv run zizmor --offline .github/workflows/
	npm run lint
	npm run lint:gherkin
	uv run djlint apps --lint
	uv run djlint apps --check
	uv run python scripts/check_design_tokens.py
	uv run pip-audit

deadcode:
	uv run vulture apps

# fix: auto-fixes what's fixable, re-checks typing like lint does.
# pip-audit (network, ~6s) intentionally stays in lint/CI only.
fix:
	uv run ruff check --fix .
	uv run ruff format .
	uv run lint-imports --cache-dir .cache/import-linter
	uv run ty check apps/
	npm run format
	uv run djlint apps --reformat

upgrade:
	mkdir --parents .cache/upgrade
	cp uv.lock .cache/upgrade/uv.lock.bak
	cp pyproject.toml .cache/upgrade/pyproject.toml.bak
	python3 scripts/upgrade.py relax
	uv lock --upgrade
	python3 scripts/upgrade.py repin

# --- Base upgrades (for products cloned from labase) ---
BASE_REMOTE ?= base
BASE_BRANCH ?= main

# Merge the latest base into a dedicated branch; resolve, `make ci`, then merge
# into the product branch. Ownership map and protocol: docs/upgrade-base.md.
upgrade-base:
	@git remote get-url $(BASE_REMOTE) >/dev/null 2>&1 || { \
	  echo "no '$(BASE_REMOTE)' remote — one-time setup:"; \
	  echo "  git remote add $(BASE_REMOTE) <url-of-labase.py>"; \
	  exit 1; }
	git fetch $(BASE_REMOTE) $(BASE_BRANCH)
	git switch --create upgrade-base-$(shell date +%Y%m%d) 2>/dev/null || git switch upgrade-base-$(shell date +%Y%m%d)
	git merge --no-ff $(BASE_REMOTE)/$(BASE_BRANCH) \
	  || echo "conflicts to resolve — see docs/upgrade-base.md, then run: make ci"

# doctor: reachability AND latency of the local stack (a wedged Docker proxy
# accepts TCP but multiplies every round-trip — see scripts/doctor.py).
doctor:
	env ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/doctor.py

# --- Production ---
# preflight: production config safety gate. Point it at the prod env file; exits
# non-zero on any blocking error, so it can gate a deploy. Docs: docs/production.md.
#   make preflight ENV_FILE=.env.production
preflight:
	ENV_FILE=$(if $(ENV_FILE),$(ENV_FILE),.env) PYTHONPATH=. uv run python scripts/preflight.py

# backup-storage: mirror the Supabase Storage bucket to disk (bytes aren't in SQL dumps).
#   make backup-storage DEST=/backups/storage ENV_FILE=.env.production
backup-storage:
	ENV_FILE=$(if $(ENV_FILE),$(ENV_FILE),.env) PYTHONPATH=. uv run python scripts/backup_storage.py --dest $(if $(DEST),$(DEST),backups/storage)

# --- Tests ---
# The coverage floor lives here, not in pyproject: `--cov-append` is on for every run, so a
# floor in the shared config makes any partial `pytest <one-file>` fail at 15% with all its
# tests green. It only means something over the whole suite. Measured at 51% the day it
# was wired in on an accumulated figure — the honest single-run number is 49.8%, which is
# what this floor sits under. Raise it when the real number moves up, never lower it to fit.
# No wall-clock guard here on purpose. There was one, warning past a threshold derived from a
# duration measured once — and a duration in a Makefile rots: the suite tripled in test count and
# the warning started firing on a healthy stack, which is how a guardrail becomes noise. What it
# was a proxy for is measured directly and cannot go stale: `test_local_stack_is_responsive`
# times each dependency on every run and fails the suite loudly when the stack is degraded.
test: provision-test
	env --ignore-environment ENV_FILE=.env.test PATH="$(PATH)" uv run pytest --cov-fail-under=48

test-e2e: provision-test
	env --ignore-environment ENV_FILE=.env.test PATH="$(PATH)" uv run pytest apps/ tests/e2e/drivers/ -k "test_scenarios or test_browser_isolation" --driver=browser --no-cov

# flakehunt: run the browser scenarios N times and aggregate failures per test — an
# intermittent test fails a few runs out of N, where a single run only says "red" or "green".
# No rerun plugin on purpose: a rerun hides exactly what this looks for.
#   make flakehunt N=10 [TARGET=apps/auth/tests/e2e/test_scenarios.py]
flakehunt:
	scripts/flakehunt.sh $(if $(N),$(N),10) $(TARGET)

# Perf smoke: boots the app on the test schema, drives it with Locust through
# the generated OpenAPI client; blocking thresholds live in scripts/smoke.py.
perf-smoke: provision-test client-gen
	env --ignore-environment ENV_FILE=.env.test PATH="$(PATH)" uv run python scripts/perf_smoke.py

coverage-erase:
	uv run coverage erase

coverage-xml:
	uv run coverage xml -o .cache/cov/coverage.xml

coverage-html:
	uv run coverage html --directory=.cache/cov/html

cert:
	openssl req -x509 -newkey rsa:4096 -keyout dev.key -out dev.crt -days 365 -nodes -subj '/CN=localhost'

letsencrypt:
	certbot certonly --standalone --domain $(DOMAIN) --agree-tos --non-interactive
	@echo "Certs at /etc/letsencrypt/live/$(DOMAIN)/"

# check = lint + test, the shared meaning across the three repos: read-only, no heavy lane,
# and what a pre-commit hook can afford to run. `ci` below adds the heavy lanes.
check: lint test

# --keep-going: run every step even if one fails, so no failure is hidden
# behind an earlier one; the sub-make exits non-zero if any step failed.
ci:
	$(MAKE) --keep-going js-build lint coverage-erase test test-e2e perf-smoke coverage-xml

# finalize: js-build + fix, then the full read-only gate and the suite. Run before committing.
# Wider than `fix + test` on purpose: the wave that raised ruff shipped two regressions a
# linter alone called green — one caught by `ty`, one only by the suite.
finalize: js-build fix check

act:
	act push --job ci --platform ubuntu-latest=catthehacker/ubuntu:act-24.04 --container-architecture linux/amd64 --network host
