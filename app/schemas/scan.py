from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# A real UUID in place of the assignment placeholder "dt-uuid": the field has format: uuid.
_EXAMPLE_DATA_TYPE_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
_EXAMPLE_DATA_SET_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


class ScanIn(BaseModel):
    """Body of POST /api/scan (D20). Nothing from it is persisted."""

    # No str_strip_whitespace and no NUL pattern: the text is scanned, never stored (D20).
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "text": "Confidential: salary review. Do not forward the salary sheet.",
                    "data_set_id": _EXAMPLE_DATA_SET_ID,
                }
            ]
        },
    )

    # No max_length: the limit is a setting enforced by the service as a 413, not a 422 (D20).
    text: str = Field(
        description=(
            "The text to scan. At most MAX_SCAN_TEXT_CHARS code points (413 above that). "
            "May be empty."
        )
    )
    data_set_id: UUID = Field(
        description="The Data Set (policy) to scan against. 404 if it does not exist."
    )


class DetectedObject(BaseModel):
    # Built from engine.Detection, a frozen slots dataclass.
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    match_count: int


# Two models, one per assignment example. json_schema_serialization_defaults_required: `status`
# has a default, which would make it optional in the schema; with it, `status` is required, so
# `{}` no longer validates as ScanNoMatch.
class ScanMatch(BaseModel):
    model_config = ConfigDict(
        json_schema_serialization_defaults_required=True,
        json_schema_extra={
            "examples": [
                {
                    "status": "match",
                    "detected_objects": [
                        {
                            "id": _EXAMPLE_DATA_TYPE_ID,
                            "name": "Sensitive Keywords",
                            "match_count": 3,
                        }
                    ],
                }
            ]
        },
    )

    status: Literal["match"] = "match"
    # Never empty: no detection is the ScanNoMatch shape. Guards construction only: Pydantic
    # passes returned model instances through without re-validating them.
    detected_objects: list[DetectedObject] = Field(min_length=1)


class ScanNoMatch(BaseModel):
    model_config = ConfigDict(
        json_schema_serialization_defaults_required=True,
        json_schema_extra={"examples": [{"status": "not matched"}]},
    )

    status: Literal["not matched"] = "not matched"


# Discriminated: OpenAPI shows a oneOf with a mapping on `status` instead of a bare anyOf.
ScanOut = Annotated[ScanMatch | ScanNoMatch, Field(discriminator="status")]
