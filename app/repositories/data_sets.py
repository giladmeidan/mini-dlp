from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSet, DataType


class DataSetRepository:
    """SQL only. Never flushes or commits, so constraint errors surface in the service's commit."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, id: UUID, *, for_update: bool = False) -> DataSet | None:
        # FOR UPDATE locks only the data_sets row; data_types are selectin-loaded by a second
        # query that runs after the lock is granted, so membership is read fresh.
        return self.session.get(DataSet, id, with_for_update=for_update)

    def list_all(self) -> list[DataSet]:
        stmt = select(DataSet).order_by(DataSet.created_at.desc(), DataSet.id.asc())
        return list(self.session.scalars(stmt))

    def add(self, ds: DataSet) -> None:
        self.session.add(ds)

    def delete(self, ds: DataSet) -> None:
        # The ORM deletes the link rows it has loaded; ON DELETE CASCADE is the backstop (D7).
        self.session.delete(ds)

    def get_data_types_by_ids(self, ids: Sequence[UUID]) -> list[DataType]:
        if not ids:
            return []  # skip the round trip for an empty IN ()
        # Same key as DataSet.data_types' order_by: after a write the collection keeps
        # assignment order, so this is what makes a POST/PUT response match a later GET.
        stmt = (
            select(DataType).where(DataType.id.in_(ids)).order_by(DataType.created_at, DataType.id)
        )
        return list(self.session.scalars(stmt))
