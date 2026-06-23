"""To-do's public contract. ``settings`` exposes its console-managed settings, read as typed
attributes (``settings.max_items_per_org``) and kept current as admins edit them."""

from app.console.contract.settings import AppSettings

settings = AppSettings("todo")  # group bound + values read in mount(); see integration.py
