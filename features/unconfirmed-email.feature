Feature: Unconfirmed email verification
  As a user who registered but never verified their mailbox
  I want a clear explanation and a way to get the confirmation email again
  So that I am not stuck in front of a generic sign-in error

  Background: running
    Given the application is running
    And an unconfirmed user is registered with email "pending@labase.dev" and password "Test1234!"

  Scenario: An unconfirmed sign-in is blocked with a clear message
    When a visitor signs in with email "pending@labase.dev" and password "Test1234!"
    Then their sign-in is rejected with message "Please verify your email before signing in"
    And they are offered to resend the confirmation email

  Scenario: Resending really delivers a fresh confirmation email
    When a visitor signs in with email "pending@labase.dev" and password "Test1234!"
    And they ask for the confirmation email to be resent to "pending@labase.dev"
    Then a confirmation link is delivered to "pending@labase.dev"

  Scenario: Following the emailed link unlocks sign-in
    When a visitor signs in with email "pending@labase.dev" and password "Test1234!"
    And they ask for the confirmation email to be resent to "pending@labase.dev"
    And they confirm their address using the link emailed to "pending@labase.dev"
    And they sign out
    And a visitor signs in with email "pending@labase.dev" and password "Test1234!"
    Then they are on their profile page

  Scenario: An admin can turn confirmation resend off
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "users" setting "resend_confirmation_enabled" to "false"
    And a visitor signs in with email "pending@labase.dev" and password "Test1234!"
    Then their sign-in is rejected with message "Please verify your email before signing in"
    And they are not offered to resend the confirmation email
