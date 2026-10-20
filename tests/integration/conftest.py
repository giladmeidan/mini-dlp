import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_db
from app.main import create_app
from app.models import Base

# Process environment, then the local .env (a developer may publish the db on another port),
# then the compose default. A missing .env yields an empty dict.
REPO_ROOT = Path(__file__).resolve().parents[2]

TEST_DATABASE_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or dotenv_values(REPO_ROOT / ".env").get("TEST_DATABASE_URL")
    or "postgresql+psycopg://dlp:dlp@localhost:5433/mini_dlp_test"
)


def _recreate_database(url: URL) -> None:
    # CREATE/DROP DATABASE cannot run inside a transaction, hence AUTOCOMMIT.
    admin_engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session")
def test_database() -> None:
    """Recreate the test database and build it with the real migrations."""
    url = make_url(TEST_DATABASE_URL)
    error = None
    try:
        _recreate_database(url)
    except OperationalError as exc:
        error = exc.orig
    if error is not None:
        # Failing outside the except block keeps the driver's long traceback out of the report.
        pytest.fail(
            f"Cannot reach the test database server at TEST_DATABASE_URL={url!r}. "
            f"Start it with `docker compose up -d --wait db`. ({error})",
            pytrace=False,
        )

    # Both paths are anchored to the repo so pytest works from any cwd.
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def engine(test_database: None) -> Iterator[Engine]:
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def testing_session_local(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def clean_tables(engine: Engine) -> None:
    """Empty every model table before each test; alembic_version is not a model table."""
    tables = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client(testing_session_local: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        # Same semantics as app.core.db.get_db, bound to the test database.
        session = testing_session_local()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client


@pytest.fixture
def db_session(testing_session_local: sessionmaker[Session]) -> Iterator[Session]:
    session = testing_session_local()
    yield session
    session.close()
