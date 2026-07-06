Feature: Two-factor authentication (TOTP)
  As a security-conscious user
  I want sign-in to require a code from my authenticator app
  So that a stolen password is not enough to enter my account

  Background: running
    Given the application is running
    And a user is registered with email "vault@labase.dev" and password "Test1234!"

  # Enrolment

  Scenario: Enrolling an authenticator app from the profile
    Given a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    When they enrol an authenticator app
    Then their profile shows two-factor as enabled

  # Sign-in challenge

  Scenario: Sign-in asks for the authenticator code once enrolled
    Given a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they enrol an authenticator app
    When they sign out
    And a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    Then they are asked for their authenticator code
    When they enter a valid authenticator code
    Then they are on their profile page

  Scenario: A wrong authenticator code is rejected
    Given a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they enrol an authenticator app
    When they sign out
    And a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they enter the authenticator code "000000"
    Then the authenticator code is rejected

  # Admin switch

  Scenario: An admin can turn two-factor off
    Given a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And a server admin is signed in as "root@example.com"
    When the admin sets the "users" setting "two_factor_enabled" to "false"
    Then the two-factor option is not offered
