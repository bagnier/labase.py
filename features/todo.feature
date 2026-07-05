Feature: Todo list
  As an authenticated user
  I want to manage a personal todo list
  So that I can track tasks I need to complete

  Background:
    Given a user is signed in

  Scenario: View the todo list
    Given they have todo items "Buy groceries", "Call dentist", "Read book"
    When they view their todo list
    Then the items appear in order: "Buy groceries", "Call dentist", "Read book"

  Scenario: Add a todo item at the top of the list
    Given they have todo items "Call dentist", "Read book"
    When they add a todo item "Buy groceries"
    Then the items appear in order: "Buy groceries", "Call dentist", "Read book"

  Scenario: Reorder todo items manually
    Given they have todo items "Buy groceries", "Call dentist", "Read book"
    When they move the todo item "Read book" above "Buy groceries"
    Then the items appear in order: "Read book", "Buy groceries", "Call dentist"

  Scenario: Move a todo item to the end of the list
    Given they have todo items "Buy groceries", "Call dentist", "Read book"
    When they move the todo item "Buy groceries" to the end
    Then the items appear in order: "Call dentist", "Read book", "Buy groceries"

  Scenario: Added todo item are not completed
    When they add a todo item "Buy groceries"
    Then "Buy groceries" is shown as not completed

  Scenario: Mark a todo item as done
    Given they have a todo item "Buy groceries"
    When they mark the todo item "Buy groceries" as done
    Then "Buy groceries" is shown as completed

  Scenario: Mark a todo item as not done
    Given they have a todo item "Buy groceries"
    When they mark the todo item "Buy groceries" as done
    When they mark the todo item "Buy groceries" as not done
    Then "Buy groceries" is shown as not completed

  Scenario: Rename a todo item
    Given they have a todo item "Buy groceries"
    When they rename the todo item "Buy groceries" to "Buy vegetables"
    Then "Buy vegetables" appears in their todo list
    And "Buy groceries" no longer appears in their todo list

  Scenario: Delete a todo item
    Given they have a todo item "Buy groceries"
    When they delete the todo item "Buy groceries"
    Then "Buy groceries" no longer appears in their todo list

  Scenario: A per-organisation override caps that organisation's tasks
    Given the "todo" setting "max_items_per_org" is overridden to "1" for their organisation
    And they have a todo item "Only one"
    When they try to add a todo item "One too many"
    Then the action is forbidden
