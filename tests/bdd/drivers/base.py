from abc import ABC, abstractmethod


class BaseDriver(ABC):
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @abstractmethod
    def login(self, email: str, password: str) -> None: ...

    @abstractmethod
    def visit(self, path: str) -> None: ...

    @abstractmethod
    def assert_page_accessible(self, path: str, contains: str) -> None: ...

    @abstractmethod
    def assert_text(self, text: str) -> None: ...

    @abstractmethod
    def assert_unauthorized(self) -> None: ...

    @abstractmethod
    def assert_redirected_to_login(self) -> None: ...

    @abstractmethod
    def assert_page_loaded(self) -> None: ...

    @abstractmethod
    def assert_login_rejected(self) -> None: ...
