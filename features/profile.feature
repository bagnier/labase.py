Feature: Profile management
  As an authenticated user
  I want to manage my profile
  So that I can personalise my account

  # Access control

  Scenario: The profile page requires authentication
    When they try to access the profile without signing in
    Then access is denied

  Scenario: From their profile, a signed-in user reaches their org and todos
    Given a user is signed in
    When they view their profile
    Then their org dashboard is reachable from their profile
    And their todo list is reachable from their profile

  @web
  Scenario: The profile is reached from the account area, not the main navigation
    Given a user is signed in
    When they view their profile
    Then their profile is reachable from the account area
    And their profile is not in the main navigation

  # Handle edition

  Scenario: A signed-in user can update their handle
    Given a user is signed in
    When they update their handle to "alice"
    Then their handle is "alice"

  Scenario: A signed-in user cannot set an empty handle
    Given a user is signed in
    And their handle is "alice"
    When they update their handle to ""
    Then the update is rejected
    And their handle is "alice"

  Scenario: A signed-in user cannot change their email
    Given a user is signed in
    When they view their profile
    Then they cannot change their email from their profile
