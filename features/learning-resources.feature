Feature: Finding help resources

  A learner finds resources in order to get help on their difficulties

  Background:
    Given the deck "Python Basics" with resource "https://docs.python.org/fr/3/tutorial/index.html" is made of the following cards:
      | ID    | Question                                    | Answer                         | Resource                                                                             |
      | PY001 | How do you declare a variable in Python?    | variable_name = value          | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | PY002 | What is the syntax of a for loop in Python? | for element in sequence:       | https://docs.python.org/fr/3/tutorial/controlflow.html#for-statements                |
      | PY003 | How do you define a function in Python?     | def function_name(parameters): | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | PY004 | How do you import a module in Python?       | import module_name             | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | PY005 | How do you write a comment in Python?       | # This is a comment            |                                                                                      |
    And the deck "Advanced Python" with resource "https://docs.python.org/fr/3/reference/index.html" is made of the following cards:
      | ID    | Question                             | Answer           | Resource                                                  |
      | PYA01 | What is a decorator in Python?       | @decorator_name  | https://docs.python.org/fr/3/glossary.html#term-decorator |
      | PYA02 | How do you define a class in Python? | class ClassName: | https://docs.python.org/fr/3/tutorial/classes.html        |
    And "Alice" wants to learn the deck "Python Basics"

  Scenario: Resources are offered for all cards not yet studied
    When "Alice" looks at the resources to review
    Then "Alice" sees the resources in this order:
      | Deck          | Resources                                                                            |
      | Python Basics | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | Python Basics | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | Python Basics | https://docs.python.org/fr/3/tutorial/controlflow.html#for-statements                |

  Scenario: No resource is offered if no card is marked to review
    Given "Alice" has already reviewed the cards of the deck "Python Basics" at level 3 10 days ago
    And "Alice" starts a review session
    And "Alice" marks all today's cards as learned
    When "Alice" looks at the resources to review
    Then "Alice" sees no resource

  Scenario: Resources of cards marked to review are offered at the end of the session
    Given "Alice" has already reviewed the cards of the deck "Python Basics" at level 3 10 days ago
    And "Alice" starts a review session
    And "Alice" marks the card "PY001" as to review
    And "Alice" marks the card "PY002" as to review
    And "Alice" marks the card "PY003" as learned
    When "Alice" looks at the resources to review
    Then "Alice" sees the resources in this order:
      | Deck          | Resources                                                                            |
      | Python Basics | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | Python Basics | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | Python Basics | https://docs.python.org/fr/3/tutorial/controlflow.html#for-statements                |

  Scenario: Resources are presented without duplicates
    Given "Alice" has already reviewed the cards of the deck "Python Basics" at level 3 10 days ago
    And "Alice" starts a review session
    And "Alice" marks the card "PY001" as to review
    And "Alice" marks the card "PY002" as learned
    And "Alice" marks the card "PY003" as to review
    When "Alice" looks at the resources to review
    Then "Alice" sees the resources in this order:
      | Deck          | Resources                                                                            |
      | Python Basics | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | Python Basics | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |

  Scenario: A card resource is not shown if it is identical to the deck resource
    Given "Alice" has already reviewed the cards of the deck "Python Basics" at level 3 10 days ago
    And "Alice" starts a review session
    And "Alice" marks the card "PY001" as learned
    And "Alice" marks the card "PY002" as learned
    And "Alice" marks the card "PY003" as learned
    And "Alice" marks the card "PY004" as to review
    When "Alice" looks at the resources to review
    Then "Alice" sees the resources in this order:
      | Deck          | Resources                                        |
      | Python Basics | https://docs.python.org/fr/3/tutorial/index.html |

  Scenario: cards without a resource show nothing more
    Given "Alice" has already reviewed the cards of the deck "Python Basics" at level 3 10 days ago
    And "Alice" starts a review session
    And "Alice" marks the card "PY001" as to review
    And "Alice" marks the card "PY002" as learned
    And "Alice" marks the card "PY003" as learned
    And "Alice" marks the card "PY004" as learned
    And "Alice" marks the card "PY005" as to review
    When "Alice" looks at the resources to review
    Then "Alice" sees the resources in this order:
      | Deck          | Resources                                                                            |
      | Python Basics | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | Python Basics | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |

  Scenario: resources accumulate across the multiple sessions of a day
    Given "Alice" has already reviewed the cards of the deck "Python Basics" at level 3 10 days ago
    And "Alice" starts a review session
    And "Alice" marks the card "PY001" as to review
    And "Alice" starts a review session
    And "Alice" marks the card "PY002" as to review
    When "Alice" looks at the resources to review
    Then "Alice" sees the resources in this order:
      | Deck          | Resources                                                                            |
      | Python Basics | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | Python Basics | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | Python Basics | https://docs.python.org/fr/3/tutorial/controlflow.html#for-statements                |

  Scenario: you see the resources of your last review day
    Given "Alice" has already reviewed the cards of the deck "Python Basics" at level 3 10 days ago
    And "Alice" starts a review session
    And "Alice" marks the card "PY001" as to review
    And one day passes
    When "Alice" looks at the resources to review
    Then "Alice" sees the resources in this order:
      | Deck          | Resources                                                                            |
      | Python Basics | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | Python Basics | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |

  Scenario: resources from several decks are presented grouped by deck
    Given "Alice" has already reviewed the cards of the deck "Python Basics" at level 3 10 days ago
    And "Alice" wants to learn the deck "Advanced Python"
    And "Alice" starts a review session
    And "Alice" marks the card "PYA01" as to review
    And "Alice" marks the card "PYA02" as learned
    And "Alice" marks the card "PY001" as to review
    And "Alice" marks the card "PY002" as learned
    And "Alice" marks the card "PY003" as learned
    And "Alice" marks the card "PY004" as learned
    And "Alice" marks the card "PY005" as learned
    When "Alice" looks at the resources to review
    Then "Alice" sees the resources in this order:
      | Deck           | Resources                                                                            |
      | Python Basics  | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | Python Basics  | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | Advanced Python | https://docs.python.org/fr/3/reference/index.html                                    |
      | Advanced Python | https://docs.python.org/fr/3/glossary.html#term-decorator                            |
      | Advanced Python | https://docs.python.org/fr/3/tutorial/classes.html                                   |
