from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.db import SessionDep
from app.core.errors import NOT_FOUND_RESPONSE, PAYLOAD_TOO_LARGE_RESPONSE
from app.schemas.scan import ScanIn, ScanMatch, ScanNoMatch, ScanOut
from app.services.scan import ScanService


def get_scan_service(db: SessionDep) -> ScanService:
    return ScanService(db, max_text_chars=get_settings().MAX_SCAN_TEXT_CHARS)


ServiceDep = Annotated[ScanService, Depends(get_scan_service)]

router = APIRouter(prefix="/api/scan", tags=["scan"])


# 200, not 201: nothing is created. POST: the text is a payload, possibly megabytes.
@router.post(
    "",
    response_model=ScanOut,
    responses={**NOT_FOUND_RESPONSE, **PAYLOAD_TOO_LARGE_RESPONSE},
)
def scan_text(data: ScanIn, service: ServiceDep) -> ScanMatch | ScanNoMatch:
    """Scan `text` against the Data Set.

    200 with the verdict; 404 unknown Data Set; 413 text too long.
    """
    return service.scan(data)
