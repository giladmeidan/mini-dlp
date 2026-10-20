import uuid
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, PayloadTooLargeError
from app.schemas.scan import ScanIn
from app.services.scan import ScanService

# "😀" is one code point and four UTF-8 bytes: these tests pin code points over bytes.


def scan_in(text: str) -> ScanIn:
    return ScanIn.model_validate({"text": text, "data_set_id": str(uuid.uuid4())})


def test_text_at_the_limit_in_code_points_passes_the_size_check():
    session = Mock(spec=Session)
    session.get.return_value = None  # the Data Set lookup finds nothing

    # 12 bytes, 3 code points: reaching the lookup's 404 proves the size check let it through.
    with pytest.raises(NotFoundError):
        ScanService(session, max_text_chars=3).scan(scan_in("😀" * 3))


def test_text_over_the_limit_in_code_points_is_413_before_any_db_work():
    session = Mock(spec=Session)

    with pytest.raises(PayloadTooLargeError) as exc_info:
        ScanService(session, max_text_chars=3).scan(scan_in("😀" * 4))

    [detail] = exc_info.value.details
    assert detail.loc == ["body", "text"]
    assert detail.type == "too_long"
    assert detail.ctx == {"max_chars": "3", "chars": "4"}
    assert session.mock_calls == []
