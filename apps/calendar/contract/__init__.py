"""Calendar's public contract. ``settings`` exposes its console-managed settings, read as
typed attributes and kept current as admins edit them."""

from apps.settings.contract.settings import AppSettings

settings = AppSettings("calendar")  # group bound + values read in mount(); see integration.py
