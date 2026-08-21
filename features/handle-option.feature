Feature: Handle option
  As a server admin
  I want the public @handle feature to be switchable
  So that products that do not need identities can hide it

  # The handle behaviour itself is covered by profile.feature; this feature
  # covers only the admin switch (2026-07-06 decision: every advanced-auth
  # option gets its own declared setting).

  Scenario: An admin can turn handles off
    Given a user is signed in as "plain@labase.dev"
    And a server admin is signed in as "root@example.com"
    When the admin sets the "profile" setting "handle_enabled" to "false"
    Then the handle option is not offered to "plain@labase.dev"
