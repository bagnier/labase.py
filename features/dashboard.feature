Feature: Domain access control
  As a user of the platform
  I want each domain to enforce its own access rules
  So that public pages are open and protected pages require authentication

  # ── Public domain ─────────────────────────────────────────────────────────

  Scenario: The home page is publicly accessible
    Given the application is running
    When they access the home page without signing in
    Then it is publicly accessible

  # ── Profile domain ────────────────────────────────────────────────────────

  Scenario: The profile page requires authentication
    Given the application is running
    When they try to access the profile without signing in
    Then access is denied

  Scenario: The profile page shows org links after sign-in
    Given a user is signed in
    When they view the profile
    Then there is a link to their org dashboard

  # ── Org dashboard domain ──────────────────────────────────────────────────

  Scenario: The org dashboard requires authentication
    Given the application is running
    When they try to access an org dashboard without signing in
    Then access is denied

  Scenario: An authenticated member can view their org dashboard
    Given a user is signed in
    When they view their org dashboard
    Then the org dashboard is visible

  # ── Console domain ────────────────────────────────────────────────────────

  Scenario: The console requires authentication
    Given the application is running
    When they try to access the console without signing in
    Then access is denied
