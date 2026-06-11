.PHONY: dev up down logs db-start db-stop db-reset migrate test test-e2e test-all serve ci install js-build quality lint format typecheck coverage-erase coverage-xml coverage-html

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

migrate:
	supabase db push

# --- App ---
dev: db-start
	docker compose up --build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f app

# --- Quality ---
lint:
	uv run ruff check --fix .

format:
	uv run ruff format .

typecheck:
	uv run ty check app/

quality: lint format typecheck

# --- Tests ---
test:
	ENV_FILE=.env.test uv run pytest

test-e2e:
	ENV_FILE=.env.test APP_URL=http://127.0.0.1:8002 uv run pytest app/ -k test_scenarios --driver=browser
	ENV_FILE=.env.test APP_URL=http://127.0.0.1:8002 uv run pytest app/*/e2e -p no:asyncio --override-ini="norecursedirs="

coverage-erase:
	uv run coverage erase

coverage-xml:
	uv run coverage xml -o .cov/coverage.xml

coverage-html:
	uv run coverage html -d .cov/html

test-all: coverage-erase test test-e2e coverage-xml

serve:
	-lsof -ti :8002 | xargs kill -9 2>/dev/null; true
	ENV_FILE=.env.test uv run uvicorn app.main:app --port 8002 --reload

ci: js-build lint typecheck coverage-erase test test-e2e coverage-xml
