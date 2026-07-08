from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import BigInteger, DateTime, Float, Integer
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base


class MetricResolution(StrEnum):
    minute = "minute"
    hour = "hour"


class RequestMetric(Base):
    """One flushed delta: traffic of one route on one instance in one time bucket.

    ``duration_buckets`` is positionally aligned with ``BUCKET_BOUNDS_MS`` (+Inf
    last) — the shape Prometheus derives percentiles from, so p95 survives
    aggregation across rows where raw averages would not.
    """

    __tablename__ = "request_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str] = mapped_column(default=MetricResolution.minute)
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
    p95_ms: float | None


class LoadTotals(BaseModel):
    requests: int
    error_rate_pct: float
    p95_ms: float | None


class LoadPoint(BaseModel):
    """Traffic of one time bucket, summed across routes and instances."""

    bucket: datetime
    requests: int
    errors: int
