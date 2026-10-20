import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, func, select, text

from app.core.errors import UnprocessableError
from app.models import DataSet, DataType, data_set_data_types
from app.repositories.data_sets import DataSetRepository
from app.schemas.data_set import DataSetIn
from app.services.data_sets import DataSetService

URL = "/api/datasets"


def seed_dt(db_session, name: str, **overrides) -> DataType:
    fields = {"name": name, "type": "keywords", "content": ["k"], "threshold": 1} | overrides
    dt = DataType(**fields)
    db_session.add(dt)
    db_session.commit()
    return dt


def seed_ds(db_session, name: str = "Payroll", data_types=(), **overrides) -> DataSet:
    ds = DataSet(name=name, data_types=list(data_types), **overrides)
    db_session.add(ds)
    db_session.commit()
    return ds


def body(name: str = "Payroll", ids=()) -> dict:
    return {"name": name, "data_type_ids": [str(i) for i in ids]}


def ids_of(response) -> list[uuid.UUID]:
    return [uuid.UUID(i) for i in response.json()["data_type_ids"]]


def assert_error(response, status_code: int, code: str) -> dict:
    assert response.status_code == status_code
    error = response.json()["error"]
    assert error["code"] == code
    return error


def link_count(db_session, ds_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(data_set_data_types.c.data_set_id == ds_id)
    return db_session.scalar(stmt)


def data_set_count(db_session) -> int:
    return db_session.scalar(select(func.count()).select_from(DataSet))


def not_found_detail(index: int, dt_id: uuid.UUID) -> dict:
    return {
        "loc": ["body", "data_type_ids", index],
        "msg": "Data Type not found",
        "type": "not_found",
        "ctx": {"data_type_id": str(dt_id)},
    }


# --- POST ---------------------------------------------------------------------------------------


def test_create_returns_ids_ordered_by_data_type_created_at(client, db_session):
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    a = seed_dt(db_session, "a", created_at=t0 + timedelta(seconds=2))  # newest
    b = seed_dt(db_session, "b", created_at=t0 + timedelta(seconds=1))
    c = seed_dt(db_session, "c", created_at=t0)  # oldest

    response = client.post(URL, json=body(ids=[b.id, a.id, c.id]))

    assert response.status_code == 201
    data = response.json()
    assert ids_of(response) == [c.id, b.id, a.id]
    assert data["created_at"] == data["updated_at"]
    assert client.get(f"{URL}/{data['id']}").json() == data


def test_create_with_empty_list_is_201(client):
    response = client.post(URL, json=body(ids=[]))

    assert response.status_code == 201
    assert response.json()["data_type_ids"] == []


def test_create_without_data_type_ids_is_422(client):
    error = assert_error(client.post(URL, json={"name": "Payroll"}), 422, "VALIDATION_ERROR")

    assert [detail["loc"] for detail in error["details"]] == [["body", "data_type_ids"]]


def test_create_collapses_duplicate_ids(client, db_session):
    dt = seed_dt(db_session, "SSN")

    response = client.post(URL, json=body(ids=[dt.id, dt.id]))

    assert response.status_code == 201
    assert ids_of(response) == [dt.id]
    assert link_count(db_session, uuid.UUID(response.json()["id"])) == 1


def test_create_with_unknown_id_is_422_at_every_position(client, db_session):
    dt = seed_dt(db_session, "SSN")
    unknown = uuid.uuid4()

    response = client.post(URL, json=body(ids=[dt.id, unknown, unknown]))

    error = assert_error(response, 422, "VALIDATION_ERROR")
    assert error["message"] == "1 Data Type id(s) do not exist"
    assert error["details"] == [not_found_detail(1, unknown), not_found_detail(2, unknown)]
    assert data_set_count(db_session) == 0


def test_create_duplicate_name_in_other_case_is_409(client):
    assert client.post(URL, json=body(name="Payroll")).status_code == 201

    error = assert_error(client.post(URL, json=body(name="PAYROLL")), 409, "CONFLICT")

    assert error["message"] == "A Data Set named 'PAYROLL' already exists"
    assert error["details"] == [
        {"loc": ["body", "name"], "msg": "name already exists", "type": "unique"}
    ]


def test_create_invalid_body_is_422_envelope_with_loc(client):
    response = client.post(URL, json={"name": "", "data_type_ids": ["not-a-uuid"]})

    error = assert_error(response, 422, "VALIDATION_ERROR")
    locs = [detail["loc"] for detail in error["details"]]
    assert ["body", "name"] in locs
    assert ["body", "data_type_ids", 0] in locs


# --- GET ----------------------------------------------------------------------------------------


def test_list_is_newest_first_with_ties_broken_by_id(client, db_session):
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    first = seed_ds(db_session, "t0", created_at=t0)
    second = seed_ds(db_session, "t1", created_at=t0 + timedelta(seconds=1))
    tie_a = seed_ds(db_session, "tie-a", created_at=t0 - timedelta(seconds=1))
    tie_b = seed_ds(db_session, "tie-b", created_at=t0 - timedelta(seconds=1))
    # Python orders UUIDs by their 128-bit value, as Postgres does.
    ties = sorted([tie_a.id, tie_b.id])

    response = client.get(URL)

    assert response.status_code == 200
    assert [uuid.UUID(item["id"]) for item in response.json()] == [second.id, first.id, *ties]


def test_list_loads_member_ids_without_keyword_arrays(client, db_session, engine):
    dt = seed_dt(db_session, "SSN", content=["ssn", "social security"])
    seed_ds(db_session, "Payroll", [dt])
    seed_ds(db_session, "HR", [dt])
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(URL)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 200
    assert [item["data_type_ids"] for item in response.json()] == [[str(dt.id)]] * 2
    # The data sets, then one selectin query for every set's members.
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 2
    [members] = [s for s in selects if "data_set_data_types" in s]
    assert "content" not in members


def test_get_by_id(client, db_session):
    dt = seed_dt(db_session, "SSN")
    created = client.post(URL, json=body(ids=[dt.id])).json()

    response = client.get(f"{URL}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_id_is_404(client):
    missing = uuid.uuid4()

    error = assert_error(client.get(f"{URL}/{missing}"), 404, "NOT_FOUND")

    assert error["message"] == f"Data Set {missing} not found"


def test_get_malformed_id_is_422(client):
    error = assert_error(client.get(f"{URL}/not-a-uuid"), 422, "VALIDATION_ERROR")

    assert error["details"][0]["loc"] == ["path", "id"]


# --- PUT ----------------------------------------------------------------------------------------


def test_put_replaces_name_and_membership(client, db_session):
    old_dt = seed_dt(db_session, "Old")
    new_dt = seed_dt(db_session, "New")
    created_at = datetime.now(UTC) - timedelta(hours=1)
    ds = seed_ds(db_session, "Old", [old_dt], created_at=created_at)

    response = client.put(f"{URL}/{ds.id}", json=body(name="New", ids=[new_dt.id]))

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New"
    assert ids_of(response) == [new_dt.id]
    assert datetime.fromisoformat(data["created_at"]) == created_at
    assert datetime.fromisoformat(data["updated_at"]) > created_at
    assert client.get(f"{URL}/{ds.id}").json() == data


def test_put_membership_only_bumps_updated_at(client, db_session):
    dt1 = seed_dt(db_session, "SSN")
    dt2 = seed_dt(db_session, "Salary")
    seeded = datetime.now(UTC) - timedelta(hours=1)
    ds = seed_ds(db_session, "Payroll", [dt1], created_at=seeded, updated_at=seeded)

    response = client.put(f"{URL}/{ds.id}", json=body(name="Payroll", ids=[dt2.id]))

    assert response.status_code == 200
    assert ids_of(response) == [dt2.id]
    assert datetime.fromisoformat(response.json()["created_at"]) == seeded
    assert datetime.fromisoformat(response.json()["updated_at"]) > seeded

    emptied = client.put(f"{URL}/{ds.id}", json=body(name="Payroll", ids=[]))

    assert emptied.status_code == 200
    assert emptied.json()["data_type_ids"] == []
    assert link_count(db_session, ds.id) == 0


def test_put_same_set_in_other_order_keeps_order_and_bumps_updated_at(client, db_session):
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    older = seed_dt(db_session, "older", created_at=t0)
    newer = seed_dt(db_session, "newer", created_at=t0 + timedelta(seconds=1))
    seeded = datetime.now(UTC) - timedelta(hours=1)
    ds = seed_ds(db_session, "Payroll", [older, newer], created_at=seeded, updated_at=seeded)

    response = client.put(f"{URL}/{ds.id}", json=body(name="Payroll", ids=[newer.id, older.id]))

    assert response.status_code == 200
    assert ids_of(response) == [older.id, newer.id]
    assert datetime.fromisoformat(response.json()["updated_at"]) > seeded


def test_put_unknown_id_among_duplicates_is_422_at_put_body_positions(client, db_session):
    dt = seed_dt(db_session, "SSN")
    ds = seed_ds(db_session, "Payroll", [dt])
    unknown = uuid.uuid4()

    response = client.put(f"{URL}/{ds.id}", json=body(ids=[dt.id, dt.id, unknown]))

    error = assert_error(response, 422, "VALIDATION_ERROR")
    assert error["details"] == [not_found_detail(2, unknown)]
    assert ids_of(client.get(f"{URL}/{ds.id}")) == [dt.id]


def test_put_name_taken_by_another_data_set_is_409(client):
    client.post(URL, json=body(name="Payroll"))
    other = client.post(URL, json=body(name="HR")).json()

    error = assert_error(
        client.put(f"{URL}/{other['id']}", json=body(name="payroll")), 409, "CONFLICT"
    )

    assert error["details"][0]["loc"] == ["body", "name"]
    # The failed rename was rolled back.
    assert client.get(f"{URL}/{other['id']}").json()["name"] == "HR"


def test_put_own_name_in_other_case_is_200(client):
    created = client.post(URL, json=body(name="Payroll")).json()

    response = client.put(f"{URL}/{created['id']}", json=body(name="PAYROLL"))

    assert response.status_code == 200
    assert response.json()["name"] == "PAYROLL"


def test_put_unknown_id_is_404(client):
    assert_error(client.put(f"{URL}/{uuid.uuid4()}", json=body()), 404, "NOT_FOUND")


def test_put_unknown_data_type_id_is_422(client):
    created = client.post(URL, json=body()).json()
    unknown = uuid.uuid4()

    response = client.put(f"{URL}/{created['id']}", json=body(ids=[unknown]))

    error = assert_error(response, 422, "VALIDATION_ERROR")
    assert error["details"] == [not_found_detail(0, unknown)]


# --- DELETE -------------------------------------------------------------------------------------


def test_delete_removes_links_but_not_data_types(client, db_session):
    dt1 = seed_dt(db_session, "SSN")
    dt2 = seed_dt(db_session, "Salary")
    ds = seed_ds(db_session, "Payroll", [dt1, dt2])

    response = client.delete(f"{URL}/{ds.id}")

    assert response.status_code == 204
    assert response.content == b""
    assert link_count(db_session, ds.id) == 0
    assert db_session.scalar(select(func.count()).select_from(DataType)) == 2
    assert_error(client.get(f"{URL}/{ds.id}"), 404, "NOT_FOUND")
    assert_error(client.delete(f"{URL}/{ds.id}"), 404, "NOT_FOUND")


def test_on_delete_cascade_removes_links_without_the_orm(db_session):
    dt = seed_dt(db_session, "SSN")
    ds = seed_ds(db_session, "Payroll", [dt])

    # Raw SQL: the ORM never sees the delete, so only ON DELETE CASCADE can remove the links.
    db_session.execute(text("DELETE FROM data_sets WHERE id = :id"), {"id": ds.id})
    db_session.commit()

    assert link_count(db_session, ds.id) == 0


# --- With the Data Types API --------------------------------------------------------------------


def test_referenced_data_type_can_be_deleted_only_after_detaching(client):
    dt = client.post(
        "/api/datatypes", json={"name": "SSN", "content": ["ssn"], "threshold": 1}
    ).json()
    ds = client.post(URL, json=body(name="Payroll", ids=[dt["id"]])).json()

    error = assert_error(client.delete(f"/api/datatypes/{dt['id']}"), 409, "CONFLICT")
    assert error["details"][0]["ctx"] == {"data_set_id": ds["id"], "data_set_name": "Payroll"}

    assert client.put(f"{URL}/{ds['id']}", json=body(name="Payroll", ids=[])).status_code == 200
    assert client.delete(f"/api/datatypes/{dt['id']}").status_code == 204


def test_data_type_deleted_after_resolution_is_422(db_session, engine, monkeypatch):
    # Through the service, not the client, so the stale DataType belongs to the calling session.
    dt = seed_dt(db_session, "SSN")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM data_types WHERE id = :id"), {"id": dt.id})
    # Simulate the race: resolution saw the Data Type before the concurrent delete committed.
    monkeypatch.setattr(DataSetRepository, "get_data_types_by_ids", lambda self, ids: [dt])

    with pytest.raises(UnprocessableError) as exc_info:
        DataSetService(db_session).create(DataSetIn(name="Payroll", data_type_ids=[dt.id]))

    assert exc_info.value.message == "A referenced Data Type no longer exists; retry to see which"
    assert exc_info.value.details == []
    # The session was rolled back and is usable.
    assert data_set_count(db_session) == 0
