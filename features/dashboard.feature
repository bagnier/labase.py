Feature: Dashboard
  As an authenticated user
  I want to access the dashboard
  So that I can manage my resources

  Scenario: Dashboard requires authentication
    Given the app is running
    When I GET "/dashboard" without auth
    Then the response status is 401

  Scenario: Root redirects to dashboard
    Given the app is running
    When I GET "/" without auth
    Then the response status is 307
