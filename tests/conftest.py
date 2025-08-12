import os
import tempfile
import json
import contextlib
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main as app_module


@pytest.fixture()
def temp_data_file(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        data_path = Path(tmpdir) / "test_data.json"
        # start with empty structure
        data = {"next_folder_id": 1, "next_node_id": 1, "folders": []}
        data_path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setenv("DATA_FILE", str(data_path))
        # Force module to pick up new path if already imported
        app_module.DATA_FILE = Path(str(data_path))
        yield data_path


@pytest.fixture()
def client(temp_data_file):
    # Fresh client per test using overridden DATA_FILE
    from main import app  # import after env set
    return TestClient(app)


class MockResp:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300


@pytest.fixture()
def mock_http_ok(monkeypatch):
    import httpx

    def sync_get(self, url, *args, **kwargs):
        return MockResp(200)

    async def async_get(self, url, *args, **kwargs):
        return MockResp(200)

    monkeypatch.setattr(httpx.Client, "get", sync_get, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "get", async_get, raising=True)
    return True


@pytest.fixture()
def mock_http_fail(monkeypatch):
    import httpx

    def sync_get(self, url, *args, **kwargs):
        return MockResp(404)

    async def async_get(self, url, *args, **kwargs):
        return MockResp(404)

    monkeypatch.setattr(httpx.Client, "get", sync_get, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "get", async_get, raising=True)
    return True
