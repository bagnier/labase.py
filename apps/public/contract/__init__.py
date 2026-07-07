"""Public app's contract. ``settings`` exposes its console-managed settings."""

from apps.shared.settings import AppSettings

settings = AppSettings()  # declaration bound + values read in mount(); see integration.py
