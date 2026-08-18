from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import BigInteger, DateTime, Float, Integer
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Created, UUIDPk


class MetricResolution(StrEnum):
    minute = "minute"
    hour = "hour"


class RequestMetric(Base, UUIDPk, Created):
    """One flushed delta: traffic of one route on one instance in one time bucket.

    ``duration_buckets`` is positionally aligned with ``BUCKET_BOUNDS_MS`` (+Inf
    last) — the shape Prometheus derives percentiles from, so p95 survives
    aggregation across rows where raw averages would not.
    """

    __tablename__ = "request_metrics"

    # The instant the bucket opens — `bucket` alone would collide with `duration_buckets` (a
    # histogram) and with Storage buckets.
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[MetricResolution] = mapped_column(
        SAEnum(MetricResolution, name="metric_resolution", create_type=False),
        default=MetricResolution.minute,
    )
    instance: Mapped[str]
    method: Mapped[str]
    route: Mapped[str]
    requests: Mapped[int] = mapped_column(BigInteger, default=0)
    errors: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_sum_ms: Mapped[float] = mapped_column(Float, default=0.0)
    duration_buckets: Mapped[list[int]] = mapped_column(ARRAY(Integer))


class RouteLoad(BaseModel):
    """Aggregated view of one route over the screen's window."""

    method: str
    route: str
    label: str
    requests: int
    errors: int
    error_rate_pct: float
    avg_ms: float | None
    p95_ms: float | None


class LoadTotals(BaseModel):
    requests: int
    error_rate_pct: float
    avg_ms: float | None
    p95_ms: float | None


class LoadPoint(BaseModel):
    """Traffic of one time bucket, summed across routes and instances."""

    bucket_start: datetime
    requests: int
    errors: int
