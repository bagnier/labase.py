from fastapi import FastAPI

from app.auth.contract import integration as auth
from app.console.contract import integration as console
from app.files.contract import integration as files
from app.health.contract import integration as health
from app.integration import host
from app.learning.contract import integration as learning
from app.organizations.contract import integration as organizations
from app.profile.contract import integration as profile
from app.public.contract import integration as public
from app.shared import integration as shared
from app.todo.contract import integration as todo

app = FastAPI(title="labase")

# Composition root: each context declares everything from its contract/integration.register —
# mounts its routers, subscribes to events, answers collaboration queries, claims its URL slugs.
# Listed in dependency order (auth → org → org-scoped apps → cross-cutting → infra); routing
# precedence needs no special ordering since reserved slugs keep org handles off these paths.
# Event subscriptions are wired unconditionally; seeding is gated at its emission site
# (app.registration) so BDD scenarios under the test schema start from an empty org.
for _ctx in (shared, auth, organizations, files, todo, learning, profile, console, public, health):
    _ctx.register(app, host)
