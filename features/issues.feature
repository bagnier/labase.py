Feature: Error tracking
  As a server admin
  I want captured errors grouped into issues with a lifecycle
  So that thousands of occurrences read as a short, triageable list

  Background:
    Given a captured error "ValueError: capture boom" with 3 occurrences

  Scenario: Captured errors appear grouped in the console
    Given a server admin is signed in as "root@example.com"
    When the admin opens the issues screen
    Then the issue "ValueError: capture boom" is listed with status "new" and 3 occurrences

  Scenario: The console overview counts unresolved issues
    Given a server admin is signed in as "root@example.com"
    When the admin opens the console
    Then the "issues" overview is visible on the console
    And the "issues" console overview shows "1 unresolved"

  Scenario: Resolving an issue
    Given a server admin is signed in as "root@example.com"
    When the admin resolves the issue "ValueError: capture boom"
    Then the issue "ValueError: capture boom" is listed with status "resolved" and 3 occurrences

  Scenario: An occurrence from another version reopens a resolved issue as regressed
    Given a server admin is signed in as "root@example.com"
    When the admin resolves the issue "ValueError: capture boom"
    And another occurrence of "ValueError: capture boom" arrives from version "v2"
    Then the issue "ValueError: capture boom" is listed with status "regressed" and 4 occurrences

  Scenario: Ignored issues stay ignored when new occurrences arrive
    Given a server admin is signed in as "root@example.com"
    When the admin ignores the issue "ValueError: capture boom"
    And another occurrence of "ValueError: capture boom" arrives from version "v2"
    Then the issue "ValueError: capture boom" is listed with status "ignored" and 4 occurrences

  Scenario: The issue detail shows the stack and its occurrences
    Given a server admin is signed in as "root@example.com"
    When the admin opens the issue "ValueError: capture boom"
    Then the stack trace and 3 occurrences are shown

  Scenario: A non-admin cannot see the issues screen
    Given the server already has an admin
    And a user is signed in as "bob@example.com"
    When they try to open the issues screen
    Then the issues screen is not found
