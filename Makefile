.PHONY: dev up down logs env db-start db-stop db-reset db-seed migrate schema schema-supabase test test-e2e ci install js-build lint fix finalize coverage-erase coverage-xml coverage-html cert letsencrypt upgrade act client-gen worktree worktree-rm provision-test

# Each worktree runs on the single shared Supabase stack but with its own schema/bucket/port.
# Compose is isolated per checkout so several `make dev` can run at once.
# Docker compose project names allow only [a-z0-9_-], so sanitise the dir name (e.g. "labase.py").
WORKTREE := $(subst .,-,$(notdir $(CURDIR)))
COMPOSE := docker compose --env-file .env -p labase-$(WORKTREE) -f docker/docker-compose.yml

# --- Setup ---
install: db-start
	uv sync --all-groups
	pre-commit install --config scripts/.pre-commit-config.yaml
	npm install
	$(MAKE) env
	$(MAKE) js-build

js-build:
	mkdir -p static/css static/fonts static/js
	npm run build

client-gen:
	PYTHONPATH=. uv run python scripts/export_openapi.py > /tmp/openapi.json
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
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f app

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
lint:
	uv run ruff check .
	uv run ty check apps/
	npm run lint
	uv run djlint apps --lint
	uv run djlint apps --check
	uv run pip-audit

# fix: auto-fixes what's fixable, re-checks typing/audit like lint does.
fix:
	uv run ruff check --fix .
	uv run ruff format .
	uv run ty check apps/
	npm run format
	uv run djlint apps --reformat
	uv run pip-audit

upgrade:
	cp uv.lock /tmp/uv.lock.bak
	cp pyproject.toml /tmp/pyproject.toml.bak
	python3 scripts/upgrade.py relax
	uv lock --upgrade
	python3 scripts/upgrade.py repin

# --- Tests ---
test: provision-test
	env -i ENV_FILE=.env.test PATH="$(PATH)" uv run pytest

test-e2e: provision-test
	env -i ENV_FILE=.env.test PATH="$(PATH)" uv run pytest apps/ -k test_scenarios --driver=browser --no-cov

coverage-erase:
	uv run coverage erase

coverage-xml:
	uv run coverage xml -o .cov/coverage.xml

coverage-html:
	uv run coverage html -d .cov/html

cert:
	openssl req -x509 -newkey rsa:4096 -keyout dev.key -out dev.crt -days 365 -nodes -subj '/CN=localhost'

letsencrypt:
	certbot certonly --standalone -d $(DOMAIN) --agree-tos --non-interactive
	@echo "Certs at /etc/letsencrypt/live/$(DOMAIN)/"

# -k (keep-going): run every step even if one fails, so no failure is hidden
# behind an earlier one; the sub-make exits non-zero if any step failed.
ci:
	$(MAKE) -k js-build lint coverage-erase test test-e2e coverage-xml

# finalize: js-build + fix (also typechecks + audits) + local tests. Run before committing.
finalize: js-build fix test

act:
	act push -j ci -P ubuntu-latest=catthehacker/ubuntu:act-24.04 --container-architecture linux/amd64 --network host
