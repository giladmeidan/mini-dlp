import uuid

import pytest
from pydantic import ValidationError

from app.scan.engine import Detection
from app.schemas.scan import DetectedObject, ScanIn, ScanMatch, ScanNoMatch

# Python mode (model_validate), as the API path validates after json.loads (D20).


def valid(**overrides) -> dict:
    return {"text": "hello", "data_set_id": str(uuid.uuid4())} | overrides


@pytest.mark.parametrize("text", ["", "  padded  ", "a\x00b"])
def test_text_is_kept_verbatim(text):
    # Empty allowed, no strip, NUL allowed: the text is scanned, never stored.
    assert ScanIn.model_validate(valid(text=text)).text == text


def test_schema_has_no_size_limit():
    # The limit is the service's 413, not a schema 422.
    text = "a" * 2_000_000

    assert ScanIn.model_validate(valid(text=text)).text == text


def test_rejects_unknown_field():
    with pytest.raises(ValidationError) as exc_info:
        ScanIn.model_validate(valid(txet="x"))

    [error] = exc_info.value.errors()
    assert error["loc"] == ("txet",)
    assert error["type"] == "extra_forbidden"


def test_text_is_not_coerced():
    with pytest.raises(ValidationError) as exc_info:
        ScanIn.model_validate(valid(text=123))

    [error] = exc_info.value.errors()
    assert error["loc"] == ("text",)
    assert error["type"] == "string_type"


def test_no_match_dumps_only_status():
    assert ScanNoMatch().model_dump() == {"status": "not matched"}


def test_match_rejects_empty_detected_objects():
    with pytest.raises(ValidationError) as exc_info:
        ScanMatch(detected_objects=[])

    [error] = exc_info.value.errors()
    assert error["loc"] == ("detected_objects",)
    assert error["type"] == "too_short"


def test_detected_object_from_detection_has_exactly_three_keys():
    dt_id = uuid.uuid4()

    detected = DetectedObject.model_validate(Detection(dt_id, "Sensitive Keywords", 3))

    assert detected.model_dump() == {"id": dt_id, "name": "Sensitive Keywords", "match_count": 3}
