Feature: spaced repetition

  a learner is offered spaced repetition in order to periodically review a concept

  The Leitner method does not explicitly specify a procedure for missed review days.
  However, based on the principles of the method and common spaced-repetition practices, here is what is generally recommended:

  - Immediate resumption: As soon as possible, resume reviews starting with the cards that were due on the missed day.
  - No penalty: Do not penalize cards by automatically demoting them. Having missed a day does not necessarily mean the information has been forgotten.
  - Adjusting dates: Shift future review dates for cards not reviewed, bringing them forward by a day or setting them to the current day.
  - Prioritization: If the number of cards to review becomes too large because of the missed day, prioritize cards at lower levels and those not reviewed for the longest time.
  - Flexibility: Allow the user to "catch up" on missed reviews over several days if needed, rather than forcing everything into a single session.
  - Keeping the algorithm: Continue applying the normal card progression or regression rules based on the user's answers, regardless of the delay.

  additional rules not covered by a scenario:
  - Reviews happen every day, including weekends
  - Each card is handled atomically during an interrupted session

  Background:
    Given the deck "Python Basics" is made of the following cards:
      | ID    | Question                                                     | Answer                                                                                                     | Resource                                                                                                  |
      | PY001 | How do you declare a variable in Python?                     | variable_name = value                                                                                      | [Python Documentation](https://docs.python.org/3/tutorial/introduction.html#using-python-as-a-calculator) |
      | PY002 | What is the syntax of a for loop in Python?                  | for element in sequence:                                                                                    | [For loops](https://docs.python.org/3/tutorial/controlflow.html#for-statements)                           |
      | PY003 | How do you define a function in Python?                      | def function_name(parameters):                                                                             | [Defining functions](https://docs.python.org/3/tutorial/controlflow.html#defining-functions)              |
      | PY004 | What is the operator for integer division in Python?         | //                                                                                                         | [Numeric types](https://docs.python.org/3/library/stdtypes.html#numeric-types-int-float-complex)          |
      | PY005 | How do you create a list in Python?                          | my_list = [element1, element2, element3]                                                                   | [Lists](https://docs.python.org/3/tutorial/introduction.html#lists)                                       |
      | PY006 | Which method is used to add an element to the end of a list? | list.append(element)                                                                                       | [List methods](https://docs.python.org/3/tutorial/datastructures.html#more-on-lists)                      |
      | PY007 | How do you write a single-line comment in Python?            | # This is a comment                                                                                        | [Comments](https://docs.python.org/3/tutorial/introduction.html#first-steps-towards-programming)          |
      | PY008 | What is the syntax of an if-else conditional in Python?      | if condition:<br>&nbsp;&nbsp;&nbsp;&nbsp;# code if true<br>else:<br>&nbsp;&nbsp;&nbsp;&nbsp;# code if false | [If conditions](https://docs.python.org/3/tutorial/controlflow.html#if-statements)                        |
      | PY009 | How do you create a dictionary in Python?                    | my_dict = {"key1": value1, "key2": value2}                                                                 | [Dictionaries](https://docs.python.org/3/tutorial/datastructures.html#dictionaries)                       |
      | PY010 | Which function is used to read user input in Python?         | input()                                                                                                    | [input function](https://docs.python.org/3/library/functions.html#input)                                  |
    And the current date is 01/09/2024
    And "Alice" wants to learn the deck "Python Basics"

  Scenario: All cards start at level 0
    When "Alice" starts a review session
    Then "Alice" sees the cards in this order:
      | ID    | Level |
      | PY001 | 0     |
      | PY002 | 0     |
      | PY003 | 0     |
      | PY004 | 0     |
      | PY005 | 0     |
      | PY006 | 0     |
      | PY007 | 0     |
      | PY008 | 0     |
      | PY009 | 0     |
      | PY010 | 0     |

  Scenario: Only card marking matters during an interrupted session
    Given "Alice" starts a review session
    And "Alice" sees the card "PY001" asking the question "How do you declare a variable in Python?"
    And "Alice" marks the card "PY001" as to review
    And "Alice" sees the card "PY002" asking the question "What is the syntax of a for loop in Python?"
    And one day passes
    And "Alice" starts a review session
    Then "Alice" sees the card "PY002" asking the question "What is the syntax of a for loop in Python?"

  Scenario: the cards to learn wait for the learner
    When "Alice" looks at today's cards
    And "Alice" sees 10 cards to learn
    And 2 days pass
    And "Alice" looks at today's cards
    Then "Alice" sees 10 cards to learn

  Scenario: the cards to learn come back over time
    Given "Alice" looks at today's cards
    And "Alice" sees 10 cards to learn
    And "Alice" starts a review session
    And "Alice" sees the card "PY001" asking the question "How do you declare a variable in Python?"
    And "Alice" marks the card "PY001" as learned
    And "Alice" sees 9 cards to learn
    When 2 days pass
    And "Alice" looks at today's cards
    Then "Alice" sees 10 cards to learn

  Scenario: the first review interval is 1 day
    Given "Alice" starts a review session
    And "Alice" sees the card "PY001" asking the question "How do you declare a variable in Python?"
    When "Alice" marks the card "PY001" as learned
    And one day passes
    And "Alice" looks at today's cards
    Then "Alice" sees 10 cards to learn

  Scenario: the second review interval is also 1 day
    Given "Alice" starts a review session
    And "Alice" sees the card "PY001" asking the question "How do you declare a variable in Python?"
    When "Alice" marks the card "PY001" as learned
    And one day passes
    And "Alice" starts a review session
    And "Alice" sees the card "PY002" asking the question "What is the syntax of a for loop in Python?"
    When "Alice" marks the card "PY002" as learned
    And one day passes
    And "Alice" looks at today's cards
    Then "Alice" sees 10 cards to learn

  Scenario Outline: the review intervals are the Fibonacci numbers
    Given "Alice" has already reviewed the card "PY001" at level <initial_level> <days_since_last_review> days ago
    When "Alice" starts a review session
    And "Alice" marks the card "PY001" as learned
    Then the card "PY001" is at level <new_level>
    And the last review of "PY001" is set to today
    And the next review of "PY001" is scheduled in <days_until_next_review> days

    Examples:
      | initial_level | days_since_last_review | new_level | days_until_next_review |
      | 1             | 1                      | 2         | 1                      |
      | 2             | 1                      | 3         | 2                      |
      | 3             | 2                      | 4         | 3                      |
      | 4             | 3                      | 5         | 5                      |
      | 5             | 5                      | 6         | 8                      |
      | 6             | 8                      | 7         | 13                     |
      | 7             | 13                     | 8         | 21                     |
      | 8             | 21                     | 9         | 34                     |
      | 9             | 34                     | 9         | 34                     |

  Scenario: an incorrect review resets the level to 1
    Given "Alice" has already reviewed the cards of the deck "Python Basics" at level 4 60 days ago
    When "Alice" starts a review session
    When "Alice" marks the card "PY001" as to review
    Then the card "PY001" is at level 1
    And the last review of "PY001" is set to today
    And the next review of "PY001" is scheduled in 1 days

  Scenario: a late review does not affect progression if correct
    Given "Alice" has already reviewed the card "PY001" at level 3 5 days ago
    When "Alice" starts a review session
    When "Alice" marks the card "PY001" as learned
    Then the card "PY001" is at level 4
    And the last review of "PY001" is set to today
    And the next review of "PY001" is scheduled in 3 days

  Scenario: a monthly review stays at that level
    Given "Alice" has already reviewed the card "PY001" at level 9 34 days ago
    When "Alice" starts a review session
    When "Alice" marks the card "PY001" as learned
    Then the card "PY001" is at level 9
    And the last review of "PY001" is set to today
    And the next review of "PY001" is scheduled in 34 days

  Scenario: a late review computes the next date from the actual day of answering
    Given "Alice" has already reviewed the card "PY001" at level 3 60 days ago
    When "Alice" starts a review session
    When "Alice" marks the card "PY001" as learned
    Then the card "PY001" is at level 4
    And the last review of "PY001" is set to today
    And the next review of "PY001" is scheduled in 3 days

  Scenario: cards are sorted by the earliest next review then by deck order
    Given "Alice" has already reviewed the following cards:
      | ID    | Level | Last reviewed on |
      | PY001 | 1     | 14/07/2024       |
      | PY002 | 2     | 14/07/2024       |
      | PY003 | 3     | 14/07/2024       |
      | PY004 | 4     | 14/07/2024       |
      | PY005 | 5     | 14/07/2024       |
      | PY006 | 6     | 14/07/2024       |
      | PY007 | 7     | 14/07/2024       |
      | PY008 | 8     | 14/07/2024       |
      | PY009 | 9     | 14/07/2024       |
      | PY010 | 9     | 14/07/2024       |
    When "Alice" starts a review session
    Then "Alice" sees the cards in this order:
      | ID    | Level |
      | PY001 | 1     |
      | PY002 | 2     |
      | PY003 | 3     |
      | PY004 | 4     |
      | PY005 | 5     |
      | PY006 | 6     |
      | PY007 | 7     |
      | PY008 | 8     |
      | PY009 | 9     |
      | PY010 | 9     |

  Scenario: Cards not yet studied are offered first
    Given "Alice" has already reviewed the following cards:
      | ID    | Level | Last reviewed on |
      | PY001 | 1     | 14/07/2024       |
      | PY002 | 2     | 14/07/2024       |
      | PY003 | 3     | 14/07/2024       |
      | PY004 | 4     | 14/07/2024       |
    When "Alice" starts a review session
    Then "Alice" sees the cards in this order:
      | ID    | Level |
      | PY005 | 0     |
      | PY006 | 0     |
      | PY007 | 0     |
      | PY008 | 0     |
      | PY009 | 0     |
      | PY010 | 0     |
      | PY001 | 1     |
      | PY002 | 2     |
      | PY003 | 3     |
      | PY004 | 4     |

  Scenario: Cards from different decks are mixed together
    Given the deck "Advanced Python" is made of the following cards:
      | ID    | Question                       | Answer          |
      | PYA01 | What is a decorator in Python? | @decorator_name |
      | PYA02 | How do you define a class in Python? | class ClassName: |
    And "Alice" wants to learn the deck "Advanced Python"
    Given "Alice" has already reviewed the following cards:
      | ID    | Level | Last reviewed on |
      | PY001 | 3     | 14/07/2024       |
      | PY002 | 5     | 14/07/2024       |
      | PY003 | 1     | 14/07/2024       |
      | PYA01 | 4     | 14/07/2024       |
      | PYA02 | 2     | 14/07/2024       |
    When "Alice" starts a review session
    Then "Alice" sees the cards in this order:
      | ID    | Level |
      | PY004 | 0     |
      | PY005 | 0     |
      | PY006 | 0     |
      | PY007 | 0     |
      | PY008 | 0     |
      | PY009 | 0     |
      | PY010 | 0     |
      | PY003 | 1     |
      | PYA02 | 2     |
      | PY001 | 3     |
      | PYA01 | 4     |
      | PY002 | 5     |

  # Seeded by a durable consumer of OrganizationCreated, off the journal. Seeding is off by
  # default under test — starter rows would break every other scenario's assertions — so this
  # one turns it on to observe the behaviour the README advertises.
  Scenario: A new organisation starts with its welcome deck
    Given a server admin is signed in as "root@example.com"
    And the admin sets the "organizations" setting "seed_welcome_content" to "true"
    And "newcomer" wants to learn the deck "Welcome"
    When "newcomer" starts a review session
    Then "newcomer" sees 2 cards to learn
