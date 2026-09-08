from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from app.group_v3.schemas import StrictModel


LANGUAGES = {"vi", "en", "zh-TW"}


class LanguageProfileUpdate(StrictModel):
    spoken_language: str
    preferred_output_language: str
    auto_translate_enabled: bool = True
    chat_auto_translate_enabled: bool = False
    auto_read_enabled: bool = False
    show_original_enabled: bool = True

    @field_validator("spoken_language", "preferred_output_language")
    @classmethod
    def validate_language(cls, value):
        if value not in LANGUAGES:
            raise ValueError("invalid_language")
        return value


class TranslationConsentUpdate(StrictModel):
    status: Literal["granted", "denied", "revoked"]
    policy_version: str = Field(min_length=8, max_length=40)


class TranslationSecretCreate(StrictModel):
    runtime_kind: Literal["call", "video", "radio"]
    runtime_id: str = Field(min_length=1, max_length=36)
    segment_id: str = Field(min_length=8, max_length=128)
    source_language: str
    target_language: str
    estimated_target_seconds: int = Field(ge=1, le=900)

    @field_validator("source_language", "target_language")
    @classmethod
    def validate_language(cls, value):
        if value not in LANGUAGES:
            raise ValueError("invalid_language")
        return value


class TranslationFinalCreate(StrictModel):
    reservation_id: str = Field(min_length=1, max_length=36)
    state: Literal["FINAL"]
    speaker_membership_id: str = Field(min_length=1, max_length=36)
    original_text: str = Field(min_length=1, max_length=12000)
    translated_text: str = Field(min_length=1, max_length=12000)
    actual_target_seconds: int = Field(ge=1, le=900)
    confidence: float | None = Field(default=None, ge=0, le=1)


class TranslationSegmentTextCreate(StrictModel):
    runtime_kind: Literal["call", "video", "radio"]
    runtime_id: str = Field(min_length=1, max_length=36)
    client_segment_id: str = Field(min_length=8, max_length=128)
    source_language: str
    source_text: str = Field(min_length=1, max_length=12000)

    @field_validator("source_language")
    @classmethod
    def validate_source_language(cls, value):
        if value not in LANGUAGES | {"auto"}:
            raise ValueError("invalid_language")
        return value


class TranslationVariantRetry(StrictModel):
    target_language: str

    @field_validator("target_language")
    @classmethod
    def validate_target_language(cls, value):
        if value not in LANGUAGES:
            raise ValueError("invalid_language")
        return value


class TranslationReservationRelease(StrictModel):
    reservation_id: str = Field(min_length=1, max_length=36)


class TtsJobAck(StrictModel):
    status: Literal["completed", "failed", "suppressed"]
    failure_code: str = Field(default="", max_length=80)
