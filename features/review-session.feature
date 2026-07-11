Feature: Review session

  A learner interacts with a review card in order to learn a new concept

  Review sessions are meant to present only a subset of the cards.
  Ending the review session before marking every card leaves the marked or unmarked cards in the same state.

  Background:
    Given the deck "Python Basics" is made of the following cards:
      | ID    | Question                                    | Answer                         |
      | PY001 | How do you declare a variable in Python?    | variable_name = value          |
      | PY002 | What is the syntax of a for loop in Python? | for element in sequence:       |
      | PY003 | How do you define a function in Python?     | def function_name(parameters): |
    And "Alice" wants to learn the deck "Python Basics"

  Scenario: A deck to learn is fully accessible from the start
    When "Alice" looks at today's cards
    Then "Alice" sees 3 cards to learn

  Scenario: A deck to learn is personal to each user
    When "Bob" looks at today's cards
    Then "Bob" sees no card to learn

  Scenario: Cards are presented in deck order
    When "Alice" starts a review session
    Then "Alice" sees the cards in this order:
      | ID    | Level |
      | PY001 | 0     |
      | PY002 | 0     |
      | PY003 | 0     |

  Scenario: Cards are presented grouped by deck
    Given the deck "Advanced Python" is made of the following cards:
      | ID    | Question                             | Answer           |
      | PYA01 | What is a decorator in Python?       | @decorator_name  |
      | PYA02 | How do you define a class in Python? | class ClassName: |
    And "Alice" wants to learn the deck "Advanced Python"
    And "Alice" looks at today's cards
    When "Alice" starts a review session
    Then "Alice" sees the cards in this order:
      | ID    | Level |
      | PY001 | 0     |
      | PY002 | 0     |
      | PY003 | 0     |
      | PYA01 | 0     |
      | PYA02 | 0     |

  Scenario: A card marked as learned is removed from today's cards
    Given "Alice" looks at today's cards
    And "Alice" starts a review session
    When "Alice" reveals the answer of the card "PY001" and sees "variable_name = value"
    And "Alice" marks the card "PY001" as learned
    Then "Alice" sees 2 cards to learn
    And "Alice" sees the card "PY002" asking the question "What is the syntax of a for loop in Python?"

  Scenario: A card marked to review is removed from today's cards
    Given "Alice" looks at today's cards
    And "Alice" starts a review session
    When "Alice" reveals the answer of the card "PY001" and sees "variable_name = value"
    And "Alice" marks the card "PY001" as to review
    Then "Alice" sees 2 cards to learn
    And "Alice" sees the card "PY002" asking the question "What is the syntax of a for loop in Python?"

  Scenario: A review session can be interrupted without consequence
    Given "Alice" starts a review session
    And "Alice" marks the card "PY001" as learned
    When "Alice" starts a review session
    Then "Alice" sees the card "PY002" asking the question "What is the syntax of a for loop in Python?"
