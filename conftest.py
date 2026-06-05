import os

# Must be set before app modules are imported (Settings is a module-level singleton).
os.environ.setdefault("ENV_FILE", ".env.test")
