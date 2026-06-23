from dataclasses import dataclass


@dataclass
class AuthenticatedUser:
    id: str
    email: str
    access_token: str = ""
    is_admin: bool = False
