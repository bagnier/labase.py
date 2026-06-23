class PendingInvitationExists(Exception):
    pass


class LastOwnerViolation(Exception):
    pass


class OrgLimitReached(Exception):
    @staticmethod
    def message(max_orgs: int) -> str:
        suffix = "" if max_orgs == 1 else "s"
        return f"You can own at most {max_orgs} organisation{suffix}."
