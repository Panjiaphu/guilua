from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from app.group_v3.schemas import StrictModel


class GroupNotificationPreferenceUpdate(StrictModel):
    mode: Literal["smart", "all", "important", "none"]
    mute_for_minutes: Literal[-1, 0, 15, 60, 480, 1440] | None = None


class GroupNotificationPresenceHeartbeat(StrictModel):
    tab_id: str = Field(min_length=8, max_length=64)
    surface: Literal["chat", "chat-translation", "call", "video", "radio"]
    visible: bool

    @field_validator("tab_id")
    @classmethod
    def validate_tab_id(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("invalid_tab_id")
        return value


class GroupNotificationReadUpdate(StrictModel):
    last_seen_sequence: int = Field(ge=0)
