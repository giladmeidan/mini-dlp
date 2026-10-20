from datetime import UTC, datetime

from sqlalchemy.engine.default import DefaultExecutionContext


def utcnow() -> datetime:
    return datetime.now(UTC)


def copy_created_at(context: DefaultExecutionContext) -> datetime:
    """SQLAlchemy passes the INSERT parameters; a new row starts with updated_at == created_at."""
    return context.get_current_parameters()["created_at"]
