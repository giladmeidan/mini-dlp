from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSet, DataType, data_set_data_types


class DataTypeRepository:
    """SQL only. Never flushes or commits, so constraint errors surface in the service's commit."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, id: UUID) -> DataType | None:
        return self.session.get(DataType, id)

    def list_all(self) -> list[DataType]:
        stmt = select(DataType).order_by(DataType.created_at.desc(), DataType.id.asc())
        return list(self.session.scalars(stmt))

    def add(self, dt: DataType) -> None:
        self.session.add(dt)

    def delete(self, dt: DataType) -> None:
        self.session.delete(dt)

    def referencing_data_sets(self, id: UUID) -> list[tuple[UUID, str]]:
        stmt = (
            select(DataSet.id, DataSet.name)
            .join(data_set_data_types, data_set_data_types.c.data_set_id == DataSet.id)
            .where(data_set_data_types.c.data_type_id == id)
            .order_by(DataSet.name, DataSet.id)
        )
        return [(ds_id, name) for ds_id, name in self.session.execute(stmt)]
