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

    def assert_workspace_card(self, org_name: str) -> None:
        raise NotImplementedError
