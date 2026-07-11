Feature: Passkeys (WebAuthn)
  As a security-conscious user
  I want to sign in with a passkey instead of a password
  So that phishing-resistant sign-in is one console switch away

  # Both drivers run the real GoTrue ceremony. The browser driver executes
  # navigator.credentials for real: the e2e server sits on a pinned origin
  # (rp_origins) and a Playwright CDP virtual authenticator answers the prompts.
  # The API driver uses the software authenticator in tests/e2e/drivers/webauthn.py.

  Background: running
    Given the application is running
    And the server already has an admin

  Scenario: Passkey sign-in stays hidden until enabled
    Then the sign-in page does not offer passkey sign-in

  Scenario: Enrolling a passkey and signing in with it
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "users" setting "passkeys_enabled" to "true"
    Given a user is signed in as "peggy@example.com"
    When they add a passkey
    Then their passkey is listed on their profile
    And the sign-in page offers passkey sign-in
    When they sign out
    And a visitor signs in with their passkey
    Then they are on their profile page
