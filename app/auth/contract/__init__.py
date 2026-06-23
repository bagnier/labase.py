"""Auth's public contract. ``settings`` exposes its console-managed settings, read as typed
attributes (``settings.session_ttl_seconds``) and kept current as admins edit them."""

from app.console.contract.settings import AppSettings

settings = AppSettings("users")  # group bound + values read in mount(); see integration.py
