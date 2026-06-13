Feature: Console domain
  As an admin
  I want the console to be protected
  So that only authenticated admins can access it

  Scenario: The console requires authentication
    Given the application is running
    When they try to access the console without signing in
    Then access is denied
