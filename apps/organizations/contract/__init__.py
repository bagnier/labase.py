from apps.shared.settings import AppSettings

ORG_PREFIX = "/{org_handle}"  # all org-scoped routes mount under this handle segment

settings = AppSettings()  # declaration bound + values read in mount(); see integration.py
