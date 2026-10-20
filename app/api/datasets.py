from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.db import SessionDep
from app.core.errors import CONFLICT_RESPONSE, NOT_FOUND_RESPONSE
from app.models import DataSet
from app.schemas.data_set import DataSetIn, DataSetOut
from app.services.data_sets import DataSetService


def get_data_set_service(db: SessionDep) -> DataSetService:
    return DataSetService(db)


ServiceDep = Annotated[DataSetService, Depends(get_data_set_service)]

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.post("", status_code=201, response_model=DataSetOut, responses=CONFLICT_RESPONSE)
def create_data_set(data: DataSetIn, service: ServiceDep) -> DataSet:
    """422 if any id in `data_type_ids` does not exist."""
    return service.create(data)


@router.get("", response_model=list[DataSetOut])
def list_data_sets(service: ServiceDep) -> list[DataSet]:
    """Newest first."""
    return service.list_all()


@router.get("/{id}", response_model=DataSetOut, responses=NOT_FOUND_RESPONSE)
def get_data_set(id: UUID, service: ServiceDep) -> DataSet:
    return service.get(id)


@router.put(
    "/{id}",
    response_model=DataSetOut,
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def update_data_set(id: UUID, data: DataSetIn, service: ServiceDep) -> DataSet:
    """Full replace of name and membership."""
    return service.update(id, data)


@router.delete("/{id}", status_code=204, responses=NOT_FOUND_RESPONSE)
def delete_data_set(id: UUID, service: ServiceDep) -> None:
    """Never 409: the set's links to Data Types go with it."""
    service.delete(id)
