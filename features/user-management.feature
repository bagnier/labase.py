Feature: User management
  As a server admin
  I want to see, disable and delete server accounts from the console
  So that everyday support does not require Supabase access

  Background:
    Given the server already has an admin
    And a user is registered with email "member@labase.dev" and password "Test1234!"

  # Listing

  Scenario: The accounts screen lists registered users
    Given a server admin is signed in as "root@example.com"
    When the admin opens the accounts screen
    Then the account "member@labase.dev" is listed

  Scenario: A non-admin cannot see the accounts screen
    Given a user is signed in as "bob@example.com"
    When they try to open the accounts screen
    Then the accounts screen is not found

  # Disable / enable

  Scenario: Disabling an account blocks its sign-in
    Given a server admin is signed in as "root@example.com"
    When the admin disables the account "member@labase.dev"
    And a visitor signs in with email "member@labase.dev" and password "Test1234!"
    Then their sign-in is rejected

  Scenario: Re-enabling a disabled account restores sign-in
    Given a server admin is signed in as "root@example.com"
    When the admin disables the account "member@labase.dev"
    And the admin enables the account "member@labase.dev"
    And a visitor signs in with email "member@labase.dev" and password "Test1234!"
    Then they are on their profile page

  # Delete

  Scenario: Deleting an account from the console closes its access
    Given a server admin is signed in as "root@example.com"
    When the admin deletes the account "member@labase.dev"
    Then the account "member@labase.dev" is no longer listed
    When a visitor signs in with email "member@labase.dev" and password "Test1234!"
    Then their sign-in is rejected

  # Admin switch

  Scenario: An admin can turn user management off
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "users" setting "user_management_enabled" to "false"
    And the admin tries to open the accounts screen
    Then the accounts screen is not found
