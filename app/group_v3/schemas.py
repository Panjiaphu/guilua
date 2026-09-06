from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SpaceCreate(StrictModel):
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)


class SpaceUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    lifecycle_status: str | None = None
    version: int = Field(ge=1)

    @field_validator("lifecycle_status")
    @classmethod
    def validate_status(cls, value):
        if value is not None and value not in {"active", "archived"}:
            raise ValueError("invalid_lifecycle_status")
        return value


class OwnershipTransfer(StrictModel):
    target_membership_id: str = Field(min_length=1, max_length=36)
    version: int = Field(ge=1)


class MembershipCreate(StrictModel):
    principal_type: str
    principal_id: str = Field(min_length=1, max_length=128)
    principal_user_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    role: str = "member"

    @field_validator("principal_type")
    @classmethod
    def validate_type(cls, value):
        if value not in {"member", "business"}:
            raise ValueError("invalid_principal_type")
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        if value not in {"admin", "member"}:
            raise ValueError("invalid_membership_role")
        return value


class MembershipUpdate(StrictModel):
    role: str | None = None
    status: str | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        if value is not None and value not in {"admin", "member"}:
            raise ValueError("invalid_membership_role")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value is not None and value not in {"active", "removed"}:
            raise ValueError("invalid_membership_status")
        return value


class InvitationCreate(StrictModel):
    contact_ref: str = Field(min_length=3, max_length=128)


class MessageCreate(StrictModel):
    content: str = Field(min_length=1, max_length=8000)
    content_type: str = "text"
    client_message_id: str = Field(min_length=8, max_length=128)
    source_language: Literal["vi", "en", "zh-TW"] | None = None
    reply_to_id: str | None = Field(default=None, max_length=36)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value):
        if value not in {"text", "attachment"}:
            raise ValueError("invalid_content_type")
        return value

    @field_validator("attachment_ids")
    @classmethod
    def unique_attachments(cls, value):
        if len(set(value)) != len(value) or any(len(item) > 36 for item in value):
            raise ValueError("invalid_attachment_ids")
        return value


class MessageUpdate(StrictModel):
    content: str = Field(min_length=1, max_length=8000)


class ReactionCreate(StrictModel):
    reaction: str = Field(min_length=1, max_length=16)

    @field_validator("reaction")
    @classmethod
    def validate_reaction(cls, value):
        if any(character.isspace() for character in value):
            raise ValueError("invalid_reaction")
        return value
