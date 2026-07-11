Feature: Public domain
  As a visitor
  I want public pages to be accessible without authentication
  So that I can discover the platform

  Scenario: The home page is publicly accessible
    When they access the home page without signing in
    Then it is publicly accessible
