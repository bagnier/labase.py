"""Typed alerting events — the emitter never knows the subscribers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IssueOpened:
    group_id: int
    title: str


@dataclass(frozen=True)
class IssueRegressed:
    group_id: int
    title: str
    resolved_in_version: str | None
    seen_version: str
