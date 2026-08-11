.PHONY: dev up down logs env db-start db-stop db-reset db-seed promote-admin migrate schema schema-supabase test test-e2e perf-smoke ci install cloud-setup js-build lint fix finalize coverage-erase coverage-xml coverage-html cert letsencrypt upgrade act client-gen worktree worktree-rm provision-test deadcode doctor upgrade-base preflight backup-storage

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
# Per file type: ruff/ty (Python), sqlfluff (SQL migrations, lint-light — no reformat),
# yamllint (YAML), validate-pyproject (pyproject schema), zizmor (GitHub Actions security),
# biome (JS/CSS/JSON), gherkin-lint (.feature), djlint (Jinja2). Dockerfiles are linted by
# droast, which runs as a self-contained GitHub Action in CI (see .github/workflows/ci.yml).
# All Python linters are pinned dev-deps in pyproject.toml, so they resolve once in uv.lock
# and run straight from the project env — no per-invocation resolution.
lint:
	uv run ruff check .
	uv run lint-imports --cache-dir .cache/import-linter
	uv run ty check apps/
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
	cp uv.lock /tmp/uv.lock.bak
	cp pyproject.toml /tmp/pyproject.toml.bak
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
# The suite normally runs in ~100s; way beyond that means the environment is
# degraded (not the tests) — say so instead of letting it pass silently slow.
test: provision-test
	@start=$$(date +%s); \
	env --ignore-environment ENV_FILE=.env.test PATH="$(PATH)" uv run pytest; rc=$$?; \
	elapsed=$$(( $$(date +%s) - start )); \
	if [ $$elapsed -gt 240 ]; then \
		echo "⚠ pytest took $${elapsed}s (~100s expected) — run 'make doctor'"; \
	fi; \
	exit $$rc

test-e2e: provision-test
	env --ignore-environment ENV_FILE=.env.test PATH="$(PATH)" uv run pytest apps/ tests/e2e/drivers/ -k "test_scenarios or test_browser_isolation" --driver=browser --no-cov

# Perf smoke: boots the app on the test schema, drives it with Locust through
# the generated OpenAPI client; blocking thresholds live in scripts/smoke.py.
# Depends on client-gen because client/ is generated (gitignored), so CI — which
# checks out a fresh tree — must build it before the smoke can import it.
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

# --keep-going: run every step even if one fails, so no failure is hidden
# behind an earlier one; the sub-make exits non-zero if any step failed.
ci:
	$(MAKE) --keep-going js-build lint coverage-erase test test-e2e perf-smoke coverage-xml

# finalize: js-build + fix (also typechecks + audits) + local tests. Run before committing.
finalize: js-build fix test

act:
	act push --job ci --platform ubuntu-latest=catthehacker/ubuntu:act-24.04 --container-architecture linux/amd64 --network host
