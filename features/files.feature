Feature: Org file storage
  As an authenticated member of an organisation
  I want to upload and share files with my team
  So that we can centralise our documents in one place

  Background:
    Given a user is signed in

  Scenario: Upload a file to the org
    When they upload a file "rapport.pdf" to the org
    Then "rapport.pdf" appears in the file list

  Scenario: List org files
    Given they have uploaded "rapport.pdf" to the org
    When they view the file list
    Then "rapport.pdf" appears in the file list

  Scenario: Download a file
    Given they have uploaded "rapport.pdf" to the org
    When they download the file "rapport.pdf"
    Then the download succeeds

  Scenario: Delete a file
    Given they have uploaded "rapport.pdf" to the org
    When they delete the file "rapport.pdf"
    Then "rapport.pdf" no longer appears in the file list
