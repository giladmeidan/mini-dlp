import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops"])


@router.get("/health")
def health(db: SessionDep) -> JSONResponse:
    """Readiness check: compose waits on it, so it must fail when the database is down."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Health check failed: %s", exc)
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "error"})
    return JSONResponse(status_code=200, content={"status": "ok", "db": "ok"})
