from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models import DataType
from app.models.base import utcnow
from app.models.data_set import FK_LINK_DATA_TYPE
from app.models.data_type import UQ_DATA_TYPES_NAME
from app.repositories.data_types import DataTypeRepository
from app.schemas.data_type import DataTypeIn


class DataTypeService:
    """Business rules and the unit of work for Data Types (D17)."""

    def __init__(self, session: Session):
        self.session = session
        self.repo = DataTypeRepository(session)

    def create(self, data: DataTypeIn) -> DataType:
        dt = DataType(**data.model_dump())
        self.repo.add(dt)
        # No name pre-check (D18): the unique index decides, and _commit maps its error.
        self._commit(name=data.name)
        return dt

    def get(self, id: UUID) -> DataType:
        dt = self.repo.get(id)
        if dt is None:
            raise NotFoundError(f"Data Type {id} not found")
        return dt

    def list_all(self) -> list[DataType]:
        return self.repo.list_all()

    def update(self, id: UUID, data: DataTypeIn) -> DataType:
        dt = self.get(id)
        # Full replace (D8). model_dump() builds a new `content` list: ARRAY columns are not
        # change-tracked in place, so the column must be reassigned, never mutated.
        for field, value in data.model_dump().items():
            setattr(dt, field, value)
        dt.updated_at = utcnow()
        self._commit(name=data.name)
        return dt

    def delete(self, id: UUID) -> None:
        dt = self.get(id)
        # Only a query can list the referencing Data Sets for the 409 body (D7);
        # ON DELETE RESTRICT is the backstop for a link added concurrently.
        refs = self.repo.referencing_data_sets(id)
        if refs:
            raise ConflictError(
                f"Data Type is referenced by {len(refs)} Data Set(s)",
                details=[
                    {
                        "loc": ["path", "id"],
                        "msg": f"referenced by Data Set '{name}'",
                        "type": "referenced_by",
                        "ctx": {"data_set_id": str(ds_id), "data_set_name": name},
                    }
                    for ds_id, name in refs
                ],
            )
        self.repo.delete(dt)
        self._commit()

    def _commit(self, *, name: str | None = None) -> None:
        """Commit, mapping known constraint violations to 409 by constraint name (D18)."""
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == UQ_DATA_TYPES_NAME:
                # Built from `name`, not the ORM object: rollback expired its attributes.
                raise ConflictError(
                    f"A Data Type named '{name}' already exists",
                    details=[
                        {"loc": ["body", "name"], "msg": "name already exists", "type": "unique"}
                    ],
                ) from exc
            if constraint == FK_LINK_DATA_TYPE:
                raise ConflictError("Data Type is referenced by a Data Set") from exc
            raise
