Feature: Organisation management
  As an authenticated user
  I want to create and manage organisations
  So that I can collaborate with my team in an isolated workspace

  # Bootstrapping — one org per user, isolated by default

  Scenario: A new user gets a personal organisation on registration
    Given a user is registered with email "alice@example.com" and password "Secret1!"
    Then they have exactly one organisation
    And they are its owner

  Scenario: Two users cannot see each other's organisation
    Given a user is registered with email "alice@example.com" and password "Secret1!"
    And a user is registered with email "bob@example.com" and password "Secret1!"
    When "alice@example.com" views their organisation list
    Then "bob@example.com"'s organisation does not appear in the list

  Scenario: A user cannot own more organisations than allowed
    Given a user is signed in as "alice@example.com" within org "Acme"
    And the maximum owned organisations per user is 1
    When they try to create an organisation named "Beta"
    Then the action is forbidden

  # List

  Scenario: See all organisations they belong to
    Given a user is signed in as "alice@example.com" within org "Acme"
    And they have also joined "Beta Corp" as member "alice@example.com"
    When they view their organisation list
    Then "Acme" appears in their organisation list
    And "Beta Corp" appears in their organisation list

  # Rename

  Scenario: Owner can rename their organisation
    Given a user is signed in as "alice@example.com" within org "Acme"
    When they rename the active organisation to "Acme Corp"
    Then "Acme Corp" appears in their organisation list
    And "Acme" no longer appears in their organisation list

  Scenario: Member cannot rename the organisation
    Given a user is signed in as "alice@example.com" within org "Acme"
    And "bob@example.com" is a member of the org
    And they are signed in as "bob@example.com" in the same org
    When they rename the active organisation to "Hacked Name"
    Then the action is forbidden

  # Access control

  Scenario: The org dashboard requires authentication
    Given the application is running
    When they try to access an org dashboard without signing in
    Then access is denied

  Scenario: An authenticated member can view their org dashboard
    Given a user is signed in
    When they view their org dashboard
    Then the org dashboard is visible

  # Navigate — dashboard as hub

  Scenario: Navigate to an organisation from the dashboard
    Given a user is signed in as "alice@example.com" within org "Acme"
    And they have also joined "Beta Corp" as member "alice@example.com"
    When they view the dashboard
    Then "Acme" appears as a workspace card
    And "Beta Corp" appears as a workspace card
