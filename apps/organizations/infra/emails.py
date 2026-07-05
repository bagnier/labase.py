from apps.shared.email import Email
from apps.shared.http.templates import templates


def invitation_email(to: str, org_name: str, link: str) -> Email:
    context = {"org_name": org_name, "link": link}
    return Email(
        to=to,
        subject=f"You're invited to join {org_name}",
        text=templates.env.get_template("organizations/email/invitation.txt").render(context),
        html=templates.env.get_template("organizations/email/invitation.html").render(context),
    )
