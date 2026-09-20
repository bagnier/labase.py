"""What the Tasks screen answers a JSON caller — the backlog, its counts, and the strip's data."""

from pydantic import BaseModel, ConfigDict, Field

from apps.shared.queue import QueuedTaskRead


class StripSegmentRead(BaseModel):
    kind: str
    left: float
    width: float
    starts_at: str
    ends_at: str


class LaneRead(BaseModel):
    topic: str
    state: str
    cadence: str
    counts: dict[str, int]
    family: str
    segments: list[StripSegmentRead]


class HistoryRead(BaseModel):
    """The film strip as data: the window, and one lane per task or recurring topic."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    lanes: list[LaneRead]


class TasksPage(BaseModel):
    tasks: list[QueuedTaskRead]
    counts: dict[str, int]
    history: HistoryRead
