# Pulling base improvements into a product — `make upgrade-base`

A product starts as a clone of labase, then lives its own life. This is the
protocol that lets it keep benefiting from base fixes and bricks — the
equivalent of `jhipster upgrade`, built on plain git because the whole history
of the base is already in the product's repo.

## One-time setup (per product clone)

```bash
git remote add base <url-of-labase.py>
```

## Each upgrade

```bash
make upgrade-base       # fetch base, branch upgrade-base-<date>, merge base/main
# resolve conflicts using the ownership map below
make ci                 # both drivers + perf smoke arbitrate the merge
git switch main && git merge upgrade-base-<date>
```

`BASE_REMOTE` / `BASE_BRANCH` are overridable (`make upgrade-base BASE_BRANCH=v2`).

## Ownership map — where conflicts come from and how to resolve them

| Area | Owner | On conflict |
| --- | --- | --- |
| `apps/shared/**`, `tests/e2e/drivers/**`, `scripts/**`, `Makefile`, `docker/**` | **base** — a product should never edit these; if it must, upstream the change to labase instead | take base's side, re-apply the local patch on top (and question it) |
| `apps/<your-contexts>/**` | **product** | base never touches them — no conflicts |
| demo apps (`todo/`, `files/`, `learning/`, `calendar/`) | deleted in products | modify/delete conflicts: keep them deleted (`git rm`) |
| `apps/main.py` | **shared** — the one file both sides edit by design | keep base's mounts, keep your mounts; order stays: shared → auth → your apps |
| `pyproject.toml` | shared | union of dependencies; base wins on tool configs (`[tool.*]`), incl. the import-linter contracts you extend (never relax) |
| `supabase/migrations/**` | append-only, both | never edit an applied migration; conflicts mean both added files — keep both, timestamps order them |
| `features/**`, per-context tests | follow their context's owner | demo features go with the demos |
| `README.md`, branding, `.env*` | **product** | keep yours; cherry-pick doc improvements manually |

Two rules make the merges stay small:

1. **Products never edit base-owned files.** Anything you need there is either
   a declared surface the base already offers (settings, events, mounts,
   NavItems, ConsoleLinks) or a patch worth sending back to labase.
2. **Upgrade often.** A quarterly merge is an afternoon; a two-year merge is a
   rewrite. The dated branches keep an auditable trail of each sync.
