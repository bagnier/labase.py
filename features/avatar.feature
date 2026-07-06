Feature: Profile avatar
  As a signed-in user
  I want a profile photo
  So that my account is recognisable at a glance

  Background: running
    Given the application is running
    And a user is registered with email "face@labase.dev" and password "Test1234!"

  Scenario: Uploading an avatar shows it on the profile
    Given a visitor signs in with email "face@labase.dev" and password "Test1234!"
    When they upload a PNG image as their avatar
    Then their avatar is shown on their profile

  Scenario: Only images are accepted as avatars
    Given a visitor signs in with email "face@labase.dev" and password "Test1234!"
    When they upload a text file as their avatar
    Then the avatar upload is rejected

  Scenario: An admin can turn avatars off
    Given a visitor signs in with email "face@labase.dev" and password "Test1234!"
    And a server admin is signed in as "root@example.com"
    When the admin sets the "profile" setting "avatar_enabled" to "false"
    Then the avatar option is not offered
