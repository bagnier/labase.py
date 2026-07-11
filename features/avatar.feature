Feature: Profile avatar
  As a signed-in user
  I want a profile photo
  So that my account is recognisable at a glance

  Background:
    Given a user is signed in as "face@labase.dev"

  Scenario: Uploading an avatar shows it on the profile
    When they upload a PNG image as their avatar
    Then their avatar is shown on their profile

  Scenario: Only images are accepted as avatars
    When they upload a text file as their avatar
    Then the avatar upload is rejected

  Scenario: An admin can turn avatars off
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "profile" setting "avatar_enabled" to "false"
    Then the avatar option is not offered
