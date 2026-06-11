from tests.e2e.drivers.protocols import BrowserProtocol


class OrgBrowserMixin(BrowserProtocol):
    def assert_org_count(self, count: int) -> None:
        raise NotImplementedError

    def assert_is_owner(self) -> None:
        raise NotImplementedError

    def view_org_list_as(self, email: str) -> None:
        raise NotImplementedError

    def assert_other_org_absent(self, email: str) -> None:
        raise NotImplementedError

    def join_org_as_member(self, org_name: str, email: str) -> None:
        raise NotImplementedError

    def view_org_list(self) -> None:
        raise NotImplementedError

    def assert_org_in_list(self, org_name: str) -> None:
        raise NotImplementedError

    def assert_org_absent(self, org_name: str) -> None:
        raise NotImplementedError

    def rename_org(self, new_name: str) -> None:
        raise NotImplementedError

    def sign_in_as_member(self, email: str) -> None:
        raise NotImplementedError

    def assert_action_forbidden(self) -> None:
        raise NotImplementedError

    def view_member_list(self) -> None:
        raise NotImplementedError

    def assert_member_with_role(self, email: str, role: str) -> None:
        raise NotImplementedError

    def assert_member_absent(self, email: str) -> None:
        raise NotImplementedError

    def set_member_role(self, email: str, role: str) -> None:
        raise NotImplementedError

    def remove_member(self, email: str) -> None:
        raise NotImplementedError

    def leave_org(self) -> None:
        raise NotImplementedError

    def assert_workspace_card(self, org_name: str) -> None:
        raise NotImplementedError

    def invite_member(self, email: str, role: str) -> None:
        raise NotImplementedError

    def view_pending_invitations(self) -> None:
        raise NotImplementedError

    def assert_invitation_pending(self, email: str, role: str) -> None:
        raise NotImplementedError

    def assert_invitation_absent(self, email: str) -> None:
        raise NotImplementedError

    def revoke_invitation(self, email: str) -> None:
        raise NotImplementedError

    def accept_invitation(self, email: str) -> None:
        raise NotImplementedError

    def try_accept_revoked_invitation(self, email: str) -> None:
        raise NotImplementedError

    def follow_invitation_link_again(self, email: str) -> None:
        raise NotImplementedError

    def assert_redirected_to_org_dashboard(self) -> None:
        raise NotImplementedError

    def assert_action_fails_with(self, message: str) -> None:
        raise NotImplementedError
