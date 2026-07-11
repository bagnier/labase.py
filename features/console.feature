Feature: Console domain
  As a server admin
  I want a console to oversee and configure every app
  So that I can monitor the whole server and tune each app's settings

  # The console is server-wide (all organisations confounded), admin-only.
  # It has two surfaces:
  #   - global overviews: each app answers a server-wide query with aggregate metrics
  #   - settings: a per-app key/value store the admin can read and edit

  Scenario: The console requires authentication
    When they try to access the console without signing in
    Then access is denied

  Scenario: A signed-in non-admin user is refused access to the console
    Given the server already has an admin
    And a user is signed in as "bob@example.com"
    When they try to open the console
    Then the console is not found

  Scenario: An admin sees global overviews aggregating every organisation
    Given a server admin is signed in as "root@example.com"
    And a user is signed in as "alice@example.com" within org "Acme"
    And "alice@example.com" has uploaded "report.pdf" of 200 KB to the org
    And a user is signed in as "carol@example.com" within org "Globex"
    And "carol@example.com" has uploaded "plan.txt" of 50 KB to the org
    When the admin opens the console
    Then the "files" overview is visible on the console
    And the "files" console overview shows "2 files"

  Scenario: The console shows an overview card for every app
    Given a server admin is signed in as "root@example.com"
    When the admin opens the console
    Then the "organizations" overview is visible on the console
    And the "users" overview is visible on the console
    And the "files" overview is visible on the console
    And the "learning" overview is visible on the console
    And the "todo" overview is visible on the console
    And the "profile" overview is visible on the console
    And the "public" overview is visible on the console

  Scenario: The users overview reflects registered accounts
    Given a server admin is signed in as "root@example.com"
    When the admin opens the console
    Then the "users" console overview shows "user"

  Scenario: The organizations overview counts organisations across the server
    Given a server admin is signed in as "root@example.com"
    And a user is signed in as "alice@example.com" within org "Acme"
    When the admin opens the console
    Then the "organizations" console overview shows "organisation"

  Scenario: The public overview is wired but has nothing to report yet
    Given a server admin is signed in as "root@example.com"
    When the admin opens the console
    Then the "public" overview is visible on the console
    And the "public" console overview shows "Nothing to report yet"

  Scenario: The files settings page links into Supabase Storage
    Given a server admin is signed in as "root@example.com"
    When the admin opens the settings for the "files" app
    Then a Supabase link pointing at "storage/buckets/org-files" is shown for the "files" app

  Scenario: The users settings page links into Supabase Auth
    Given a server admin is signed in as "root@example.com"
    When the admin opens the settings for the "users" app
    Then a Supabase link pointing at "auth/users" is shown for the "users" app

  Scenario: The to-do settings page links straight to its table in the Supabase editor
    Given a server admin is signed in as "root@example.com"
    When the admin opens the settings for the "todo" app
    Then a Supabase link pointing at "editor/" is shown for the "todo" app

  Scenario: An admin overrides a setting for a single organisation
    Given a server admin is signed in as "root@example.com"
    And a user is signed in as "alice@example.com" within org "Acme"
    When the admin overrides the "todo" setting "max_items_per_org" to "9" for the active org
    Then the "todo" override "max_items_per_org" for the active org is listed as "9"

  Scenario: An admin reads an app's current settings of every type
    Given a server admin is signed in as "root@example.com"
    When the admin opens the settings for the "files" app
    Then the "files" setting "max_upload_mb" is shown as "25"
    And the "files" setting "uploads_enabled" is shown as "true"
    And the "files" setting "welcome_message" is shown as "Welcome aboard"

  Scenario: An admin updates a number setting and it persists
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "files" setting "max_upload_mb" to "50"
    And the admin opens the settings for the "files" app
    Then the "files" setting "max_upload_mb" is shown as "50"

  Scenario: An admin toggles a boolean setting and it persists
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "files" setting "uploads_enabled" to "false"
    And the admin opens the settings for the "files" app
    Then the "files" setting "uploads_enabled" is shown as "false"

  Scenario: An admin updates a string setting and it persists
    Given a server admin is signed in as "root@example.com"
    When the admin sets the "files" setting "welcome_message" to "Hello team"
    And the admin opens the settings for the "files" app
    Then the "files" setting "welcome_message" is shown as "Hello team"

  Scenario: A non-admin cannot change an app's settings
    Given the server already has an admin
    And a user is signed in as "bob@example.com"
    When they try to set the "files" setting "max_upload_mb" to "999"
    Then the console is not found
