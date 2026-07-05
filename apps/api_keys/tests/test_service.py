from apps.api_keys.domain.service import generate_key, hash_token


def test_generate_key_material():
    key = generate_key()
    assert key.token.startswith("lbk_")
    assert key.prefix == key.token[:12]
    assert key.key_hash == hash_token(key.token)
    assert key.token not in key.key_hash  # hashed, not stored in clear


def test_every_key_is_unique():
    assert generate_key().token != generate_key().token
