import os
import tempfile
import contextlib
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main as app_module



@pytest.fixture()
def client(monkeypatch):
    # Fresh client per test using a temporary database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        monkeypatch.setenv("DB_FILE", str(db_path))
        from main import app  # import after env set
        yield WrappedTestClient(app)



class WrappedTestClient(TestClient):
    def _normalized_request(self, method, url, **kwargs):
        # Map deprecated allow_redirects to follow_redirects to silence Starlette deprecation warnings
        if "allow_redirects" in kwargs and "follow_redirects" not in kwargs:
            kwargs["follow_redirects"] = bool(kwargs.pop("allow_redirects"))

        # If raw body provided via data (bytes/str) or classic form structures, move to content
        # to avoid httpx deprecation warning about using 'data=' for raw bytes.
        if "content" not in kwargs:
            data = kwargs.get("data", None)
            files = kwargs.get("files", None)
            json_arg = kwargs.get("json", None)
            # Only transform when not uploading files and not JSON
            if json_arg is None and not files and data is not None:
                import urllib.parse
                headers = dict(kwargs.get("headers") or {})
                body_bytes = None
                if isinstance(data, (bytes, bytearray)):
                    body_bytes = bytes(data)
                elif isinstance(data, str):
                    body_bytes = data.encode("utf-8")
                elif isinstance(data, (dict, list, tuple)):
                    try:
                        # url-encode; support list of tuples with doseq
                        body_str = urllib.parse.urlencode(data, doseq=True)
                        body_bytes = body_str.encode("utf-8")
                        # set form content-type if not already set
                        if not any(k.lower() == "content-type" for k in headers.keys()):
                            headers["Content-Type"] = "application/x-www-form-urlencoded"
                    except Exception:
                        body_bytes = None
                if body_bytes is not None:
                    kwargs.pop("data", None)
                    kwargs["content"] = body_bytes
                    if headers:
                        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)

    # Override verb helpers to avoid passing deprecated args into parent helpers
    def get(self, url, **kwargs):
        return self._normalized_request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._normalized_request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._normalized_request("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._normalized_request("DELETE", url, **kwargs)

    def request(self, method, url, *args, **kwargs):
        # Ensure direct calls still go through normalization
        return self._normalized_request(method, url, **kwargs)





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
