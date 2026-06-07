Feature: Dashboard
  As an authenticated user
  I want to access the dashboard
  So that I can manage my resources

  Scenario: An unauthenticated user cannot access the dashboard
    Given the application is running
    When they try to access the dashboard without signing in
    Then access is denied

  Scenario: The dashboard links to the todo list
    Given a user is signed in
    When they view the dashboard
    Then there is a link to their todo list

  Scenario: The home page is publicly accessible
    Given the application is running
    When they access the home page without signing in
    Then it is publicly accessible
