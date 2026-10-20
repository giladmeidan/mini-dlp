import pytest
from pydantic import ValidationError

from app.schemas.data_type import DataTypeIn, DataTypeKind


def valid(**overrides) -> dict:
    return {"name": "SSN", "content": ["ssn"], "threshold": 1} | overrides


def error_locs(exc_info: pytest.ExceptionInfo[ValidationError]) -> list[tuple]:
    return [err["loc"] for err in exc_info.value.errors()]


def test_strips_name_description_and_keywords():
    dt = DataTypeIn.model_validate(
        valid(name="  SSN  ", description="  social  ", content=["  ssn ", "\tsocial\n"])
    )

    assert dt.name == "SSN"
    assert dt.description == "social"
    assert dt.content == ["ssn", "social"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_rejects_bad_name(name):
    with pytest.raises(ValidationError) as exc_info:
        DataTypeIn.model_validate(valid(name=name))

    assert error_locs(exc_info) == [("name",)]


def test_accepts_name_of_200_chars():
    assert DataTypeIn.model_validate(valid(name="x" * 200)).name == "x" * 200


def test_rejects_empty_content():
    with pytest.raises(ValidationError) as exc_info:
        DataTypeIn.model_validate(valid(content=[]))

    assert error_locs(exc_info) == [("content",)]


def test_whitespace_only_keyword_is_rejected_at_its_index():
    with pytest.raises(ValidationError) as exc_info:
        DataTypeIn.model_validate(valid(content=["ssn", "   "]))

    [error] = exc_info.value.errors()
    assert error["loc"] == ("content", 1)
    assert error["type"] == "string_too_short"


def test_rejects_keyword_of_201_chars():
    with pytest.raises(ValidationError) as exc_info:
        DataTypeIn.model_validate(valid(content=["x" * 201]))

    assert error_locs(exc_info) == [("content", 0)]


def test_rejects_more_than_1000_keywords():
    with pytest.raises(ValidationError) as exc_info:
        DataTypeIn.model_validate(valid(content=[f"k{i}" for i in range(1001)]))

    assert error_locs(exc_info) == [("content",)]


def test_dedupes_case_insensitively_keeping_first_spelling_and_order():
    dt = DataTypeIn.model_validate(valid(content=[" Salary ", "salary", "SSN", "SALARY", "ssn"]))

    assert dt.content == ["Salary", "SSN"]


def test_collapses_internal_whitespace_before_deduping():
    dt = DataTypeIn.model_validate(valid(content=["credit   card", "credit card", "a\t\nb"]))

    assert dt.content == ["credit card", "a b"]


def test_type_defaults_to_keywords():
    assert DataTypeIn.model_validate(valid()).type is DataTypeKind.KEYWORDS


@pytest.mark.parametrize("kind", ["KEYWORDS", "regex"])
def test_rejects_unknown_type(kind):
    with pytest.raises(ValidationError) as exc_info:
        DataTypeIn.model_validate(valid(type=kind))

    assert error_locs(exc_info) == [("type",)]


@pytest.mark.parametrize("threshold", [0, -1, "3", True, 3.0, 2**31, 1_000_001])
def test_rejects_bad_threshold(threshold):
    with pytest.raises(ValidationError) as exc_info:
        DataTypeIn.model_validate(valid(threshold=threshold))

    assert error_locs(exc_info) == [("threshold",)]


@pytest.mark.parametrize("threshold", [1, 1_000_000])
def test_accepts_threshold_bounds(threshold):
    assert DataTypeIn.model_validate(valid(threshold=threshold)).threshold == threshold


@pytest.mark.parametrize("field", ["descripton", "id", "created_at", "updated_at"])
def test_rejects_unknown_and_read_only_fields(field):
    with pytest.raises(ValidationError) as exc_info:
        DataTypeIn.model_validate(valid(**{field: "x"}))

    [error] = exc_info.value.errors()
    assert error["loc"] == (field,)
    assert error["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    ("overrides", "loc"),
    [
        ({"name": "a\x00b"}, ("name",)),
        ({"description": "a\x00b"}, ("description",)),
        ({"content": ["ok", "a\x00b"]}, ("content", 1)),
    ],
)
def test_rejects_nul_bytes(overrides, loc):
    with pytest.raises(ValidationError) as exc_info:
        DataTypeIn.model_validate(valid(**overrides))

    assert error_locs(exc_info) == [loc]
