Feature: Dashboard
  As an authenticated user
  I want to access the dashboard
  So that I can manage my resources

  Scenario: An unauthenticated user cannot access the dashboard
    Given the application is running
    When they try to access the dashboard without signing in
    Then access is denied

  Scenario: The home page is publicly accessible
    Given the application is running
    When they access the home page without signing in
    Then it is publicly accessible
