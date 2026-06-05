# labase.py

Base SaaS en Python, full open-source, s'appuyant sur Supabase pour la base de données, l'authentification et le stockage de fichiers.

## Stack

| Couche | Choix | Raison |
|--------|-------|--------|
| **Web framework** | FastAPI | Async natif, Pydantic V2, OpenAPI auto-généré |
| **Rendu HTML** | Jinja2 + HTMX | SSR sans build JS, dynamisme SPA-like via échanges de fragments |
| **Styling** | Tailwind CSS | CDN Play en dev, CLI en prod |
| **ORM** | SQLModel (sur SQLAlchemy 2.x) | Modèles Pydantic + SQLAlchemy, async, bien intégré avec Postgres |
| **Auth + Storage** | supabase-py | SDK officiel Supabase, JWT en cookie HTTPOnly |
| **Base de données** | Supabase (Postgres) | DB hébergée, RLS, triggers, Storage, Auth intégrés |
| **Migrations** | Supabase CLI (SQL pur) | Migrations versionnées, intégration Studio, contrôle total |
| **Serveur ASGI** | Uvicorn | Standard de facto pour FastAPI |
| **Gestion des dépendances** | uv | Ultra-rapide, lockfile, gestion Python intégrée |
| **Python** | 3.14 | Dernière version stable |

### Outils qualité

| Outil | Usage |
|-------|-------|
| **ruff** | Linting + formatting |
| **ty** | Type checking (Astral, Rust) |
| **pyright** | Type checking (Microsoft, en CI) |
| **pytest + pytest-asyncio** | Tests unitaires et d'intégration |
| **behave** | Tests BDD fonctionnels (Gherkin) |

## Architecture

Le projet démarre en **CRUD simple** et peut évoluer vers une architecture hexagonale domaine par domaine, sans réécriture.

```
Mode CRUD (défaut) :
  router → repository (SQLAlchemy) → DB

Mode hexagonal (opt-in par domaine) :
  router → service (use case) → repository (adapter) → DB
                              ↘ supabase_client (adapter) → Storage / Auth
```

- `app/routers/` — routes HTTP, logique de présentation uniquement
- `app/repositories/` — accès données, interface simple sur SQLAlchemy
- `app/services/` — use cases métier (vide au départ, à remplir quand la logique grossit)
- `app/auth/` — authentification via Supabase Auth (JWT en cookie HTTPOnly)

## Choix structurants

**Supabase comme couche infrastructure** — supabase-py est cantonné à l'auth et au storage. Les requêtes métier passent par SQLAlchemy directement sur Postgres, ce qui préserve la flexibilité (requêtes complexes, transactions, pgvector…).

**SSR avec HTMX plutôt qu'une SPA séparée** — un seul repo, un seul déploiement, pas de CORS, auth simplifiée côté serveur. Adapté à un SaaS dont l'interface est principalement du CRUD.

**Migrations SQL pures** — les migrations Supabase CLI restent lisibles et versionnées en SQL brut. La migration initiale pose la table `profiles` liée à `auth.users` avec RLS et un trigger d'auto-création à l'inscription.

**Tests BDD fonctionnels** — les scénarios Gherkin (`features/`) pilotent l'API HTTP réelle via `httpx.AsyncClient`. Pas de mock réseau : l'app tourne vraiment, ce qui valide les routes, la sérialisation et les réponses HTTP de bout en bout.

## Structure

```
labase.py/
├── app/
│   ├── main.py              # FastAPI app + lifespan
│   ├── config.py            # Settings (pydantic-settings, .env)
│   ├── database.py          # SQLAlchemy async engine + session
│   ├── supabase_client.py   # Clients supabase-py (anon + admin)
│   ├── auth/                # Login, logout, register + middleware JWT
│   ├── models/              # SQLModel table models
│   ├── repositories/        # Accès données (adapter pattern)
│   ├── services/            # Use cases métier (à alimenter)
│   └── templates/           # Jinja2 (base, auth, dashboard)
├── features/                # BDD Gherkin + steps behave
├── tests/                   # Fixtures pytest
├── supabase/migrations/     # SQL versionnés (Supabase CLI)
├── Dockerfile               # Image production
├── Dockerfile.dev           # Image dev avec hot-reload
├── docker-compose.yml       # App + connexion Supabase local
└── Makefile                 # Commandes courantes
```

## Démarrage local

### Prérequis

- [uv](https://docs.astral.sh/uv/)
- [Docker](https://www.docker.com/)
- [Supabase CLI](https://supabase.com/docs/guides/cli)

### Installation

```bash
# Cloner et installer les dépendances
uv sync --all-groups

# Copier et remplir les variables d'environnement
cp .env.example .env
```

### Lancer Supabase en local

```bash
make db-start
# Récupérer les clés affichées par `supabase status` et les mettre dans .env
```

### Appliquer les migrations

```bash
make migrate
```

### Lancer l'application

```bash
make dev          # via Docker Compose (hot-reload)
# ou directement :
uv run uvicorn app.main:app --reload
```

L'app est disponible sur [http://localhost:8000](http://localhost:8000).

## Commandes

```bash
make dev          # Docker Compose en mode dev (hot-reload)
make up           # Docker Compose en arrière-plan
make down         # Arrêter les conteneurs
make logs         # Logs de l'app

make db-start     # Démarrer Supabase local
make db-stop      # Arrêter Supabase local
make db-reset     # Réinitialiser la DB locale
make migrate      # Appliquer les migrations (supabase db push)

make lint         # ruff check
make format       # ruff format
make typecheck    # ty check
make test         # pytest
make bdd          # behave (tests BDD fonctionnels)
```
