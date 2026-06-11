Feature: Organisation member management
  As an organisation owner
  I want to manage who belongs to my organisation
  So that I can control access and delegate administration

  Background:
    Given a user is signed in as "alice@example.com" as owner of "Acme"

  # List members

  Scenario: Owner sees all members of the organisation
    Given "bob@example.com" is a member of the org
    When they view the member list
    Then "alice@example.com" appears in the member list with role "owner"
    And "bob@example.com" appears in the member list with role "member"

  # Change role

  Scenario: Owner can promote a member to owner
    Given "bob@example.com" is a member of the org
    When they set the role of "bob@example.com" to "owner"
    Then "bob@example.com" appears in the member list with role "owner"

  Scenario: Member cannot change roles
    Given "bob@example.com" is a member of the org
    And they are signed in as "bob@example.com" in the same org
    When they set the role of "alice@example.com" to "member"
    Then the action is forbidden

  # Remove member

  Scenario: Owner can remove a member
    Given "bob@example.com" is a member of the org
    When they remove "bob@example.com" from the org
    Then "bob@example.com" does not appear in the member list

  Scenario: Member cannot remove another member
    Given "bob@example.com" is a member of the org
    And "carol@example.com" is a member of the org
    And they are signed in as "bob@example.com" in the same org
    When they remove "carol@example.com" from the org
    Then the action is forbidden

  # Last owner guard

  Scenario: Owner cannot be removed if they are the only owner
    When they remove "alice@example.com" from the org
    Then the action is forbidden

  Scenario: Owner cannot be demoted if they are the only owner
    When they set the role of "alice@example.com" to "member"
    Then the action is forbidden

  # Leave

  Scenario: Member can leave an organisation
    Given "bob@example.com" is a member of the org
    And they are signed in as "bob@example.com" in the same org
    When they leave the organisation
    Then "bob@example.com" does not appear in the member list

  Scenario: Last owner cannot leave the organisation
    When they leave the organisation
    Then the action is forbidden
