Feature: Authentication
  As a user
  I want to authenticate
  So that I can access protected resources

  Scenario: Login page is accessible
    Given the app is running
    Then the login page is accessible

  Scenario: Login with invalid credentials fails
    Given the app is running
    When I log in with email "invalid@example.com" and password "wrongpassword"
    Then my login attempt is rejected

  Scenario: Accessing dashboard without auth is forbidden
    Given the app is running
    When I visit the dashboard without logging in
    Then I am not authorized

  Scenario: Register page is accessible
    Given the app is running
    Then the register page is accessible
