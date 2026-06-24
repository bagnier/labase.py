"""Pages' public contract. ``settings`` exposes its console-managed settings, read as typed
attributes (``settings.default_visibility``) and kept current as admins edit them."""

from apps.settings.contract.settings import AppSettings

settings = AppSettings("pages")  # group bound + values read in mount(); see integration.py
