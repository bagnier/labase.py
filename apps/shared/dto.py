"""Shapes shared by the DTOs of every context — what a request carries, said once."""

from pydantic import BaseModel


class Partial(BaseModel):
    """A PATCH body: every field typed as what it is, presence asked separately.

    A partial update reads only the fields the caller sent. Typing each as ``| None`` would make
    "absent" a value of the field — and read ``{"title": null}`` as "not sent". Pydantic already
    keeps the set of fields the message carried; :meth:`sent` is that set, and a field's type
    stays what a sent value is (README: `| None` means optional).
    """

    def sent(self, field: str) -> bool:
        return field in self.model_fields_set


class Message(BaseModel):
    """A mutation's whole JSON answer when there is nothing to return but that it happened."""

    message: str


class Redirect(BaseModel):
    """Where a JSON caller should go next — what the browser gets as a 303."""

    redirect: str
