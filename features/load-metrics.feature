Feature: Load metrics
  As a server admin
  I want request traffic aggregated per route in the console
  So that I can watch the load of a running product without a monitoring stack

  # Console Load screen

  Scenario: The Load screen shows traffic per route
    Given recorded traffic of 30 requests on "GET /todo" with 3 errors at around 80 ms
    And recorded traffic of 10 requests on "POST /todo" with 0 errors at around 20 ms
    And a server admin is signed in as "root@example.com"
    When the admin opens the load screen
    Then the route "GET /todo" is listed with 30 requests and a 10% error rate
    And the route "POST /todo" is listed with 10 requests and a 0% error rate
    And the route "GET /todo" shows a p95 of 98 ms
    And the route "GET /todo" shows an average of 80 ms

  Scenario: The Load screen has an empty state before any traffic is recorded
    Given a server admin is signed in as "root@example.com"
    When the admin opens the load screen
    Then the load screen reports no recorded traffic

  Scenario: The console overview sums the recent traffic
    Given recorded traffic of 30 requests on "GET /todo" with 3 errors at around 80 ms
    And a server admin is signed in as "root@example.com"
    When the admin opens the console
    Then the "metrics" overview is visible on the console
    And the "metrics" console overview shows "30 requests"

  Scenario: A non-admin cannot see the Load screen
    Given the server already has an admin
    And a user is signed in as "bob@example.com"
    When they try to open the load screen
    Then the load screen is not found

  # Prometheus exposition

  Scenario: The metrics exposition reports live counters
    Given a server admin is signed in as "root@example.com"
    When the admin opens the console
    And the admin fetches the metrics exposition
    Then the exposition reports requests on the console route

  Scenario: A non-admin cannot fetch the metrics exposition
    Given the server already has an admin
    And a user is signed in as "bob@example.com"
    When they try to fetch the metrics exposition
    Then the metrics exposition is not found
