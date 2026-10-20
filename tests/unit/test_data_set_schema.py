import uuid

import pytest
from pydantic import ValidationError

from app.schemas.data_set import MAX_DATA_TYPES_PER_SET, DataSetIn


def valid(**overrides) -> dict:
    return {"name": "Payroll", "data_type_ids": [str(uuid.uuid4())]} | overrides


def error_locs(exc_info: pytest.ExceptionInfo[ValidationError]) -> list[tuple]:
    return [err["loc"] for err in exc_info.value.errors()]


def test_strips_name():
    assert DataSetIn.model_validate(valid(name="  Payroll  ")).name == "Payroll"


@pytest.mark.parametrize("name", ["", "   ", "x" * 201, "a\x00b"])
def test_rejects_bad_name(name):
    with pytest.raises(ValidationError) as exc_info:
        DataSetIn.model_validate(valid(name=name))

    assert error_locs(exc_info) == [("name",)]


def test_data_type_ids_is_required():
    with pytest.raises(ValidationError) as exc_info:
        DataSetIn.model_validate({"name": "Payroll"})

    [error] = exc_info.value.errors()
    assert error["loc"] == ("data_type_ids",)
    assert error["type"] == "missing"


def test_accepts_explicit_empty_data_type_ids():
    assert DataSetIn.model_validate(valid(data_type_ids=[])).data_type_ids == []


def test_accepts_the_maximum_number_of_ids():
    ids = [str(uuid.uuid4()) for _ in range(MAX_DATA_TYPES_PER_SET)]

    assert (
        len(DataSetIn.model_validate(valid(data_type_ids=ids)).data_type_ids)
        == MAX_DATA_TYPES_PER_SET
    )


def test_rejects_more_than_100_ids():
    ids = [str(uuid.uuid4()) for _ in range(MAX_DATA_TYPES_PER_SET + 1)]

    with pytest.raises(ValidationError) as exc_info:
        DataSetIn.model_validate(valid(data_type_ids=ids))

    assert error_locs(exc_info) == [("data_type_ids",)]


def test_malformed_uuid_is_rejected_at_its_index():
    with pytest.raises(ValidationError) as exc_info:
        DataSetIn.model_validate(valid(data_type_ids=[str(uuid.uuid4()), "not-a-uuid"]))

    [error] = exc_info.value.errors()
    assert error["loc"] == ("data_type_ids", 1)
    assert error["type"] == "uuid_parsing"


def test_keeps_duplicates_for_the_service_to_collapse():
    dt_id = uuid.uuid4()

    data = DataSetIn.model_validate(valid(data_type_ids=[str(dt_id), str(dt_id)]))

    assert data.data_type_ids == [dt_id, dt_id]


@pytest.mark.parametrize("field", ["nmae", "id", "created_at", "updated_at"])
def test_rejects_unknown_and_read_only_fields(field):
    with pytest.raises(ValidationError) as exc_info:
        DataSetIn.model_validate(valid(**{field: "x"}))

    [error] = exc_info.value.errors()
    assert error["loc"] == (field,)
    assert error["type"] == "extra_forbidden"
