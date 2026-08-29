"""Validated public metadata for encrypted statement contributions."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_METADATA_JSON_BYTES = 2048
MAX_ENCRYPTED_KEY_BYTES = 1024
MAX_ENCRYPTED_STATEMENT_BYTES = 36 * 1024 * 1024
MAX_CLIENT_IP_CHARS = 45
MAX_USER_AGENT_CHARS = 255


class StatementSubmissionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    file_name: str = Field(min_length=1, max_length=255)
    institution: str = Field(min_length=1, max_length=120)
    frequency: Literal["Daily", "Weekly", "Monthly", "Quarterly", "Annually", "Other"]
    comments: str = Field(default="", max_length=256)

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        supplied = Path(value)
        if supplied.name != value or supplied.is_absolute() or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("must be a plain filename")
        return value


def bounded_log_value(value: str | None, maximum_chars: int) -> str:
    """Remove control-line breaks and bound values before logging/persistence."""
    return (value or "unknown").replace("\r", " ").replace("\n", " ")[:maximum_chars]
