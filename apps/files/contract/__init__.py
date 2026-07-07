"""Files' public contract. ``settings`` exposes its console-managed settings, read as typed
attributes (``settings.max_upload_mb``) and kept current as admins edit them."""

from apps.shared.settings import AppSettings

settings = AppSettings()  # declaration bound + values read in mount(); see integration.py
