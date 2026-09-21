Feature: Two-factor authentication (TOTP)
  As a security-conscious user
  I want sign-in to require a code from my authenticator app
  So that a stolen password is not enough to enter my account

  Background:
    Given a user is registered with email "vault@labase.dev" and password "Test1234!"

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

  Scenario: The password alone does not open a session once enrolled
    Given a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they enrol an authenticator app
    When they sign out
    And a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they skip the authenticator code and open their profile with the pending sign-in
    Then access is denied

  Scenario: The password alone does not open a session dressed as an impersonation
    Given a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they enrol an authenticator app
    When they sign out
    And a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they skip the authenticator code and claim to be an admin impersonating themselves
    Then access is denied

  Scenario: A wrong authenticator code is rejected
    Given a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they enrol an authenticator app
    When they sign out
    And a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they enter the authenticator code "000000"
    Then the authenticator code is rejected

  # Interaction with other profile changes

  Scenario: A user with two-factor enabled can still change their password and email
    Given a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they enrol an authenticator app
    When they sign out
    And a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And they enter a valid authenticator code
    And they change their password from "Test1234!" to "Changed1234!"
    And they request to change their email to "vaulted@labase.dev" using password "Changed1234!"
    Then they are told a confirmation email is on its way

  # Admin switch

  Scenario: An admin can turn two-factor off
    Given a visitor signs in with email "vault@labase.dev" and password "Test1234!"
    And a server admin is signed in as "root@example.com"
    When the admin sets the "users" setting "two_factor_enabled" to "false"
    Then the two-factor option is not offered to "vault@labase.dev"
