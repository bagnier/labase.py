Feature: Authentication
  As a user
  I want to manage my account access
  So that I can securely use the application

  Background:
    Given a user is registered with email "test@labase.dev" and password "Test1234!"

  Scenario: A visitor can initiate sign-in
    When a visitor starts to sign in
    Then the sign-in form is available

  Scenario: A visitor can initiate registration
    When a visitor starts to register
    Then the registration form is available

  Scenario: A registered user can sign in
    When a visitor signs in with email "test@labase.dev" and password "Test1234!"
    Then they are on their profile page

  Scenario: Sign-in with wrong credentials is rejected
    When a visitor signs in with email "unknown@example.com" and password "wrongpassword"
    Then their sign-in is rejected

  Scenario: An unauthenticated user cannot access their profile
    When they try to access their profile without signing in
    Then access is denied

  Scenario: A visitor can create an account with a new email
    When a visitor registers with a new email and password "Test1234!"
    Then they are asked to verify their email

  Scenario: Registration with an already taken email is rejected
    When a visitor registers with "test@labase.dev" and password "Test1234!"
    Then their registration is rejected with message "An account already exists"

  Scenario: Registration with a weak password is rejected
    When a visitor registers with a new email and password "toto"
    Then their registration is rejected with message "Password too weak"

  Scenario: A signed-in user can sign out
    Given a visitor signs in with email "test@labase.dev" and password "Test1234!"
    And they are on their profile page
    When they sign out
    Then they are redirected to sign-in

  Scenario: A user resets a forgotten password
    When they request a password reset for "test@labase.dev"
    And they set a new password "NewSecret1!" using the emailed reset link
    And a visitor signs in with email "test@labase.dev" and password "NewSecret1!"
    Then they are on their profile page

  Scenario: A signed-in user changes their password
    Given a visitor signs in with email "test@labase.dev" and password "Test1234!"
    When they change their password from "Test1234!" to "Changed1234!"
    And they sign out
    And a visitor signs in with email "test@labase.dev" and password "Changed1234!"
    Then they are on their profile page
