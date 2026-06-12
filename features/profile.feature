Feature: Profile management
  As an authenticated user
  I want to manage my profile
  So that I can personalise my account

  Background:
    Given a user is signed in

  Scenario: A signed-in user can update their display name
    When they update their display name to "Alice Wonderland"
    Then their display name is "Alice Wonderland"

  Scenario: A signed-in user cannot set an empty display name
    Given their display name is "Alice Wonderland"
    When they update their display name to ""
    Then the update is rejected
    And their display name is still "Alice Wonderland"

  Scenario: A signed-in user cannot change their email
    When they view their profile
    Then their email is shown as read-only
