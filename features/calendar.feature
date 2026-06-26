Feature: Org calendar
  As a member of an organisation
  I want to keep our shared events on a team calendar
  So that everyone knows what is happening and when

  Background:
    Given a user is signed in as "alice@example.com" within org "Acme"

  # Browse

  Scenario: An empty calendar shows no events
    When they view the calendar
    Then no events appear in the calendar

  Scenario: Events are listed in chronological order by start time
    Given an event "Dentist" from "2026-07-03 10:00" to "2026-07-03 11:00"
    And an event "Standup" from "2026-07-01 09:00" to "2026-07-01 09:30"
    And an event "Review" from "2026-07-02 15:00" to "2026-07-02 16:00"
    When they view the calendar
    Then the events appear in order: "Standup", "Review", "Dentist"

  # Create

  Scenario: Create a timed event
    When they create an event "Project kickoff" from "2026-07-01 14:00" to "2026-07-01 15:00"
    Then "Project kickoff" appears in the calendar

  Scenario: Create an event with a location and a description
    When they create an event "Project kickoff" from "2026-07-01 14:00" to "2026-07-01 15:00" at "Room A" described as "Quarterly planning"
    When they open the event "Project kickoff"
    Then the event shows the location "Room A"
    And the event shows the description "Quarterly planning"

  Scenario: An event must have a title
    When they try to create an event with no title from "2026-07-01 14:00" to "2026-07-01 15:00"
    Then the event is rejected

  Scenario: The end time must be after the start time
    When they try to create an event "Backwards" from "2026-07-01 15:00" to "2026-07-01 14:00"
    Then the event is rejected
    And "Backwards" does not appear in the calendar

  # View

  Scenario: View an event's details
    Given an event "Project kickoff" from "2026-07-01 14:00" to "2026-07-01 15:00"
    When they open the event "Project kickoff"
    Then the event shows the time "1 July 2026, 14:00 – 15:00"

  # Edit

  Scenario: Rename an event
    Given an event "Kickoff" from "2026-07-01 14:00" to "2026-07-01 15:00"
    When they rename the event "Kickoff" to "Project kickoff"
    Then "Project kickoff" appears in the calendar
    And "Kickoff" no longer appears in the calendar

  Scenario: Reschedule an event to a different time
    Given an event "Kickoff" from "2026-07-01 14:00" to "2026-07-01 15:00"
    When they reschedule the event "Kickoff" to start "2026-07-02 10:00" and end "2026-07-02 11:00"
    Then the event "Kickoff" shows the time "2 July 2026, 10:00 – 11:00"

  # Delete

  Scenario: Delete an event
    Given an event "Kickoff" from "2026-07-01 14:00" to "2026-07-01 15:00"
    When they delete the event "Kickoff"
    Then "Kickoff" no longer appears in the calendar

  # Org isolation

  Scenario: A member of a different org cannot see the events
    Given an event "Kickoff" from "2026-07-01 14:00" to "2026-07-01 15:00"
    And "carol@example.com" is a member of "Beta Corp"
    When "carol@example.com" views the calendar
    Then "Kickoff" no longer appears in the calendar

  # Dashboard overview

  Scenario: The calendar overview lists upcoming events on the org dashboard
    Given the current date is "2026-06-26"
    And an event "Kickoff" from "2026-07-01 14:00" to "2026-07-01 15:00"
    And a past event "Retro" from "2026-06-01 10:00" to "2026-06-01 11:00"
    When they view their org dashboard
    Then the "calendar" overview is visible on the dashboard
    And the "calendar" overview shows "1 upcoming"
    And the "calendar" overview lists "Kickoff"

  Scenario: The calendar overview shows an empty state on the dashboard
    When they view their org dashboard
    Then the "calendar" overview is visible on the dashboard
    And the "calendar" overview shows "No upcoming events"

  # Admin console overview

  Scenario: The console counts events across every organisation
    Given an event "Kickoff" from "2026-07-01 14:00" to "2026-07-01 15:00"
    And a server admin is signed in as "root@example.com"
    And a user is signed in as "carol@example.com" within org "Globex"
    And an event "Launch" from "2026-08-01 09:00" to "2026-08-01 10:00"
    When the admin opens the console
    Then the "calendar" overview is visible on the console
    And the "calendar" console overview shows "2 events"
