.PHONY: dev up down logs db-start db-stop db-reset db-seed migrate schema schema-supabase test test-e2e test-all ci install js-build quality lint format typecheck coverage-erase coverage-xml coverage-html cert letsencrypt audit upgrade

# --- Setup ---
install:
	uv sync --all-groups
	pre-commit install
	@test -f .env || cp .env.example .env
	npm install
	$(MAKE) js-build

js-build:
	npm run build

# --- Local Supabase ---
db-start:
	supabase start

db-stop:
	supabase stop

db-reset:
	supabase db reset

db-seed:
	PYTHONPATH=. uv run python scripts/seed.py

migrate:
	supabase db push

schema:
	tbls doc --rm-dist
	uv run python scripts/tbls_postprocess.py

schema-supabase:
	tbls doc --rm-dist --config .tbls.supabase.yml

# --- App ---
dev: db-start
	docker compose -f docker/docker-compose.yml up --build

up:
	docker compose -f docker/docker-compose.yml up -d

down:
	docker compose -f docker/docker-compose.yml down

logs:
	docker compose -f docker/docker-compose.yml logs -f app

# --- Quality ---
lint:
	uv run ruff check --fix .

format:
	uv run ruff format .

typecheck:
	uv run ty check app/

audit:
	uv run pip-audit

upgrade:
	cp uv.lock /tmp/uv.lock.bak
	cp pyproject.toml /tmp/pyproject.toml.bak
	python3 scripts/upgrade.py relax
	uv lock --upgrade
	python3 scripts/upgrade.py repin

quality: lint format typecheck

# --- Tests ---
test:
	ENV_FILE=.env.test uv run pytest

test-e2e:
	ENV_FILE=.env.test uv run pytest app/ -k test_scenarios --driver=browser --no-cov

coverage-erase:
	uv run coverage erase

coverage-xml:
	uv run coverage xml -o .cov/coverage.xml

coverage-html:
	uv run coverage html -d .cov/html

test-all: coverage-erase test test-e2e coverage-xml

cert:
	openssl req -x509 -newkey rsa:4096 -keyout dev.key -out dev.crt -days 365 -nodes -subj '/CN=localhost'

letsencrypt:
	certbot certonly --standalone -d $(DOMAIN) --agree-tos --non-interactive
	@echo "Certs at /etc/letsencrypt/live/$(DOMAIN)/"

ci: js-build lint typecheck audit coverage-erase test test-e2e coverage-xml
