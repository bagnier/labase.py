from apps.organizations.infra.emails import invitation_email

_LINK = "http://testserver/invitations/abc-123"


def test_invitation_email_renders_both_bodies():
    email = invitation_email(to="bob@example.com", org_name="Acme", link=_LINK)
    assert email.to == "bob@example.com"
    assert "Acme" in email.subject
    assert _LINK in email.text
    assert email.html is not None
    assert f'href="{_LINK}"' in email.html
    assert "Acme" in email.html
