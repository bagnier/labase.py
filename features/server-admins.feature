Feature: Server admin management
  As a server admin
  I want the first registered user to bootstrap admin access and to designate further admins
  So that the server always has an owner and administration can be delegated

  # Server admins are the server-wide owners (console access). The very first registered
  # user bootstraps the role; afterwards admins designate or revoke other admins from the
  # console, mirroring the organisation-owner dynamic — including a last-admin guard.
  # The role lives in the JWT, so a designation only takes effect on the target's next sign-in.

  # Bootstrap — the first registered user

  Scenario: The first registered user becomes a server admin
    Given the server has no admin yet
    When "root@example.com" registers
    Then "root@example.com" can open the console

  Scenario: A later registered user is not a server admin
    Given the server has no admin yet
    And "root@example.com" is the first registered user
    When "bob@example.com" registers
    Then "bob@example.com" is refused access to the console

  # Listing admins

  Scenario: An admin lists every user with their admin status
    Given a server admin is signed in as "root@example.com"
    And "bob@example.com" has registered
    When the admin opens the admins page on the console
    Then "root@example.com" appears in the admin list as a server admin
    And "bob@example.com" appears in the admin list as a regular user

  # Designating a new admin

  Scenario: An admin designates another user as a server admin
    Given a server admin is signed in as "root@example.com"
    And "bob@example.com" has registered
    When the admin designates "bob@example.com" as a server admin
    Then "bob@example.com" appears in the admin list as a server admin

  Scenario: A newly designated admin can open the console after signing in again
    Given a server admin is signed in as "root@example.com"
    And "bob@example.com" has registered
    And the admin designates "bob@example.com" as a server admin
    When "bob@example.com" signs in again
    Then "bob@example.com" can open the console

  # Revoking admin rights

  Scenario: An admin revokes another user's server admin rights
    Given a server admin is signed in as "root@example.com"
    And "bob@example.com" is a server admin
    When the admin revokes the server admin rights of "bob@example.com"
    Then "bob@example.com" appears in the admin list as a regular user

  # Last-admin guard

  Scenario: The last server admin cannot be revoked
    Given a server admin is signed in as "root@example.com"
    When the admin revokes the server admin rights of "root@example.com"
    Then the action is forbidden
    And "root@example.com" appears in the admin list as a server admin

  # Authorisation

  Scenario: A non-admin cannot designate server admins
    Given a user is signed in as "bob@example.com"
    When they try to designate "carol@example.com" as a server admin
    Then the console is not found
