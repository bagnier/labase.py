from pytest_bdd import scenarios

scenarios(
    "../../../../features/spaced-repetition.feature",
    "../../../../features/review-session.feature",
    "../../../../features/learning-resources.feature",
)
