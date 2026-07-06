Feature: Handle option
  As a server admin
  I want the public @handle feature to be switchable
  So that products that do not need identities can hide it

  # The handle behaviour itself is covered by profile.feature; this feature
  # covers only the admin switch (2026-07-06 decision: every advanced-auth
  # option gets its own declared setting).

  Background: running
    Given the application is running
    And a user is registered with email "plain@labase.dev" and password "Test1234!"

  Scenario: An admin can turn handles off
    Given a visitor signs in with email "plain@labase.dev" and password "Test1234!"
    And a server admin is signed in as "root@example.com"
    When the admin sets the "profile" setting "handle_enabled" to "false"
    Then the handle option is not offered
