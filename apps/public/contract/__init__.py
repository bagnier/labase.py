"""Public app's contract. ``settings`` exposes its console-managed settings."""

from apps.settings.contract.settings import AppSettings

settings = AppSettings("public")  # group bound + values read in mount(); see integration.py
