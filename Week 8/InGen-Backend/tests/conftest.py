import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def migrated_database(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            settings,
            "database_url",
            f"sqlite:///{tmp_path_factory.mktemp('telemetry') / 'test.db'}",
        )
        command.upgrade(Config("alembic.ini"), "head")
        yield


@pytest.fixture(scope="session")
def client(migrated_database):
    with TestClient(app) as test_client:
        yield test_client
