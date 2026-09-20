"""What a probe answers."""

from pydantic import BaseModel


class Probe(BaseModel):
    status: str
