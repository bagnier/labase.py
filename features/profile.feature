Feature: Profile management
  As an authenticated user
  I want to manage my profile
  So that I can personalise my account

  # Access control

  Scenario: The profile page requires authentication
    Given the application is running
    When they try to access the profile without signing in
    Then access is denied

  Scenario: The profile page shows org links after sign-in
    Given a user is signed in
    When they view their profile
    Then there is a link to their org dashboard
    And there is a link to their todo list

  Scenario: The profile is accessible via the user footer
    Given a user is signed in
    When they view their profile
    Then there is a link to the profile in the user footer
    And there is no profile link in the navigation

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
    Then their email is shown as read-only
