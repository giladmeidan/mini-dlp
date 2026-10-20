import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import DataSet, DataType, data_set_data_types
from app.repositories.data_types import DataTypeRepository

URL = "/api/datatypes"


def body(**overrides) -> dict:
    return {
        "name": "SSN",
        "description": "US social security number",
        "type": "keywords",
        "content": ["ssn", "social security"],
        "threshold": 2,
    } | overrides


def seed(db_session, **overrides) -> DataType:
    fields = {"name": "Seeded", "type": "keywords", "content": ["k"], "threshold": 1} | overrides
    dt = DataType(**fields)
    db_session.add(dt)
    db_session.commit()
    return dt


def assert_error(response, status_code: int, code: str) -> dict:
    assert response.status_code == status_code
    error = response.json()["error"]
    assert error["code"] == code
    return error


# --- POST ---------------------------------------------------------------------------------------


def test_create_returns_201_with_id_and_equal_timestamps(client):
    response = client.post(URL, json=body())

    assert response.status_code == 201
    data = response.json()
    uuid.UUID(data["id"])
    assert data["created_at"] == data["updated_at"]
    assert {k: data[k] for k in body()} == body()


def test_create_normalises_keywords_in_response_and_storage(client, db_session):
    response = client.post(URL, json=body(content=[" Salary ", "salary", "SSN"]))

    assert response.status_code == 201
    assert response.json()["content"] == ["Salary", "SSN"]
    stored = db_session.get(DataType, uuid.UUID(response.json()["id"]))
    assert stored.content == ["Salary", "SSN"]


def test_create_duplicate_name_in_other_case_is_409(client):
    assert client.post(URL, json=body(name="SSN")).status_code == 201

    error = assert_error(client.post(URL, json=body(name="ssn")), 409, "CONFLICT")

    assert error["message"] == "A Data Type named 'ssn' already exists"
    assert error["details"] == [
        {"loc": ["body", "name"], "msg": "name already exists", "type": "unique"}
    ]


def test_create_duplicate_name_after_stripping_is_409(client):
    assert client.post(URL, json=body(name="SSN ")).status_code == 201

    assert_error(client.post(URL, json=body(name="ssn")), 409, "CONFLICT")


def test_create_invalid_body_is_422_envelope_with_loc(client):
    response = client.post(URL, json=body(content=["ssn", "  "], threshold="3"))

    error = assert_error(response, 422, "VALIDATION_ERROR")
    locs = [detail["loc"] for detail in error["details"]]
    assert ["body", "content", 1] in locs
    assert ["body", "threshold"] in locs
    assert all("ctx" not in detail for detail in error["details"])


def test_create_rejects_nul_byte_with_422(client):
    assert_error(client.post(URL, json=body(name="a\x00b")), 422, "VALIDATION_ERROR")


# --- GET ----------------------------------------------------------------------------------------


def test_list_is_newest_first_with_ties_broken_by_id(client, db_session):
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    first = seed(db_session, name="t0", created_at=t0)
    second = seed(db_session, name="t1", created_at=t0 + timedelta(seconds=1))
    third = seed(db_session, name="t2", created_at=t0 + timedelta(seconds=2))
    tie_a = seed(db_session, name="tie-a", created_at=t0 - timedelta(seconds=1))
    tie_b = seed(db_session, name="tie-b", created_at=t0 - timedelta(seconds=1))
    # Python orders UUIDs by their 128-bit value, as Postgres does.
    ties = sorted([tie_a.id, tie_b.id])

    response = client.get(URL)

    assert response.status_code == 200
    assert [uuid.UUID(item["id"]) for item in response.json()] == [
        third.id,
        second.id,
        first.id,
        *ties,
    ]


def test_list_empty(client):
    response = client.get(URL)

    assert response.status_code == 200
    assert response.json() == []


def test_get_by_id(client):
    created = client.post(URL, json=body()).json()

    response = client.get(f"{URL}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_id_is_404(client):
    missing = uuid.uuid4()

    error = assert_error(client.get(f"{URL}/{missing}"), 404, "NOT_FOUND")

    assert error["message"] == f"Data Type {missing} not found"


def test_get_malformed_id_is_422(client):
    error = assert_error(client.get(f"{URL}/not-a-uuid"), 422, "VALIDATION_ERROR")

    assert error["details"][0]["loc"] == ["path", "id"]


# --- PUT ----------------------------------------------------------------------------------------


def test_put_replaces_all_fields_and_bumps_updated_at(client, db_session):
    created_at = datetime.now(UTC) - timedelta(hours=1)
    dt = seed(db_session, name="Old", description="old", content=["old"], created_at=created_at)
    new = body(name="New", description="new", content=["a", "b"], threshold=5)

    response = client.put(f"{URL}/{dt.id}", json=new)

    assert response.status_code == 200
    data = response.json()
    assert {k: data[k] for k in new} == new
    assert datetime.fromisoformat(data["created_at"]) == created_at
    assert datetime.fromisoformat(data["updated_at"]) > created_at
    stored = client.get(f"{URL}/{dt.id}").json()
    assert stored == data


def test_put_echoing_get_body_is_422(client):
    created = client.post(URL, json=body()).json()

    error = assert_error(
        client.put(f"{URL}/{created['id']}", json=created), 422, "VALIDATION_ERROR"
    )

    locs = {tuple(detail["loc"]) for detail in error["details"]}
    assert locs == {("body", "id"), ("body", "created_at"), ("body", "updated_at")}


def test_put_without_description_resets_it(client):
    created = client.post(URL, json=body(description="something")).json()
    new = body()
    del new["description"]

    response = client.put(f"{URL}/{created['id']}", json=new)

    assert response.status_code == 200
    assert response.json()["description"] == ""


def test_put_name_taken_by_another_data_type_is_409(client):
    client.post(URL, json=body(name="SSN"))
    other = client.post(URL, json=body(name="Salary")).json()

    error = assert_error(client.put(f"{URL}/{other['id']}", json=body(name="ssn")), 409, "CONFLICT")

    assert error["details"][0]["loc"] == ["body", "name"]
    # The failed rename was rolled back.
    assert client.get(f"{URL}/{other['id']}").json()["name"] == "Salary"


def test_put_own_name_in_other_case_is_200(client):
    created = client.post(URL, json=body(name="SSN")).json()

    response = client.put(f"{URL}/{created['id']}", json=body(name="ssn"))

    assert response.status_code == 200
    assert response.json()["name"] == "ssn"


def test_put_unknown_id_with_valid_body_is_404(client):
    assert_error(client.put(f"{URL}/{uuid.uuid4()}", json=body()), 404, "NOT_FOUND")


def test_put_unknown_id_with_invalid_body_is_422(client):
    response = client.put(f"{URL}/{uuid.uuid4()}", json=body(threshold=0))

    assert_error(response, 422, "VALIDATION_ERROR")


# --- DELETE -------------------------------------------------------------------------------------


def test_delete_returns_204_then_404(client):
    created = client.post(URL, json=body()).json()

    response = client.delete(f"{URL}/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert_error(client.get(f"{URL}/{created['id']}"), 404, "NOT_FOUND")


def test_delete_unknown_id_is_404(client):
    assert_error(client.delete(f"{URL}/{uuid.uuid4()}"), 404, "NOT_FOUND")


def link_count(db_session, dt: DataType) -> int:
    stmt = select(func.count()).where(data_set_data_types.c.data_type_id == dt.id)
    return db_session.scalar(stmt)


def test_delete_referenced_data_type_is_409_listing_data_sets(client, db_session):
    dt = seed(db_session)
    payroll = DataSet(name="Payroll", data_types=[dt])
    hr = DataSet(name="HR", data_types=[dt])
    db_session.add_all([payroll, hr])
    db_session.commit()

    error = assert_error(client.delete(f"{URL}/{dt.id}"), 409, "CONFLICT")

    assert error["message"] == "Data Type is referenced by 2 Data Set(s)"
    # Ordered by Data Set name.
    assert error["details"] == [
        {
            "loc": ["path", "id"],
            "msg": f"referenced by Data Set '{ds.name}'",
            "type": "referenced_by",
            "ctx": {"data_set_id": str(ds.id), "data_set_name": ds.name},
        }
        for ds in (hr, payroll)
    ]
    assert client.get(f"{URL}/{dt.id}").status_code == 200
    assert link_count(db_session, dt) == 2


def test_delete_referenced_data_type_is_409_from_on_delete_restrict(
    client, db_session, monkeypatch
):
    # Skip the service's check so the DELETE reaches Postgres, as in a concurrent-link race.
    monkeypatch.setattr(DataTypeRepository, "referencing_data_sets", lambda self, id: [])
    dt = seed(db_session)
    db_session.add(DataSet(name="HR", data_types=[dt]))
    db_session.commit()

    error = assert_error(client.delete(f"{URL}/{dt.id}"), 409, "CONFLICT")

    assert error["message"] == "Data Type is referenced by a Data Set"
    assert error["details"] == []
    assert client.get(f"{URL}/{dt.id}").status_code == 200
    assert link_count(db_session, dt) == 1
