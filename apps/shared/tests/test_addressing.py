from fastapi import Request

from apps.shared.http.client_ip import client_ip
from apps.shared.settings.env import get_technical_settings


def _request(headers: dict[str, str], peer: str | None = "10.0.0.1"):
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 0) if peer else None,
    }
    return Request(scope)


def test_uses_socket_peer_when_forwarded_not_trusted(monkeypatch):
    monkeypatch.setattr(get_technical_settings(), "trust_forwarded_for", False)
    req = _request({"x-forwarded-for": "1.2.3.4"}, peer="10.0.0.1")
    assert client_ip(req) == "10.0.0.1"


def test_uses_leftmost_forwarded_when_trusted(monkeypatch):
    monkeypatch.setattr(get_technical_settings(), "trust_forwarded_for", True)
    req = _request({"x-forwarded-for": "1.2.3.4, 10.0.0.9"}, peer="10.0.0.1")
    assert client_ip(req) == "1.2.3.4"


def test_falls_back_to_peer_when_trusted_but_header_absent(monkeypatch):
    monkeypatch.setattr(get_technical_settings(), "trust_forwarded_for", True)
    req = _request({}, peer="10.0.0.1")
    assert client_ip(req) == "10.0.0.1"


def test_none_when_no_peer_and_no_trusted_header(monkeypatch):
    monkeypatch.setattr(get_technical_settings(), "trust_forwarded_for", False)
    req = _request({"x-forwarded-for": "1.2.3.4"}, peer=None)
    assert client_ip(req) is None
