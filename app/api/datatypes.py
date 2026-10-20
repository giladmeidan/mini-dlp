from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.db import SessionDep
from app.core.errors import CONFLICT_RESPONSE, NOT_FOUND_RESPONSE
from app.models import DataType
from app.schemas.data_type import DataTypeIn, DataTypeOut
from app.services.data_types import DataTypeService


def get_data_type_service(db: SessionDep) -> DataTypeService:
    return DataTypeService(db)


ServiceDep = Annotated[DataTypeService, Depends(get_data_type_service)]

router = APIRouter(prefix="/api/datatypes", tags=["datatypes"])


@router.post("", status_code=201, response_model=DataTypeOut, responses=CONFLICT_RESPONSE)
def create_data_type(data: DataTypeIn, service: ServiceDep) -> DataType:
    return service.create(data)


@router.get("", response_model=list[DataTypeOut])
def list_data_types(service: ServiceDep) -> list[DataType]:
    """Newest first."""
    return service.list_all()


@router.get("/{id}", response_model=DataTypeOut, responses=NOT_FOUND_RESPONSE)
def get_data_type(id: UUID, service: ServiceDep) -> DataType:
    return service.get(id)


@router.put(
    "/{id}",
    response_model=DataTypeOut,
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def update_data_type(id: UUID, data: DataTypeIn, service: ServiceDep) -> DataType:
    """Full replace: omitted optional fields are reset to their defaults."""
    return service.update(id, data)


@router.delete("/{id}", status_code=204, responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE})
def delete_data_type(id: UUID, service: ServiceDep) -> None:
    """409 while any Data Set references it."""
    service.delete(id)
