import pytest

from oip import config


@pytest.fixture(scope="session", autouse=True)
def warehouse():
    if not config.DB_PATH.exists():
        pytest.skip("Warehouse not built. Run: python -m oip build", allow_module_level=False)
    return config.DB_PATH


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from oip.api.app import app
    return TestClient(app)
