Feature: Page navigation
  As an owner
  I want to select which pages appear in the site navigation and in what order
  So that readers can browse published content easily

  Background:
    Given a user is signed in as "owner@example.com" as owner of "Acme"
    And a page titled "About" with slug "about" published publicly
    And a page titled "Team" with slug "team" published to members
    And a draft page titled "Secret" with slug "secret" and content "x"

  Scenario: Owner adds a page to the navigation
    When they open the navigation manager
    And they add "About" to the navigation
    Then "About" appears in the navigation

  Scenario: Owner removes a page from the navigation
    Given "About" is in the navigation
    When they open the navigation manager
    And they remove "About" from the navigation
    Then "About" no longer appears in the navigation

  Scenario: Owner reorders navigation items
    Given "About" is in the navigation at position 1
    And "Team" is in the navigation at position 2
    When they open the navigation manager
    And they move "Team" above "About" in the navigation
    Then the navigation shows "Team" then "About"

  Scenario: Draft pages are not available for the navigation
    When they open the navigation manager
    Then "Secret" is not listed as a navigation candidate

  Scenario: Navigation added via the manager appears in the page sidebar
    When they open the navigation manager
    And they add "About" to the navigation
    And they view the page "about"
    Then the page navigation shows a link to "About"

  Scenario: A member sees the navigation when viewing a page
    Given "About" is in the navigation
    And "Team" is in the navigation
    And they are signed in as "alice@example.com" in the same org
    When they view the page "about"
    Then the page navigation shows a link to "About"
    And the page navigation shows a link to "Team"

  Scenario: A visitor sees only public pages in the navigation
    Given "About" is in the navigation
    And "Team" is in the navigation
    When a visitor opens "about" under org "Acme"
    Then the page navigation shows a link to "About"
    But the page navigation does not show a link to "Team"
