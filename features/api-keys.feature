Feature: API keys
  As an organisation owner
  I want machine credentials scoped to my organisation
  So that integrations can call the JSON API without a browser session

  Background:
    Given a user is signed in as "alice@example.com" as owner of "Acme"

  Scenario: Owner creates a key and a machine uses it against the JSON API
    When they create an API key named "CI robot"
    Then the API key secret is revealed once
    And the key authenticates a sessionless request to the organisation's todos

  Scenario: A revoked key stops authenticating
    Given they have created an API key named "CI robot"
    When they revoke the API key "CI robot"
    Then the key no longer authenticates sessionless requests

  Scenario: An API key is pinned to its organisation
    Given they have created an API key named "CI robot"
    And a user is signed in as "carol@example.com" as owner of "Globex"
    Then the key is rejected on the active organisation

  Scenario: Members cannot manage API keys
    Given "bob@example.com" is a member of the org
    And they are signed in as "bob@example.com" in the same org
    When they try to open the API keys page
    Then the action is forbidden
