"""Pages' public contract. ``settings`` exposes its console-managed settings, read as typed
attributes (``settings.default_visibility``) and kept current as admins edit them."""

from apps.shared.settings import AppSettings

settings = AppSettings()  # declaration bound + values read in mount(); see integration.py
