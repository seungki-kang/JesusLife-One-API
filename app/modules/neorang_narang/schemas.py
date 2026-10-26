"""Metadata and minimal command contracts; no persistence or authentication here.

Flutter SQLite remains authoritative. The app must supply a stable UUID instead
of forwarding its legacy timestamp-based ID. Revision and deleted_at are sync
metadata, not existing Flutter CompletionRecord fields.
"""

from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class CourseNumber(IntEnum):
    CHAPTER_ONE = 1
    CHAPTER_TWO = 2


class ParticipationMode(StrEnum):
    SOLO = "solo"
    TOGETHER = "together"


class CompletionRecordMetadata(BaseModel):
    """Allowlisted projection of CompletionRecord, using snake_case API keys.

    Revision starts at one; the service validates and increments server versions.
    A null deleted_at means active; a timestamp marks a soft deletion.
    Aware input offsets are normalized to UTC, including serialized output.
    This model does not authenticate a completion or authorize access.
    """

    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, frozen=True
    )

    id: UUID
    course_number: CourseNumber
    participation_mode: ParticipationMode
    completed_at: AwareDatetime
    revision: int = Field(strict=True, ge=1)
    deleted_at: AwareDatetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def validate_id_type(cls, value: object) -> object:
        if not isinstance(value, (str, UUID)):
            raise ValueError("id must be a UUID string or UUID")
        return value

    @field_validator("course_number", mode="before")
    @classmethod
    def validate_course_type(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("course_number must be an integer chapter number")
        return value

    @field_validator("completed_at", "deleted_at", mode="before")
    @classmethod
    def validate_datetime_type(cls, value: object) -> object:
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("timestamps must be timezone-aware ISO 8601 values")
        return value

    @field_validator("completed_at", "deleted_at")
    @classmethod
    def normalize_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else value.astimezone(timezone.utc)


class CompletionUpdate(BaseModel):
    """Full metadata replacement; revision is the result, base is last seen."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)
    base_revision: int = Field(strict=True, ge=0)
    metadata: CompletionRecordMetadata


class CompletionDelete(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)
    base_revision: int = Field(strict=True, ge=0)
    revision: int = Field(strict=True, ge=1)


class CompletionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    metadata: CompletionRecordMetadata
    updated_at: AwareDatetime
    applied_revision: int
    current_revision: int
    replayed: bool
