Feature: Account deletion
  As a user leaving the product
  I want to delete my account myself
  So that I do not depend on support to close it

  Background:
    # Otherwise "leaving@labase.dev" would be the first-ever registrant and bootstrap into the
    # server's sole admin — tripping the last-admin guard below on a deletion these scenarios
    # mean to be ordinary.
    Given the server already has an admin
    And a user is registered with email "leaving@labase.dev" and password "Test1234!"

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
    Then the account deletion option is not offered to "leaving@labase.dev"

  # Alice is its only owner, so her departure would leave it unmanageable: it is reaped whole
  # rather than left ownerless, and Bob — still a member — sees it gone from his own list.
  Scenario: Deleting the last owner's account reaps the organisation for its members too
    Given a user is signed in as "alice@example.com" as owner of "Acme"
    And they invite "bob@example.com" to the organisation with role "member"
    And "bob@example.com" accepts the invitation
    When "alice@example.com" deletes their account
    Then "Acme" no longer appears in "bob@example.com"'s organisation list

  # The sole server admin's own deletion is the last-admin guard's other door: revoking through
  # the console is one path, deleting the account outright is the other, and both must refuse.
  # Clears the Background's seeded admin first — this scenario needs "root@example.com" to be
  # the *sole* admin, not one of two.
  Scenario: The sole server admin cannot delete their own account
    Given the server has no admin yet
    And a server admin is signed in as "root@example.com"
    When they delete their account confirming with password "Test1234!"
    Then the account deletion is rejected
    And "root@example.com" can open the console

  # A disabled account keeps its admin role in GoTrue but cannot sign in, so it must not count
  # as the safety net that lets the server's one remaining acting admin delete their own account.
  Scenario: A disabled admin does not cover for the last acting admin's own deletion
    Given the server has no admin yet
    And a server admin is signed in as "root@example.com"
    And "bob@example.com" is a server admin
    When the admin disables the account "bob@example.com"
    And they delete their account confirming with password "Test1234!"
    Then the account deletion is rejected
    And "root@example.com" can open the console
