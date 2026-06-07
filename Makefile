.PHONY: dev up down logs db-start db-stop db-reset migrate test test-e2e test-all serve ci install js-build quality lint format typecheck

# --- Front-end assets ---
js-build:
	npm install
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
	ENV_FILE=.env.test uv run pytest --ignore=tests/e2e

test-e2e:
	ENV_FILE=.env.test APP_URL=http://127.0.0.1:8002 uv run pytest tests/e2e/test_features.py --driver=browser
	ENV_FILE=.env.test APP_URL=http://127.0.0.1:8002 uv run pytest tests/e2e/test_ui_structure.py -p no:asyncio

test-all: test test-e2e

serve:
	ENV_FILE=.env.test uv run uvicorn app.main:app --port 8002 --reload

ci: js-build lint typecheck test-all
