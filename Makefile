.PHONY: check meta flakehunt dev up down logs env db-start db-stop db-reset db-seed promote-admin migrate schema schema-supabase test test-e2e perf-smoke ci install cloud-setup js-build lint fix finalize coverage-erase coverage-report coverage-xml coverage-html cert letsencrypt upgrade act client-gen worktree worktree-rm provision-test test-stack test-stack-rm deadcode doctor upgrade-base preflight backup-storage

# Worktrees share the dev stack (own schema, bucket, port); each checkout's tests have their own
# stack. Compose is per checkout; its project name allows only [a-z0-9_-].
WORKTREE := $(subst .,-,$(notdir $(CURDIR)))
COMPOSE := docker compose --env-file .env --project-name labase-$(WORKTREE) --file docker/docker-compose.yml

# A test schema and bucket per `make` run, named by its pid ($$PPID of the subshell), so
# concurrent runs never share rows. Kept after the run for inspection; provision_schema.py sweeps
# those whose pid has exited.
TEST_RUN_ID := $(shell echo $$PPID)
TEST_RUN_SCHEMA := test_$(TEST_RUN_ID)
TEST_RUN_BUCKET := org-files-test-$(TEST_RUN_ID)
TEST_ENV := env --ignore-environment ENV_FILE=.env.test SUPABASE_DATABASE_SCHEMA=$(TEST_RUN_SCHEMA) SUPABASE_STORAGE_BUCKET=$(TEST_RUN_BUCKET) PATH="$(PATH)"

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

# cloud-setup: the setup script of a "Claude Code on the web" VM, without local Supabase
# (docs/REMOTE.md).
cloud-setup:
	uv sync --all-groups
	npm install
	$(MAKE) js-build
	uv run playwright install --with-deps chromium

# Under .env.test, the one committed env, complete enough to import the app; routes do not
# depend on it.
client-gen:
	ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/export_openapi.py /tmp/openapi.json
	uv run openapi-python-client generate --path /tmp/openapi.json --output-path client/ --overwrite

# --- Local Supabase ---
db-start:
	supabase start

env:
	PYTHONPATH=. uv run python scripts/gen_env.py

db-stop:
	supabase stop

db-reset:
	supabase db reset
	$(MAKE) env

db-seed:
	PYTHONPATH=. uv run python scripts/seed.py

# make promote-admin EMAIL=you@example.com [PASSWORD=…]: create if missing, then promote.
# Targets .env.test's stack; ENV_FILE=.env for a linked remote.
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

# --- Worktrees (schema/bucket/port on the dev stack, tests on their own stack) ---
worktree:
	PYTHONPATH=. uv run python scripts/worktree.py create $(NAME)

worktree-rm:
	PYTHONPATH=. uv run python scripts/worktree.py remove $(NAME)

# This checkout's test stack (scripts/test_stack.py). test-stack-rm removes it with its volumes,
# and those of prunable worktrees.
test-stack:
	env ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/test_stack.py start

test-stack-rm:
	env ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/test_stack.py stop

# This run's schema and bucket, cloned from the test stack's public schema.
provision-test: test-stack
	env ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/provision_schema.py --schema $(TEST_RUN_SCHEMA) --bucket $(TEST_RUN_BUCKET) --reset

# --- Quality ---
# lint: read-only. Dockerfiles are linted by droast, in CI only. Needs client-gen: pyright resolves
# scripts/smoke.py's import through client/.
lint: client-gen
	uv run ruff check .
	uv run ruff format --check .
	uv run lint-imports --cache-dir .cache/import-linter
	uv run ty check apps/ tests/
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

# fix: auto-fix, then the type checks. pip-audit (network) stays in lint.
fix:
	uv run ruff check --fix .
	uv run ruff format .
	uv run lint-imports --cache-dir .cache/import-linter
	uv run ty check apps/ tests/
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

# Merge the latest base into its own branch, then into the product (docs/upgrade-base.md).
upgrade-base:
	@git remote get-url $(BASE_REMOTE) >/dev/null 2>&1 || { \
	  echo "no '$(BASE_REMOTE)' remote — one-time setup:"; \
	  echo "  git remote add $(BASE_REMOTE) <url-of-labase.py>"; \
	  exit 1; }
	git fetch $(BASE_REMOTE) $(BASE_BRANCH)
	git switch --create upgrade-base-$(shell date +%Y%m%d) 2>/dev/null || git switch upgrade-base-$(shell date +%Y%m%d)
	git merge --no-ff $(BASE_REMOTE)/$(BASE_BRANCH) \
	  || echo "conflicts to resolve — see docs/upgrade-base.md, then run: make ci"

# doctor: the local stack's reachability and latency (scripts/doctor.py).
doctor: test-stack
	env ENV_FILE=.env.test PYTHONPATH=. uv run python scripts/doctor.py

# --- Production ---
# preflight: the production config gate (docs/production.md).
#   make preflight ENV_FILE=.env.production
preflight:
	ENV_FILE=$(if $(ENV_FILE),$(ENV_FILE),.env) PYTHONPATH=. uv run python scripts/preflight.py

# backup-storage: mirror the Storage bucket to disk; SQL dumps lack the bytes.
#   make backup-storage DEST=/backups/storage ENV_FILE=.env.production
backup-storage:
	ENV_FILE=$(if $(ENV_FILE),$(ENV_FILE),.env) PYTHONPATH=. uv run python scripts/backup_storage.py --dest $(if $(DEST),$(DEST),backups/storage)

# --- Tests ---
# Coverage wraps pytest from outside (see pyproject's addopts), one data file per lane for
# `coverage-report`. Off by default, and one lane alone misreads the HTML face. `ci` sets COV=1:
#   make test COV=1 test-e2e COV=1 coverage-report coverage-html
PYTEST = $(if $(COV),uv run coverage run --parallel-mode -m pytest,uv run pytest)
# No wall-clock guard: `test_local_stack_is_responsive` checks the stack's latency directly.
test: provision-test
	$(TEST_ENV) $(PYTEST)

# The browser lane, the only one rendering HTML. CHROMIUM_EXECUTABLE_PATH, the one outside variable
# let through, picks an installed Chromium; unset, it arrives empty.
test-e2e: provision-test
	$(TEST_ENV) CHROMIUM_EXECUTABLE_PATH="$(CHROMIUM_EXECUTABLE_PATH)" $(PYTEST) apps/ tests/e2e/drivers/ -k "scenarios or test_browser_isolation" --driver=browser

# meta: the claims of AGENTS.md and the README (tests/meta/claims.py); run it after editing them.
meta: provision-test
	$(TEST_ENV) $(PYTEST) tests/meta

# flakehunt: run the browser scenarios N times and count failures per test. No rerun plugin: a
# rerun hides flakes.
#   make flakehunt N=10 [TARGET=apps/auth/tests/e2e/test_scenarios.py]
flakehunt:
	scripts/flakehunt.sh $(if $(N),$(N),10) $(TARGET)

# perf-smoke: Locust through the generated client; thresholds in scripts/smoke.py.
perf-smoke: provision-test client-gen
	$(TEST_ENV) uv run python scripts/perf_smoke.py

coverage-erase:
	uv run coverage erase

# The floor gates `ci`, on the combined figure. Raise COV_MIN as coverage rises, never lower it.
# `--sort=-miss` (descending) lists the files with the most missed statements first; percentages
# would rank by size. The total still counts every file.
COV_MIN ?= 90
coverage-report:
	uv run coverage combine
	uv run coverage report --sort=-miss --skip-covered --fail-under=$(COV_MIN)

# Both read what `coverage-report` combined.
coverage-xml:
	uv run coverage xml -o .cache/cov/coverage.xml

coverage-html:
	uv run coverage html --directory=.cache/cov/html

cert:
	openssl req -x509 -newkey rsa:4096 -keyout dev.key -out dev.crt -days 365 -nodes -subj '/CN=localhost'

letsencrypt:
	certbot certonly --standalone --domain $(DOMAIN) --agree-tos --non-interactive
	@echo "Certs at /etc/letsencrypt/live/$(DOMAIN)/"

# check = lint + test: read-only, light enough for a pre-commit hook. `ci` adds the heavy lanes.
check: lint test

# --keep-going: every step runs, so no failure hides another.
ci:
	$(MAKE) COV=1 --keep-going js-build lint coverage-erase test test-e2e perf-smoke coverage-report coverage-xml

# finalize: js-build + fix, then lint and the suite. Run before committing.
finalize: js-build fix check

act:
	act push --job ci --platform ubuntu-latest=catthehacker/ubuntu:act-24.04 --container-architecture linux/amd64 --network host
