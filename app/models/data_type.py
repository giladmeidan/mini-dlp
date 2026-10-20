import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import copy_created_at, utcnow

# Constraint names the service maps IntegrityErrors by (D18).
UQ_DATA_TYPES_NAME = "uq_data_types_name_lower"


class DataType(Base):
    __tablename__ = "data_types"
    __table_args__ = (
        CheckConstraint("type IN ('keywords')", name="type_allowed"),
        CheckConstraint("cardinality(content) >= 1", name="content_not_empty"),
        CheckConstraint("threshold >= 1", name="threshold_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # No onupdate: services set it explicitly (D16).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=copy_created_at
    )


# Case-insensitive unique name (D15).
Index(UQ_DATA_TYPES_NAME, func.lower(DataType.name), unique=True)
