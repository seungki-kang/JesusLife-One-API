"""Unconnected candidate create/ACK DTOs; synthetic shape validation only.

Does not prove selection eligibility, authentication, consent, ownership,
idempotency or withdrawal fences. Never serialize/log ValidationError or its
errors(): hide_input_in_errors protects str(error), not structured errors.
No HTTP error handling is installed here.
"""

from datetime import date, datetime
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RealCompletionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    sync_id: UUID
    course_number: int = Field(strict=True, ge=1, le=2)
    completed_on: str = Field(strict=True)

    @field_validator("sync_id", mode="before")
    @classmethod
    def validate_uuid_type(cls, value: object) -> object:
        # Match v1: UUID objects/strings, canonical lowercase hyphenated JSON.
        if not isinstance(value, (str, UUID)):
            raise ValueError("Invalid UUID type")
        return value

    @field_validator("completed_on")
    @classmethod
    def validate_calendar_date(cls, value: str) -> str:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("Invalid calendar date")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("Invalid calendar date") from None
        return value


class RealCompletionCreate(BaseModel):
    """Client command snapshot, not server-issued authority.

    All fields are required, including explicit base_revision=0. Core must
    validate the supplied generation/policy; no generation floor or policy
    registry is established by the candidate contract. Server revision,
    received_at and verified owner are deliberately absent from this input.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    operation_id: UUID
    consent_generation: int = Field(strict=True)
    policy_version: str = Field(strict=True, min_length=1)
    base_revision: int = Field(strict=True, ge=0, le=0)
    metadata: RealCompletionMetadata

    @field_validator("operation_id", mode="before")
    @classmethod
    def validate_uuid_type(cls, value: object) -> object:
        if not isinstance(value, (str, UUID)):
            raise ValueError("Invalid UUID type")
        return value


class RealCompletionAck(BaseModel):
    """PROPOSED success shape only; no receipt storage or authority checks.

    received_at is supplied from the first server receipt, never generated here.
    Deleted, withdrawn or erased commands must be blocked by the service before
    constructing this DTO. Shape validation cannot establish that obligation.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    operation_id: UUID
    sync_id: UUID
    applied_revision: int = Field(strict=True, ge=1)
    current_revision: int = Field(strict=True, ge=1)
    replayed: bool = Field(strict=True)
    received_at: str = Field(strict=True)

    @field_validator("operation_id", "sync_id", mode="before")
    @classmethod
    def validate_uuid_type(cls, value: object) -> object:
        if not isinstance(value, (str, UUID)):
            raise ValueError("Invalid UUID type")
        return value

    @field_validator("received_at")
    @classmethod
    def validate_received_at(cls, value: str) -> str:
        if re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?Z",
            value,
        ) is None:
            raise ValueError("Invalid UTC receipt timestamp")
        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("Invalid UTC receipt timestamp") from None
        return value

    @model_validator(mode="after")
    def validate_revision_relationship(self) -> "RealCompletionAck":
        if self.current_revision < self.applied_revision:
            raise ValueError("Current revision precedes applied revision")
        if not self.replayed and (self.applied_revision != 1 or self.current_revision != 1):
            raise ValueError("Initial create revisions must both be one")
        return self
