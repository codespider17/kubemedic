import os
from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE = Path(f"/tmp/kubemedic-pytest-{os.getpid()}.db")
TEST_DATABASE.unlink(missing_ok=True)
os.environ["KUBEMEDIC_DB_PATH"] = str(TEST_DATABASE)

app = import_module("app.main").app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client
    TEST_DATABASE.unlink(missing_ok=True)
