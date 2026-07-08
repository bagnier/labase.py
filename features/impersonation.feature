Feature: User impersonation
  As a server admin
  I want to view the app as a specific user
  So that I can reproduce what they see when supporting them

  Scenario: An admin impersonates a user and stops
    Given a user is signed in as "alice@example.com" within org "Acme"
    And a server admin is signed in as "root@example.com"
    When the admin impersonates "alice@example.com"
    Then they are viewing the app as "alice@example.com"
    And the impersonation banner is visible
    When they stop impersonating
    Then they are back on their admin account "root@example.com"

  Scenario: An admin impersonates a user straight from the accounts list
    Given a user is signed in as "alice@example.com" within org "Acme"
    And a server admin is signed in as "root@example.com"
    When the admin impersonates "alice@example.com" from the accounts list
    Then they are viewing the app as "alice@example.com"
    And the impersonation banner is visible

  Scenario: A non-admin cannot impersonate
    Given the server already has an admin
    And a user is signed in as "bob@example.com"
    When they try to impersonate "carol@example.com"
    Then the impersonation is refused
