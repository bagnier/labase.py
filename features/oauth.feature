Feature: OAuth social sign-in
  As a product owner
  I want Google and GitHub sign-in driven by console switches
  So that social login ships without touching code

  # The provider round-trip itself cannot be tested sincerely against real
  # Google/GitHub — it is covered by unit tests plus the manual checklist in
  # docs/oauth.md. These scenarios cover what the app owns: the switches, the
  # buttons, and the hand-off to the authorization server.

  Background:
    Given the server already has an admin

  Scenario: OAuth stays hidden until a provider is switched on
    When a visitor starts to sign in
    Then the sign-in page does not offer "github" sign-in

  Scenario: Enabling a provider offers it on the sign-in page
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "users" setting "oauth_github_enabled" to "true"
    And a visitor starts to sign in
    Then the sign-in page offers "github" sign-in

  Scenario: Starting the flow hands the browser to the authorization server
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "users" setting "oauth_github_enabled" to "true"
    And a visitor starts the "github" sign-in
    Then they are redirected to the OAuth authorization for "github"
