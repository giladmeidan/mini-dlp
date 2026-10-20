import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.models import DataSet, DataType
from app.scan import engine

URL = "/api/scan"
MAX = get_settings().MAX_SCAN_TEXT_CHARS


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


def body(text: str, ds_id) -> dict:
    return {"text": text, "data_set_id": str(ds_id)}


def assert_error(response, status_code: int, code: str) -> dict:
    assert response.status_code == status_code
    error = response.json()["error"]
    assert error["code"] == code
    return error


NOT_MATCHED = {"status": "not matched"}


@pytest.fixture
def db_engine(engine: Engine) -> Engine:
    """The session-scoped test `engine` fixture, renamed so it does not shadow app.scan.engine."""
    return engine


@pytest.fixture
def confidential(db_session) -> tuple[DataType, DataSet]:
    dt = seed_dt(db_session, "Confidential", content=["confidential"], threshold=2)
    return dt, seed_ds(db_session, "Policy", [dt])


# --- Verdicts -----------------------------------------------------------------------------------


def test_match_has_exactly_the_instructions_shape(client, confidential):
    dt, ds = confidential
    text = "Confidential memo. Keep it confidential; confidentiality matters."

    response = client.post(URL, json=body(text, ds.id))

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "status": "match",
        "detected_objects": [{"id": str(dt.id), "name": dt.name, "match_count": 2}],
    }
    # Key order as in the assignment's example.
    assert list(data) == ["status", "detected_objects"]
    assert list(data["detected_objects"][0]) == ["id", "name", "match_count"]


def test_below_threshold_is_not_matched_without_detected_objects(client, confidential):
    _, ds = confidential

    response = client.post(URL, json=body("Confidential memo.", ds.id))

    assert response.status_code == 200
    assert response.json() == NOT_MATCHED


def test_detected_objects_keep_engine_order_and_omit_below_threshold(client, db_session):
    dt3 = seed_dt(db_session, "three", content=["gamma"])
    dt_b = seed_dt(db_session, "b", content=["beta"])
    dt_a = seed_dt(db_session, "a", content=["alpha"])
    below = seed_dt(db_session, "below", content=["delta"], threshold=2)
    ds = seed_ds(db_session, "Policy", [dt3, dt_b, dt_a, below])

    response = client.post(URL, json=body("gamma beta gamma alpha delta gamma", ds.id))

    assert response.status_code == 200
    detected = response.json()["detected_objects"]
    assert [uuid.UUID(d["id"]) for d in detected] == [dt3.id, dt_a.id, dt_b.id]
    assert [d["match_count"] for d in detected] == [3, 1, 1]


def test_empty_data_set_is_not_matched(client, db_session):
    ds = seed_ds(db_session, "Empty")

    response = client.post(URL, json=body("confidential confidential", ds.id))

    assert response.status_code == 200
    assert response.json() == NOT_MATCHED


def test_empty_text_is_not_matched(client, confidential):
    _, ds = confidential

    response = client.post(URL, json=body("", ds.id))

    assert response.status_code == 200
    assert response.json() == NOT_MATCHED


def test_case_insensitive_whole_word_through_the_api(client, db_session):
    dt = seed_dt(db_session, "Cards", content=["card"])
    ds = seed_ds(db_session, "Policy", [dt])

    response = client.post(URL, json=body("CARD card cardholder", ds.id))

    assert response.status_code == 200
    assert response.json()["detected_objects"][0]["match_count"] == 2


# --- Errors -------------------------------------------------------------------------------------


def test_unknown_data_set_is_404_with_body_loc(client):
    missing = uuid.uuid4()

    error = assert_error(client.post(URL, json=body("text", missing)), 404, "NOT_FOUND")

    assert error["message"] == f"Data Set {missing} not found"
    assert error["details"] == [
        {"loc": ["body", "data_set_id"], "msg": "Data Set not found", "type": "not_found"}
    ]


def test_malformed_data_set_id_is_422_envelope(client):
    response = client.post(URL, json={"text": "text", "data_set_id": "not-a-uuid"})

    error = assert_error(response, 422, "VALIDATION_ERROR")
    assert [detail["loc"] for detail in error["details"]] == [["body", "data_set_id"]]


def test_text_over_the_limit_is_413_before_the_data_set_lookup(client):
    # A random id: a 404 here would mean the lookup ran first.
    response = client.post(URL, json=body("a" * (MAX + 1), uuid.uuid4()))

    error = assert_error(response, 413, "PAYLOAD_TOO_LARGE")
    [detail] = error["details"]
    assert detail["loc"] == ["body", "text"]
    assert detail["type"] == "too_long"
    assert detail["ctx"] == {"max_chars": str(MAX), "chars": str(MAX + 1)}


def test_text_exactly_at_the_limit_is_scanned(client, confidential):
    _, ds = confidential

    response = client.post(URL, json=body("a" * MAX, ds.id))

    assert response.status_code == 200
    assert response.json() == NOT_MATCHED


# --- No caching (D11) ---------------------------------------------------------------------------


def test_data_type_edit_is_used_by_the_next_scan(client, confidential):
    dt, ds = confidential
    scan = body("confidential confidential", ds.id)
    assert client.post(URL, json=scan).json()["status"] == "match"

    put = {"name": dt.name, "content": ["secret"], "threshold": 2}
    assert client.put(f"/api/datatypes/{dt.id}", json=put).status_code == 200

    assert client.post(URL, json=scan).json() == NOT_MATCHED


def test_membership_change_is_used_by_the_next_scan(client, confidential):
    _, ds = confidential
    scan = body("confidential confidential", ds.id)
    assert client.post(URL, json=scan).json()["status"] == "match"

    put = {"name": ds.name, "data_type_ids": []}
    assert client.put(f"/api/datasets/{ds.id}", json=put).status_code == 200

    assert client.post(URL, json=scan).json() == NOT_MATCHED


# --- Transaction and side effects ---------------------------------------------------------------


def test_pool_has_no_connection_checked_out_while_the_engine_runs(
    client, confidential, db_engine, monkeypatch
):
    _, ds = confidential
    real_scan = engine.scan
    checked_out = []

    def spy(text, rules):
        checked_out.append(db_engine.pool.checkedout())
        return real_scan(text, rules)

    # Patched on the module object the service calls through.
    monkeypatch.setattr(engine, "scan", spy)

    response = client.post(URL, json=body("confidential confidential", ds.id))

    assert checked_out == [0]
    assert response.json()["status"] == "match"


def test_scan_writes_nothing(client, db_session):
    seeded = datetime.now(UTC) - timedelta(hours=1)
    dt = seed_dt(
        db_session, "Confidential", content=["confidential"], created_at=seeded, updated_at=seeded
    )
    ds = seed_ds(db_session, "Policy", [dt], created_at=seeded, updated_at=seeded)

    response = client.post(URL, json=body("confidential", ds.id))

    assert response.json()["status"] == "match"
    assert db_session.scalar(select(DataType.updated_at).where(DataType.id == dt.id)) == seeded
    assert db_session.scalar(select(DataSet.updated_at).where(DataSet.id == ds.id)) == seeded


def test_one_info_log_line_per_scan_without_the_text(client, confidential, caplog):
    _, ds = confidential
    token = "SECRET-TOKEN-9f1c"
    caplog.set_level(logging.INFO, logger="app.services.scan")

    response = client.post(URL, json=body(f"confidential {token} confidential", ds.id))

    assert response.status_code == 200
    [record] = [r for r in caplog.records if r.name == "app.services.scan"]
    assert record.levelno == logging.INFO
    message = record.getMessage()
    for field in ("data_set=", "chars=", "detected=", "engine_ms="):
        assert field in message
    assert f"data_set={ds.id}" in message
    assert token not in caplog.text


# --- OpenAPI ------------------------------------------------------------------------------------


def test_openapi_documents_the_contract(client):
    spec = client.get("/openapi.json").json()

    assert [path for path in spec["paths"] if path.startswith(URL)] == [URL]
    assert list(spec["paths"][URL]) == ["post"]
    responses = spec["paths"][URL]["post"]["responses"]
    assert {"404", "413", "422"} <= set(responses)

    schema = responses["200"]["content"]["application/json"]["schema"]
    assert "oneOf" in schema
    assert schema["discriminator"]["propertyName"] == "status"
    assert set(schema["discriminator"]["mapping"]) == {"match", "not matched"}
    for ref in schema["oneOf"]:
        name = ref["$ref"].rsplit("/", 1)[-1]
        assert "status" in spec["components"]["schemas"][name]["required"]
