Feature: Org CMS pages
  As a member of an organisation
  I want to author Markdown pages and let owners publish them
  So that we can share content internally and publicly

  Background:
    Given a user is signed in as "owner@example.com" as owner of "Acme"
    And "alice@example.com" is a member of the org

  Scenario: A member creates a draft page
    Given they are signed in as "alice@example.com" in the same org
    When they create a page titled "Welcome" with content "Hello world"
    Then "Welcome" appears in the pages list
    And the page "welcome" is a draft

  Scenario: The slug is derived from the title on create
    Given they are signed in as "alice@example.com" in the same org
    When they create a page titled "Our Team" with content "the team"
    Then the page "our-team" exists

  Scenario: Opening the new-page form creates no draft
    Given they are signed in as "alice@example.com" in the same org
    When they open the new-page form
    Then the pages list is empty

  Scenario: A member edits the slug of a draft page
    Given they are signed in as "alice@example.com" in the same org
    And a draft page titled "Welcome" with slug "welcome" and content "hi"
    When they change the slug of "welcome" to "home"
    Then the page "home" exists
    And the page "welcome" no longer exists

  Scenario: A member edits a draft page's content
    Given they are signed in as "alice@example.com" in the same org
    And a draft page titled "Welcome" with slug "welcome" and content "old"
    When they update the content of "welcome" to "brand new body"
    Then viewing the page "welcome" shows the text "brand new body"

  Scenario: A member deletes a draft page
    Given they are signed in as "alice@example.com" in the same org
    And a draft page titled "Welcome" with slug "welcome" and content "x"
    When they delete the page "welcome"
    Then "Welcome" no longer appears in the pages list

  Scenario: Markdown body is rendered as HTML, title shown as the heading
    Given they are signed in as "alice@example.com" in the same org
    And a draft page titled "Doc" with slug "doc" and content "- one\n- two"
    When they view the page "doc"
    Then the rendered page shows a heading "Doc"
    And the rendered page shows a list item "one"

  Scenario: The owner publishes a page to members
    Given a draft page titled "Welcome" with slug "welcome" and content "hi"
    When they publish the page "welcome" to members
    Then the page "welcome" is visible to members

  Scenario: A member sees an owner-published page as read-only
    Given a draft page titled "Welcome" with slug "welcome" and content "hi"
    And the owner has published the page "welcome" to members
    And they are signed in as "alice@example.com" in the same org
    When they view the page "welcome"
    Then the rendered page is shown
    And they cannot edit the page "welcome"

  Scenario: The owner publishes a page publicly
    Given a draft page titled "Welcome" with slug "welcome" and content "hi"
    When they publish the page "welcome" publicly
    Then a visitor can view "welcome" under org "Acme"

  Scenario: A visitor cannot view a draft page
    Given a draft page titled "Secret" with slug "secret" and content "hush"
    When a visitor opens "secret" under org "Acme"
    Then they are not allowed to see it

  Scenario: A member cannot publish a page
    Given they are signed in as "alice@example.com" in the same org
    And a draft page titled "Welcome" with slug "welcome" and content "hi"
    When they try to publish the page "welcome" to members
    Then the action is forbidden

  Scenario: The owner's pages list shows every page
    Given a draft page titled "Draft" with slug "draft" and content "d"
    And a page titled "Internal" with slug "internal" published to members
    And a page titled "Public" with slug "public" published publicly
    When they view the pages list
    Then "Draft", "Internal" and "Public" appear in the pages list

  Scenario: A member's pages list shows drafts, member and public pages
    Given a draft page titled "Draft" with slug "draft" and content "d"
    And a page titled "Internal" with slug "internal" published to members
    And a page titled "Public" with slug "public" published publicly
    And they are signed in as "alice@example.com" in the same org
    When they view the pages list
    Then "Draft", "Internal" and "Public" appear in the pages list

  Scenario: A visitor's public listing shows only public pages
    Given a draft page titled "Draft" with slug "draft" and content "d"
    And a page titled "Internal" with slug "internal" published to members
    And a page titled "Public" with slug "public" published publicly
    When a visitor opens the public pages of org "Acme"
    Then only "Public" is listed

  Scenario: The pages overview appears on the org dashboard
    Given a draft page titled "Welcome" with slug "welcome" and content "hi"
    When they view their org dashboard
    Then the "pages" overview is visible on the dashboard

  Scenario: Pages stay private to their organisation
    Given a draft page titled "Roadmap" with slug "roadmap" and content "internal"
    And a page titled "Announce" with slug "announce" published to members
    And "carol@example.com" is a member of "Beta Corp"
    When "carol@example.com" views their pages list
    Then "Roadmap" is not in that pages list
    And "Announce" is not in that pages list
