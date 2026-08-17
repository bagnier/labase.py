class InvitationRefused(Exception):
    """An invitation was not issued, and the message says why — already a member, the org's
    limit reached, one already pending. The single outcome the caller branches on, so a refusal
    never travels as a second value beside a missing invitation."""


class LastOwnerViolation(Exception):
    pass


class OrgLimitReached(Exception):
    @staticmethod
    def message(max_orgs: int) -> str:
        suffix = "" if max_orgs == 1 else "s"
        return f"You can own at most {max_orgs} organisation{suffix}."
