from apps.settings.contract.settings import AppSettings

ORG_PREFIX = "/{org_handle}"  # all org-scoped routes mount under this handle segment

settings = AppSettings("organizations")  # group bound + values read in mount(); see integration.py
