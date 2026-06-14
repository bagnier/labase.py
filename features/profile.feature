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

  # Profile edition

  Scenario: A signed-in user can update their display name
    Given a user is signed in
    When they update their display name to "Alice Wonderland"
    Then their display name is "Alice Wonderland"

  Scenario: A signed-in user cannot set an empty display name
    Given a user is signed in
    And their display name is "Alice Wonderland"
    When they update their display name to ""
    Then the update is rejected
    And their display name is still "Alice Wonderland"

  Scenario: A signed-in user cannot change their email
    Given a user is signed in
    When they view their profile
    Then their email is shown as read-only
