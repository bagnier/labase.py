.PHONY: dev up down logs db-start db-stop db-reset migrate test bdd bdd-api bdd-web bdd-all ci install js-build

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

# --- Tests ---
lint:
	uv run ruff check --fix .

format:
	uv run ruff format .

typecheck:
	uv run ty check app/

quality: lint format typecheck

test:
	ENV_FILE=.env.test uv run pytest  # unit + integration + BDD api driver

ci: js-build lint typecheck test bdd-web

coverage:
	ENV_FILE=.env.test uv run pytest --cov=app --cov-report=html
	open htmlcov/index.html

bdd-api:
	ENV_FILE=.env.test uv run pytest tests/bdd/ --driver=api

bdd-web:
	ENV_FILE=.env.test uv run pytest tests/bdd/ --driver=browser

bdd-all: bdd-api bdd-web

bdd: bdd-api
