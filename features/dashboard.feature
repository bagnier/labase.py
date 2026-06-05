Feature: Dashboard
  As an authenticated user
  I want to access the dashboard
  So that I can manage my resources

  Scenario: Dashboard requires authentication
    Given the app is running
    When I visit the dashboard without logging in
    Then I am not authorized

  Scenario: Home page is publicly accessible
    Given the app is running
    When I visit the home page without logging in
    Then the page loads successfully
