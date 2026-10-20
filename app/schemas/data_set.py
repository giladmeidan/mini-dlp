from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.data_type import NO_NUL

# A product limit, not a setting: worst-case scan cost is MAX_SCAN_TEXT_CHARS x |Data Types|
# regex passes (D11, D19).
MAX_DATA_TYPES_PER_SET = 100


class DataSetIn(BaseModel):
    """Body of POST and PUT. PUT is a full replace (D8): name and membership are both replaced."""

    # forbid: a typo or a read-only field (id, timestamps) fails loudly instead of being ignored.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200, pattern=NO_NUL)
    # Required, no default: with full-replace PUT a defaulted [] would let `PUT {"name": ...}`
    # silently empty a policy (D19). Not de-duplicated here: the service does it, so its 422
    # details can point at positions in the body as sent.
    data_type_ids: list[UUID] = Field(
        max_length=MAX_DATA_TYPES_PER_SET,
        description=(
            "Required. Set semantics: duplicates collapse; order is not significant. "
            "Send [] for an empty policy."
        ),
    )


class DataSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    data_type_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
