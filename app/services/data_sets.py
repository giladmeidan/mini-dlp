from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import DataSet, DataType
from app.models.base import utcnow
from app.models.data_set import FK_LINK_DATA_TYPE, UQ_DATA_SETS_NAME
from app.repositories.data_sets import DataSetRepository
from app.schemas.data_set import DataSetIn


class DataSetService:
    """Business rules and the unit of work for Data Sets (D17, D19)."""

    def __init__(self, session: Session):
        self.session = session
        self.repo = DataSetRepository(session)

    def create(self, data: DataSetIn) -> DataSet:
        dts = self._resolve_data_types(data.data_type_ids)
        ds = DataSet(name=data.name, data_types=dts)
        self.repo.add(ds)
        # No name pre-check (D18): the unique index decides, and _commit maps its error.
        self._commit(name=data.name)
        return ds

    def get(self, id: UUID) -> DataSet:
        return self._get_or_404(id)

    def list_all(self) -> list[DataSet]:
        return self.repo.list_all()

    def update(self, id: UUID, data: DataSetIn) -> DataSet:
        # Row lock: without it two concurrent PUTs diff membership from stale snapshots and
        # fail with StaleDataError or a duplicate link row, both 500s (D19).
        ds = self._get_or_404(id, for_update=True)
        dts = self._resolve_data_types(data.data_type_ids)
        ds.name = data.name
        # Assign a new list: SQLAlchemy diffs it against the loaded one and writes only the
        # link rows that changed.
        ds.data_types = dts
        # Always, even if only membership changed: link rows don't touch the data_sets row (D16).
        ds.updated_at = utcnow()
        self._commit(name=data.name)
        return ds

    def delete(self, id: UUID) -> None:
        # Same lock as update, so a delete cannot interleave with a concurrent membership change.
        ds = self._get_or_404(id, for_update=True)
        # No 409 path: the link rows belong to the set and go with it (D7).
        self.repo.delete(ds)
        self._commit()

    def _get_or_404(self, id: UUID, *, for_update: bool = False) -> DataSet:
        ds = self.repo.get(id, for_update=for_update)
        if ds is None:
            raise NotFoundError(f"Data Set {id} not found")
        return ds

    def _resolve_data_types(self, ids: list[UUID]) -> list[DataType]:
        """The Data Types for `ids` (de-duplicated), or a 422 naming each missing position."""
        unique = list(dict.fromkeys(ids))  # order-preserving de-dup
        found = self.repo.get_data_types_by_ids(unique)
        found_ids = {dt.id for dt in found}
        # Positions in the body as sent, every occurrence, mirroring Pydantic's loc convention.
        missing = [i for i, dt_id in enumerate(ids) if dt_id not in found_ids]
        if missing:
            raise UnprocessableError(
                f"{len({ids[i] for i in missing})} Data Type id(s) do not exist",
                details=[
                    {
                        "loc": ["body", "data_type_ids", i],
                        "msg": "Data Type not found",
                        "type": "not_found",
                        "ctx": {"data_type_id": str(ids[i])},
                    }
                    for i in missing
                ],
            )
        # Already ordered by created_at, id (see the repository).
        return found

    def _commit(self, *, name: str | None = None) -> None:
        """Commit, mapping known constraint violations by constraint name (D18)."""
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == UQ_DATA_SETS_NAME:
                # Built from `name`, not the ORM object: rollback expired its attributes.
                raise ConflictError(
                    f"A Data Set named '{name}' already exists",
                    details=[
                        {"loc": ["body", "name"], "msg": "name already exists", "type": "unique"}
                    ],
                ) from exc
            if constraint == FK_LINK_DATA_TYPE:
                # Same constraint as the Data Types service's RESTRICT backstop, different
                # meaning: here a link row was INSERTed for a Data Type deleted after
                # _resolve_data_types checked it.
                # That is why the mapping lives in each service, not in a shared helper.
                # A retry re-runs _resolve_data_types and returns the positional 422.
                raise UnprocessableError(
                    "A referenced Data Type no longer exists; retry to see which"
                ) from exc
            raise
