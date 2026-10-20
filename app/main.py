import logging

from fastapi import FastAPI

from app.api import datasets, datatypes, health, scan
from app.core.errors import DEFAULT_ERROR_RESPONSES, register_error_handlers


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = FastAPI(title="Mini DLP", version="0.1.0", responses=DEFAULT_ERROR_RESPONSES)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(datatypes.router)
    app.include_router(datasets.router)
    app.include_router(scan.router)
    return app


app = create_app()
