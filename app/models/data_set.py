import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Table, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import copy_created_at, utcnow
from app.models.data_type import DataType

# Constraint names the services map IntegrityErrors by (D18).
# The FK name is produced by NAMING_CONVENTION, not passed explicitly; see 0001_initial.py.
FK_LINK_DATA_TYPE = "fk_data_set_data_types_data_type_id_data_types"
UQ_DATA_SETS_NAME = "uq_data_sets_name_lower"

data_set_data_types = Table(
    "data_set_data_types",
    Base.metadata,
    # Link rows belong to the Data Set, so they go with it.
    Column(
        "data_set_id",
        Uuid,
        ForeignKey("data_sets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # A Data Type in use cannot be deleted (D7); the service checks first and returns 409.
    Column(
        "data_type_id",
        Uuid,
        ForeignKey("data_types.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    # The PK index leads with data_set_id; this one serves "who references this Data Type?".
    Index("ix_data_set_data_types_data_type_id", "data_type_id"),
)


class DataSet(Base):
    __tablename__ = "data_sets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=copy_created_at
    )

    # Membership is a set; order_by only makes the returned ids deterministic (D19).
    data_types: Mapped[list[DataType]] = relationship(
        secondary=data_set_data_types,
        lazy="selectin",
        order_by=(DataType.created_at, DataType.id),
    )

    @property
    def data_type_ids(self) -> list[uuid.UUID]:
        # Read by DataSetOut (from_attributes): the API shows ids, storage is a join table (D6).
        return [dt.id for dt in self.data_types]


Index(UQ_DATA_SETS_NAME, func.lower(DataSet.name), unique=True)
