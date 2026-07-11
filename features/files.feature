Feature: Org file storage
  As an authenticated member of an organisation
  I want to upload, manage, and share files with my team
  So that we can centralise our documents and collaborate efficiently

  Background:
    Given a user is signed in as "alice@example.com" within org "Acme"

  # Upload

  Scenario: Upload a file to the org
    When they upload "rapport.pdf" to the org
    Then "rapport.pdf" appears in the file list

  Scenario: Upload is rejected when the file exceeds 50 MB
    Given the org has a file size limit of 50 MB
    When they upload a file of 51 MB to the org
    Then the action is rejected

  Scenario: Upload is rejected when it would exceed the org storage quota
    Given the organisation storage quota is 1 MB
    When they upload a file of 2 MB to the org
    Then the action is rejected

  Scenario: Upload is rejected for a filename with path traversal
    When they upload a file with filename "../../../etc/passwd"
    Then the upload is rejected

  Scenario: Upload with XSS characters in filename is sanitized and succeeds
    When they upload a file with filename "<img onerror=alert(1)>.txt"
    Then "_img_onerror_alert_1__.txt" appears in the file list

  # List

  Scenario: File list shows all members' files with metadata
    Given the current date is "2026-06-10"
    And "bob@example.com" is a member of the org
    And "bob@example.com" has uploaded "budget.xlsx" of 9 KB to the org
    When they view the file list
    Then "budget.xlsx" appears in the file list with size "9 KB", uploaded by "bob@example.com" on "2026-06-10"

  # Download

  Scenario: Download a file
    Given they have uploaded "rapport.pdf" to the org
    When they download "rapport.pdf"
    Then the download succeeds

  # Delete

  Scenario: Delete own file
    Given they have uploaded "rapport.pdf" to the org
    When they delete the file "rapport.pdf"
    Then "rapport.pdf" no longer appears in the file list

  Scenario: Member cannot delete another member's file
    Given they are a member of the org
    And "bob@example.com" is a member of the org
    And "bob@example.com" has uploaded "budget.xlsx" to the org
    When they delete the file "budget.xlsx"
    Then the action is forbidden
    And "budget.xlsx" appears in the file list

  Scenario: Owner can delete any file in the org
    Given "bob@example.com" is a member of the org
    And "bob@example.com" has uploaded "budget.xlsx" to the org
    And they are an owner of the org
    When they delete the file "budget.xlsx"
    Then "budget.xlsx" no longer appears in the file list

  # Rename

  Scenario: Rename own file
    Given they have uploaded "rapport.pdf" to the org
    When they rename the file "rapport.pdf" to "rapport-v2.pdf"
    Then "rapport-v2.pdf" appears in the file list
    And "rapport.pdf" no longer appears in the file list

  Scenario: Member cannot rename another member's file
    Given they are a member of the org
    And "bob@example.com" is a member of the org
    And "bob@example.com" has uploaded "budget.xlsx" to the org
    When they rename the file "budget.xlsx" to "budget-final.xlsx"
    Then the action is forbidden

  # Org isolation

  Scenario: A member of a different org cannot see the files
    Given "carol@example.com" is a member of "Beta Corp"
    And they have uploaded "rapport.pdf" to the org
    When "carol@example.com" views the file list
    Then "rapport.pdf" no longer appears in the file list

  # Sharing — link accessible to anyone who has it

  Scenario: An org member can use a share link
    Given "bob@example.com" is a member of the org
    And they have uploaded "rapport.pdf" to the org
    And they have generated a share link for "rapport.pdf"
    When "bob@example.com" accesses the share link
    Then the download succeeds

  Scenario: A member of a different org can use a share link
    Given "carol@example.com" is a member of "Beta Corp"
    And they have uploaded "rapport.pdf" to the org
    And they have generated a share link for "rapport.pdf"
    When "carol@example.com" accesses the share link
    Then the download succeeds

  Scenario: Anyone with the share link can download the file
    Given they have uploaded "rapport.pdf" to the org
    And they have generated a share link for "rapport.pdf"
    When a non-member accesses the share link
    Then the download succeeds
