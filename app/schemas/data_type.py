from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.scan.engine import fold


class DataTypeKind(StrEnum):
    # The only detector today (D14). Case-sensitive: "KEYWORDS" is rejected.
    KEYWORDS = "keywords"


# Postgres text cannot store NUL; rejecting it here turns a would-be 500 into a 422.
NO_NUL = r"^[^\x00]*$"
# Equals the default MAX_SCAN_TEXT_CHARS: a larger threshold could never match.
MAX_THRESHOLD = 1_000_000


def collapse_whitespace(keyword: str) -> str:
    # Collapse as the engine does, so what is stored is what is matched. Pydantic's strip and
    # Python's split() disagree on \x1c-\x1f, so the result may be blank; a blank keyword is
    # rejected, not dropped.
    keyword = " ".join(keyword.split())
    if not keyword:
        raise ValueError("keyword is blank")
    return keyword


Keyword = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=NO_NUL),
    AfterValidator(collapse_whitespace),
]


class DataTypeIn(BaseModel):
    """Body of POST and PUT. PUT is a full replace (D8): omitted fields get their defaults."""

    # forbid: a typo or a read-only field (id, timestamps) fails loudly instead of being ignored.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200, pattern=NO_NUL)
    description: str = Field(
        default="",
        max_length=2000,
        pattern=NO_NUL,
        description='Defaults to "". On PUT, omitting it resets it to "".',
    )
    type: DataTypeKind = Field(
        default=DataTypeKind.KEYWORDS,
        description='Defaults to "keywords". On PUT, omitting it resets it to "keywords".',
    )
    content: list[Keyword] = Field(
        min_length=1,
        max_length=1000,
        description=(
            "Keywords; trimmed, internal whitespace collapsed, de-duplicated "
            "case-insensitively (first spelling kept)."
        ),
    )
    # strict: "3", true and 3.0 are rejected, not coerced, for the number that sets sensitivity.
    threshold: int = Field(ge=1, le=MAX_THRESHOLD, strict=True)

    @field_validator("content")
    @classmethod
    def dedupe_case_insensitively(cls, v: list[str]) -> list[str]:
        # The engine's fold, so "stored once" and "matches as equal" are the same function.
        seen: set[str] = set()
        unique: list[str] = []
        for keyword in v:
            key = fold(keyword)
            if key not in seen:
                seen.add(key)
                unique.append(keyword)
        return unique


class DataTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    type: DataTypeKind
    content: list[str]
    threshold: int
    created_at: datetime
    updated_at: datetime
