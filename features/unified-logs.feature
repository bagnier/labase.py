Feature: Unified logs
  As a server admin
  I want every log source in one filterable, exportable timeline
  So that I can trace what happened across the server without juggling three screens

  # The unified log gathers three sources into one append-only stream:
  #   - http     : the structlog firehose (failed requests — dead links & 5xx), gated by the log level
  #   - business : the business-events journal (contributes regardless of the log level)
  #   - error    : occurrences of tracked errors (contributes regardless of the log level)
  # Every entry carries org_id / user_id / request_id, so the timeline filters and correlates.
  # The screen is server-wide and admin-only, like the rest of the console.

  # Unified timeline

  Scenario: The logs screen gathers every source in one timeline
    Given a business event "todo.created" from org "Acme"
    And a request log entry "request.finished" from org "Acme"
    And an error log entry "ValueError: boom" from org "Acme"
    And a server admin is signed in as "root@example.com"
    When the admin opens the logs screen
    Then the entry "todo.created" is listed with source "business"
    And the entry "request.finished" is listed with source "http"
    And the entry "ValueError: boom" is listed with source "error"

  Scenario: The logs screen shows an empty state when nothing matches the filter
    Given the current date is "2026-06-26"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs to dates from "2020-01-01" to "2020-01-02"
    Then the logs screen reports no entries

  # Filtering

  Scenario: An admin filters the logs by organisation
    Given a business event "todo.created" from org "Acme"
    And a business event "todo.deleted" from org "Globex"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs by org "Acme"
    Then the entry "todo.created" is listed
    And the entry "todo.deleted" is not listed

  Scenario: An admin filters the logs by source
    Given a business event "todo.created" from org "Acme"
    And a request log entry "request.finished" from org "Acme"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs by source "business"
    Then the entry "todo.created" is listed
    And the entry "request.finished" is not listed

  Scenario: An admin filters the logs by app
    Given a business event "todo.created" from org "Acme"
    And a business event "calendar.event_created" from org "Acme"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs by app "todo"
    Then the entry "todo.created" is listed
    And the entry "calendar.event_created" is not listed

  Scenario: An admin filters the logs by level
    Given a request log entry "request.finished" at level "info" from org "Acme"
    And an error log entry "ValueError: boom" at level "error" from org "Acme"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs by level "error"
    Then the entry "ValueError: boom" is listed
    And the entry "request.finished" is not listed

  Scenario: An admin searches the logs by free text
    Given a business event "todo.created" from org "Acme"
    And a request log entry "request.finished" from org "Acme"
    And a server admin is signed in as "root@example.com"
    When the admin searches the logs for "todo.created"
    Then the entry "todo.created" is listed
    And the entry "request.finished" is not listed

  Scenario: An admin filters the logs by user
    Given a business event "todo.created" attributed to "alice@example.com"
    And a business event "todo.deleted" attributed to "bob@example.com"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs by user "alice@example.com"
    Then the entry "todo.created" is listed
    And the entry "todo.deleted" is not listed

  Scenario: An admin filters the logs by date range
    Given the current date is "2026-06-26"
    And a business event "todo.created" from org "Acme" recorded on "2026-06-20"
    And a business event "todo.deleted" from org "Acme" recorded on "2026-06-25"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs to dates from "2026-06-24" to "2026-06-26"
    Then the entry "todo.deleted" is listed
    And the entry "todo.created" is not listed

  # Correlation

  Scenario: One request correlates its request, event and error entries
    Given request "r-100" in org "Acme" recorded a request log, a business event "todo.created", and a captured error "ValueError: boom"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs by request "r-100"
    Then the request entry, the business event "todo.created", and the error "ValueError: boom" are all listed

  # Sorting

  Scenario: Entries are listed newest first by default
    Given the current date is "2026-06-26"
    And a business event "todo.created" from org "Acme" recorded on "2026-06-24"
    And a business event "todo.deleted" from org "Acme" recorded on "2026-06-26"
    And a server admin is signed in as "root@example.com"
    When the admin opens the logs screen
    Then "todo.deleted" is listed above "todo.created"

  Scenario: An admin sorts the entries by a column
    Given the current date is "2026-06-26"
    And a business event "todo.created" from org "Acme" recorded on "2026-06-24"
    And a business event "todo.deleted" from org "Acme" recorded on "2026-06-26"
    And a server admin is signed in as "root@example.com"
    When the admin sorts the logs by "event" ascending
    Then "todo.created" is listed above "todo.deleted"

  # Export

  Scenario: An admin exports the filtered logs as NDJSON
    Given a business event "todo.created" from org "Acme"
    And a business event "todo.deleted" from org "Globex"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs by org "Acme"
    And the admin exports the filtered logs as NDJSON
    Then the export contains "todo.created"
    And the export does not contain "todo.deleted"

  Scenario: An admin exports the filtered logs as CSV
    Given a business event "todo.created" from org "Acme"
    And a server admin is signed in as "root@example.com"
    When the admin exports the filtered logs as CSV
    Then the CSV export has a header row and lists "todo.created"

  # Tunable log level

  Scenario: The log level defaults to WARNING
    Given a server admin is signed in as "root@example.com"
    When the admin opens the settings for the "logs" app
    Then the "logs" setting "log_level" is shown as "WARNING"

  Scenario: An admin lowers the log level and it persists
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "logs" setting "log_level" to "INFO"
    And the admin opens the settings for the "logs" app
    Then the "logs" setting "log_level" is shown as "INFO"

  # Contribution independent of the log level

  Scenario: Business events reach the unified log even at WARNING level
    Given the log level is "WARNING"
    And a business event "todo.created" is recorded in org "Acme"
    And a server admin is signed in as "root@example.com"
    When the admin opens the logs screen
    Then the entry "todo.created" is listed with source "business"

  # Activity graph

  Scenario: The activity graph sums each source over time
    # Current day sits a day after the seeded events so the admin's own sign-in
    # (a business event dated "now") lands in a different bucket than the one asserted.
    Given the current date is "2026-06-27"
    And a business event "todo.created" from org "Acme" recorded on "2026-06-26"
    And a business event "todo.deleted" from org "Acme" recorded on "2026-06-26"
    And a request log entry "request.finished" from org "Acme" recorded on "2026-06-26"
    And an error log entry "ValueError: boom" from org "Acme" recorded on "2026-06-26"
    And a server admin is signed in as "root@example.com"
    When the admin opens the logs screen
    Then the activity for "2026-06-26" shows 2 business, 1 http, and 1 error

  Scenario: The activity graph re-buckets by the selected grain
    # Current month sits after the seeded event so the admin's own sign-in business
    # event (dated "now") falls in a later month than the one asserted.
    Given the current date is "2026-07-01"
    And a business event "todo.created" from org "Acme" recorded on "2026-06-26"
    And a server admin is signed in as "root@example.com"
    When the admin views the activity by "month"
    Then the activity for "2026-06" shows 1 business, 0 http, and 0 error

  Scenario: The activity graph follows the organisation filter
    Given the current date is "2026-06-26"
    And a business event "todo.created" from org "Acme" recorded on "2026-06-26"
    And a business event "todo.deleted" from org "Globex" recorded on "2026-06-26"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs by org "Acme"
    Then the activity for "2026-06-26" shows 1 business, 0 http, and 0 error

  Scenario: The graph and table stay in sync on the selected period
    # Current day sits just past the filter window so the admin's own sign-in business
    # event (dated "now") is excluded from both the table and the graph.
    Given the current date is "2026-06-27"
    And a business event "todo.created" from org "Acme" recorded on "2026-06-22"
    And a business event "todo.deleted" from org "Acme" recorded on "2026-06-26"
    And a server admin is signed in as "root@example.com"
    When the admin filters the logs to dates from "2026-06-25" to "2026-06-26"
    Then the entry "todo.deleted" is listed
    And the entry "todo.created" is not listed
    And the activity for "2026-06-26" shows 1 business, 0 http, and 0 error

  # Recent window

  Scenario: The firehose window only shows recent lines
    Given the current date is "2026-06-26"
    And a request log entry "request.finished" from org "Acme" recorded on "2026-06-23"
    And a request log entry "request.finished" from org "Acme" recorded on "2026-06-26"
    And a server admin is signed in as "root@example.com"
    When the admin opens the logs screen
    Then 1 http entry is listed

  # Access

  Scenario: A non-admin cannot open the logs screen
    Given the server already has an admin
    And a user is signed in as "bob@example.com"
    When they try to open the logs screen
    Then the logs screen is not found
