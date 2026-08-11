# Remote development — Claude Code on the web

Drive the repo from a phone via a "Claude Code on the web" session. The cloud VM is fresh on every session (Ubuntu 24.04, 4 vCPU / 16 GB / 30 GB) and loads only the versioned repo — never the local `~/.claude`. Parity with local therefore rests on `CLAUDE.md`, `.claude/settings.json`, `.mcp.json` and `.claude/skills/`, all versioned.

## Cloud environment configuration (once, in the web UI)

Cloud icon above the message box → repo environment.

1. **Setup script**: `make cloud-setup` (uv sync + npm + js-build + Playwright). Runs as root on the first session, cached ~7 days.
2. **Environment variables** (`.env` format): the `SUPABASE_*` of the remote development project (see below) + dev knobs (`LOG_DEBUG=true`, `RATE_LIMIT_ENABLED=false`, `COOKIES_SECURE=false`).
3. **Network access: Custom** + `*.supabase.co` and any external domain used. GitHub and MCP connectors go through separate proxies.

## Database: remote Supabase (recommended)

The VM has no Supabase CLI and reinstalling the Docker stack on every cache expiry is heavy. For phone work, point `SUPABASE_*` at a **dedicated development Supabase project** (disposable, no sensitive data) rather than starting a local Supabase.

> [!warning] No secrets store
> The cloud environment's environment variables are readable by anyone using it. Put only the keys of a disposable dev project there, never a production secret.

Alternative (all-local in the VM): `docker compose` is available, but you then have to install the Supabase CLI in `cloud-setup`, start the stack and run `make env`. Heavier, reserved for long sessions.

## Sandbox constraints

- **Playwright**: browsers not pre-installed — `cloud-setup` installs them. If you skip browser tests, drive the app via the **JSON API** (Bearer token, `/organizations`, `/{org}/todos`…); `@web` scenarios are skipped by the API driver.
- **Services**: Postgres 16 and Redis 7 are installed but **must be started** on every session (the cache stores files, not processes). Same for any `docker compose` stack.
- **Filesystem**: each session is a fresh clone; the cache is a snapshot taken after the setup script.
- **Resources**: ~16 GB of RAM — an over-hungry job may be killed.
