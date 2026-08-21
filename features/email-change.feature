Feature: Email change
  As a signed-in user
  I want to change my sign-in email, confirmed from the new mailbox
  So that my account follows my current address

  Background:
    Given a user is registered with email "moving@labase.dev" and password "Test1234!"

  # Requesting

  Scenario: Requesting an email change sends a confirmation to the new address
    Given a visitor signs in with email "moving@labase.dev" and password "Test1234!"
    When they request to change their email to "moved@labase.dev" using password "Test1234!"
    Then they are told a confirmation email is on its way
    And an email change link is delivered to "moved@labase.dev"

  Scenario: The current password is required to change the email
    Given a visitor signs in with email "moving@labase.dev" and password "Test1234!"
    When they request to change their email to "moved@labase.dev" using password "wrong-pass"
    Then the email change is rejected

  # Confirming

  Scenario: Following the emailed link switches the account to the new address
    Given a visitor signs in with email "moving@labase.dev" and password "Test1234!"
    When they request to change their email to "moved@labase.dev" using password "Test1234!"
    And they confirm the change using the link emailed to "moved@labase.dev"
    And they sign out
    And a visitor signs in with email "moved@labase.dev" and password "Test1234!"
    Then they are on their profile page

  # Admin switch

  Scenario: An admin can turn email change off
    Given a visitor signs in with email "moving@labase.dev" and password "Test1234!"
    And a server admin is signed in as "root@example.com"
    When the admin sets the "profile" setting "email_change_enabled" to "false"
    Then the email change option is not offered to "moving@labase.dev"
