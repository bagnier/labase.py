.PHONY: dev up down logs db-start db-stop db-reset migrate test bdd

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
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run ty check app/

test:
	ENV_FILE=.env.test uv run pytest

coverage:
	ENV_FILE=.env.test uv run pytest --cov=app --cov-report=html
	open htmlcov/index.html

bdd:
	ENV_FILE=.env.test uv run behave features/
