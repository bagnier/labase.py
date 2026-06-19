Feature: Organisation invitations
  As an organisation owner
  I want to invite people to join my organisation by email
  So that they can collaborate in my workspace

  Background:
    Given a user is signed in as "alice@example.com" as owner of "Acme"

  # Send invitation

  Scenario: Owner invites a new user as member
    When they invite "bob@example.com" to the organisation with role "member"
    Then an invitation for "bob@example.com" appears in the pending invitations list with role "member"

  Scenario: Member cannot send invitations
    Given "bob@example.com" is a member of the org
    And they are signed in as "bob@example.com" in the same org
    When they invite "carol@example.com" to the organisation with role "member"
    Then the action is forbidden

  Scenario: Cannot invite someone who is already a member
    Given "bob@example.com" is a member of the org
    When they invite "bob@example.com" to the organisation with role "member"
    Then the action fails with error "already a member"

  Scenario: Cannot invite the same email twice while a pending invitation exists
    When they invite "bob@example.com" to the organisation with role "member"
    And they invite "bob@example.com" to the organisation with role "member"
    Then the action fails with error "invitation already pending"

  # List pending invitations

  Scenario: Owner sees all pending invitations
    When they invite "bob@example.com" to the organisation with role "member"
    And they invite "carol@example.com" to the organisation with role "member"
    And they view the pending invitations list
    Then an invitation for "bob@example.com" appears in the pending invitations list with role "member"
    And an invitation for "carol@example.com" appears in the pending invitations list with role "member"

  # Revoke invitation

  Scenario: Owner can revoke a pending invitation
    When they invite "bob@example.com" to the organisation with role "member"
    And they revoke the invitation for "bob@example.com"
    Then "bob@example.com" does not appear in the pending invitations list

  Scenario: Member cannot revoke an invitation
    Given "bob@example.com" is a member of the org
    And they are signed in as "bob@example.com" in the same org
    When they invite "carol@example.com" to the organisation with role "member"
    Then the action is forbidden

  # Accept invitation

  Scenario: New user registers through the invitation link and joins the organisation
    When they invite "bob@example.com" to the organisation with role "member"
    And "bob@example.com" registers through the invitation link and accepts it
    Then "bob@example.com" appears in the member list with role "member"
    And "bob@example.com" does not appear in the pending invitations list

  Scenario: Invited user accepts an invitation and joins the organisation
    When they invite "bob@example.com" to the organisation with role "member"
    And "bob@example.com" accepts the invitation
    Then "bob@example.com" appears in the member list with role "member"
    And "bob@example.com" does not appear in the pending invitations list

  # Token security

  Scenario: Accepted invitation token redirects to the organisation
    When they invite "bob@example.com" to the organisation with role "member"
    And "bob@example.com" accepts the invitation
    And "bob@example.com" follows the invitation link again
    Then they are redirected to the organisation dashboard

  Scenario: Revoked invitation cannot be accepted
    When they invite "bob@example.com" to the organisation with role "member"
    And they revoke the invitation for "bob@example.com"
    And "bob@example.com" tries to accept the revoked invitation
    Then the action fails with error "invitation not found or already used"
