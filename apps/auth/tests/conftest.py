from uuid import uuid4

import pytest

from apps.auth.tests.given_helpers import create_user, delete_user


@pytest.fixture
def test_user():
    email = f"{uuid4()}@test.local"
    password = "Test1234!"
    uid = create_user(email, password)
    yield email, password
    delete_user(uid)
