from __future__ import annotations

from pydantic import Field, field_validator

from app.group_v3.schemas import StrictModel


class MediaSessionCreate(StrictModel):
    media_kind: str
    title: str = Field(default="", max_length=120)
    participant_membership_ids: list[str] = Field(min_length=1, max_length=49)

    @field_validator("media_kind")
    @classmethod
    def validate_kind(cls, value):
        if value not in {"audio", "video"}:
            raise ValueError("invalid_media_kind")
        return value

    @field_validator("participant_membership_ids")
    @classmethod
    def validate_participants(cls, value):
        if len(value) != len(set(value)) or any(not 1 <= len(item) <= 36 for item in value):
            raise ValueError("invalid_participant_membership_ids")
        return value


class VideoSubscriptionsUpdate(StrictModel):
    participant_membership_ids: list[str] = Field(default_factory=list, max_length=49)

    @field_validator("participant_membership_ids")
    @classmethod
    def validate_participants(cls, value):
        if len(value) != len(set(value)) or any(not 1 <= len(item) <= 36 for item in value):
            raise ValueError("invalid_participant_membership_ids")
        return value


class MediaConnectionStateUpdate(StrictModel):
    status: str
    failure_code: str = Field(default="", max_length=80)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value not in {"connecting", "connected", "reconnecting", "failed"}:
            raise ValueError("invalid_media_connection_status")
        return value
