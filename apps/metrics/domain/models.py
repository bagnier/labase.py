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
    """One route's traffic on one instance in one time bucket. ``duration_buckets`` aligns with
    ``BUCKET_BOUNDS_MS``, +Inf last."""

    __tablename__ = "request_metrics"

    # When the time bucket opens; not `bucket`, taken by histograms and Storage.
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
    bucket_start: datetime
    requests: int
    errors: int


class LoadPage(BaseModel):
    totals: LoadTotals
    routes: list[RouteLoad]
    series: list[LoadPoint]
