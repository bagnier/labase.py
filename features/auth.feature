Feature: Authentication
  As a user
  I want to authenticate via the API
  So that I can access protected resources

  Scenario: Login page is accessible
    Given the app is running
    When I GET "/auth/login"
    Then the response status is 200
    And the response contains "Connexion"

  Scenario: Login with invalid credentials returns 401
    Given the app is running
    When I POST "/auth/login" with form data:
      | field    | value               |
      | email    | invalid@example.com |
      | password | wrongpassword       |
    Then the response status is 401
    And the response contains "invalide"

  Scenario: Accessing dashboard without auth redirects to login
    Given the app is running
    When I GET "/dashboard" without auth
    Then the response status is 401

  Scenario: Register page is accessible
    Given the app is running
    When I GET "/auth/register"
    Then the response status is 200
    And the response contains "Créer un compte"
