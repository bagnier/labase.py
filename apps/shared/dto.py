"""DTO shapes shared by every context."""

from pydantic import BaseModel


class Partial(BaseModel):
    """A PATCH body: ask :meth:`sent` whether a field was sent, rather than typing every field
    ``| None``, which would read ``{"title": null}`` as "not sent" (AGENTS: `| None` means
    optional).
    """

    def sent(self, field: str) -> bool:
        return field in self.model_fields_set


class Message(BaseModel):
    """The JSON answer of a mutation with nothing else to return."""

    message: str


class Redirect(BaseModel):
    """Where a JSON caller goes next; a browser gets a 303."""

    redirect: str
