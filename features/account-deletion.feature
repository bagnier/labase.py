Feature: Account deletion
  As a user leaving the product
  I want to delete my account myself
  So that I do not depend on support to close it

  Background:
    Given a user is registered with email "leaving@labase.dev" and password "Test1234!"

  Scenario: Deleting the account signs the user out and closes access
    Given a visitor signs in with email "leaving@labase.dev" and password "Test1234!"
    When they delete their account confirming with password "Test1234!"
    Then they are redirected to sign-in
    When a visitor signs in with email "leaving@labase.dev" and password "Test1234!"
    Then their sign-in is rejected

  Scenario: The password is required to delete the account
    Given a visitor signs in with email "leaving@labase.dev" and password "Test1234!"
    When they delete their account confirming with password "wrong-pass"
    Then the account deletion is rejected
    When a visitor signs in with email "leaving@labase.dev" and password "Test1234!"
    Then they are on their profile page

  Scenario: An admin can turn account deletion off
    Given a visitor signs in with email "leaving@labase.dev" and password "Test1234!"
    And a server admin is signed in as "root@example.com"
    When the admin sets the "profile" setting "account_deletion_enabled" to "false"
    Then the account deletion option is not offered

  # Alice is its only owner, so her departure would leave it unmanageable: it is reaped whole
  # rather than left ownerless, and Bob — still a member — sees it gone from his own list.
  Scenario: Deleting the last owner's account reaps the organisation for its members too
    Given a user is signed in as "alice@example.com" as owner of "Acme"
    And they invite "bob@example.com" to the organisation with role "member"
    And "bob@example.com" accepts the invitation
    When "alice@example.com" deletes their account
    Then "Acme" no longer appears in "bob@example.com"'s organisation list
