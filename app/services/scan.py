import logging
import time

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, PayloadTooLargeError
from app.repositories.data_sets import DataSetRepository

# Module import: the service method is also named `scan`, and the pool-spy test monkeypatches
# `engine.scan`.
from app.scan import engine
from app.schemas.scan import DetectedObject, ScanIn, ScanMatch, ScanNoMatch

logger = logging.getLogger(__name__)


class ScanService:
    """Loads the policy, hands pure rules to the engine, maps the verdict (D17 on a read)."""

    def __init__(self, session: Session, *, max_text_chars: int):
        self.session = session
        self.repo = DataSetRepository(session)
        # Injected by the router, so the service has no dependency on settings or environment.
        self.max_text_chars = max_text_chars

    def scan(self, data: ScanIn) -> ScanMatch | ScanNoMatch:
        chars = len(data.text)  # code points, not bytes: what the engine's cost scales with
        # Before the lookup, so an over-long text is a 413 even for an unknown Data Set (D20).
        if chars > self.max_text_chars:
            raise PayloadTooLargeError(
                f"text has {chars} characters; the limit is {self.max_text_chars}",
                details=[
                    {
                        "loc": ["body", "text"],
                        "msg": f"at most {self.max_text_chars} characters",
                        # Ours, deliberately not Pydantic's string_too_long.
                        "type": "too_long",
                        "ctx": {"max_chars": str(self.max_text_chars), "chars": str(chars)},
                    }
                ],
            )
        ds = self.repo.get(data.data_set_id)
        if ds is None:
            # 404, not 422: the Data Set is the target of the scan, not a reference (D20).
            raise NotFoundError(
                f"Data Set {data.data_set_id} not found",
                details=[
                    {
                        "loc": ["body", "data_set_id"],
                        "msg": "Data Set not found",
                        "type": "not_found",
                    }
                ],
            )
        # Copied into frozen dataclasses: no ORM reference survives the rollback below.
        # A deleted Data Type cannot be a member (D7), so the membership is trusted as loaded.
        rules = [
            engine.KeywordRule(dt.id, dt.name, tuple(dt.content), dt.threshold)
            for dt in ds.data_types
        ]
        # End the read transaction and give the connection back before the CPU-bound pass
        # (D20). rollback() expires every loaded attribute: never touch `ds` after this line,
        # or it silently re-queries and holds a connection for the whole scan.
        self.session.rollback()
        started = time.perf_counter()
        detections = engine.scan(data.text, rules)
        engine_ms = (time.perf_counter() - started) * 1000
        # Counts only: the text is the sensitive data and is never logged.
        logger.info(
            "scan data_set=%s chars=%d rules=%d detected=%d engine_ms=%.1f",
            data.data_set_id,
            chars,
            len(rules),
            len(detections),
            engine_ms,
        )
        if not detections:
            return ScanNoMatch()
        # Already ordered match_count DESC, name ASC, id ASC by the engine (D10).
        return ScanMatch(detected_objects=[DetectedObject.model_validate(d) for d in detections])
