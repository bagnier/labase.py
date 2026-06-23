"""Learning's public contract. ``settings`` exposes its console-managed settings, read as typed
attributes (``settings.daily_review_limit``) and kept current as admins edit them."""

from app.console.contract.settings import AppSettings

settings = AppSettings("learning")  # group bound + values read in mount(); see integration.py
