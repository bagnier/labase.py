Feature: Org dashboard overviews
  As a member of an organisation
  I want each app to surface an overview on the org dashboard
  So that I get a glance of my todos, files and learning without leaving the dashboard

  # The dashboard composes one overview per org-scoped app, auto-discovered.
  # Each overview has a web view (shown on the page) and structured data (REST only).

  Background:
    Given a user is signed in as "alice@example.com" within org "Acme"

  Scenario: The dashboard shows the to-do overview with open and done counts
    Given they have a todo item "Write the report"
    And they have a todo item "Call the client"
    And they mark the todo item "Call the client" as done
    When they view their org dashboard
    Then the "todo" overview is visible on the dashboard
    And the "todo" overview shows "1 open"
    And the "todo" overview shows "1 done"
    And the "todo" overview lists "Write the report"

  Scenario: The dashboard shows the files overview with count and total size
    Given "alice@example.com" has uploaded "report.pdf" of 200 KB to the org
    And "alice@example.com" has uploaded "notes.txt" of 50 KB to the org
    When they view their org dashboard
    Then the "files" overview is visible on the dashboard
    And the "files" overview shows "2 files"
    And the "files" overview lists "report.pdf"

  Scenario: The dashboard shows the learning overview with the org's decks
    Given the org has a learning deck "Capitales" with 2 cards
    When they view their org dashboard
    Then the "learning" overview is visible on the dashboard
    And the "learning" overview shows "1 deck"
    And the "learning" overview shows "2 cards"

  Scenario: An app with no data still shows its overview in an empty state
    When they view their org dashboard
    Then the "todo" overview is visible on the dashboard
    And the "todo" overview shows "No tasks yet"
    And the "files" overview is visible on the dashboard
    And the "files" overview shows "No files yet"
