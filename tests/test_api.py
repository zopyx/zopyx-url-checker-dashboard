
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from endpoint_pulse.app import _get_ssl_cert_info, _probe_url

def test_healthz(client: TestClient):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_tree_initial_empty(client: TestClient):
    res = client.get("/api/tree")
    assert res.status_code == 200
    data = res.json()
    assert data == {"folders": []}


def test_create_rename_delete_folder(client: TestClient):
    # create
    res = client.post("/api/folders", json={"name": "Prod"})
    assert res.status_code == 200
    folder = res.json()
    assert folder["name"] == "Prod"
    fid = folder["id"]

    # rename
    res = client.put(f"/api/folders/{fid}", json={"name": "Production"})
    assert res.status_code == 200
    assert res.json()["name"] == "Production"

    # delete
    res = client.delete(f"/api/folders/{fid}")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_folder_nodes_crud_and_tests(client: TestClient, mock_http_ok):
    # Create folder
    fid = client.post("/api/folders", json={"name": "Staging"}).json()["id"]

    # Add node
    node_in = {"name": "Homepage", "url": "https://example.com", "comment": "", "active": True}
    res = client.post(f"/api/folders/{fid}/nodes", json=node_in)
    assert res.status_code == 200
    node = res.json()
    nid = node["id"]
    assert node["folder_id"] == fid

    # Update node
    res = client.put(f"/api/nodes/{nid}", json={**node_in, "name": "Home"})
    assert res.status_code == 200
    assert res.json()["name"] == "Home"

    # Test node (mocked ok)
    res = client.post(f"/api/nodes/{nid}/test")
    assert res.status_code == 200
    j = res.json()
    assert j["ok"] is True and j["status_code"] == 200 and j["id"] == nid

    # Add inactive node and folder test
    node2 = client.post(f"/api/folders/{fid}/nodes", json={**node_in, "name": "Docs", "active": False}).json()
    res = client.post(f"/api/folders/{fid}/test")
    assert res.status_code == 200
    j = res.json()
    assert j["folder_id"] == fid
    assert len(j["results"]) == 2
    # one inactive
    assert any(r.get("tested") is False for r in j["results"])  # skipped one

    # Delete node
    res = client.delete(f"/api/nodes/{nid}")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_not_found_errors(client: TestClient):
    assert client.put("/api/folders/999", json={"name": "X"}).status_code == 404
    assert client.delete("/api/folders/999").status_code == 404
    assert client.post("/api/folders/999/nodes", json={"name": "N", "url": "https://e.com", "comment": "", "active": True}).status_code == 404
    assert client.put("/api/nodes/999", json={"name": "N", "url": "https://e.com", "comment": "", "active": True}).status_code == 404
    assert client.delete("/api/nodes/999").status_code == 404
    assert client.post("/api/nodes/999/test").status_code == 404
    assert client.post("/api/folders/999/test").status_code == 404

@patch('ssl.create_default_context')
@patch('socket.create_connection')
def test_get_ssl_cert_info(mock_create_connection, mock_create_default_context):
    # Test with non-https url
    info = _get_ssl_cert_info("http://example.com")
    assert info == {}

    # Test with https url
    mock_socket = MagicMock()
    mock_ssock = MagicMock()
    mock_ssock.getpeercert.return_value = {
        'notAfter': 'Aug 14 12:00:00 2026 GMT'
    }
    mock_context = MagicMock()
    mock_context.wrap_socket.return_value.__enter__.return_value = mock_ssock
    mock_create_default_context.return_value = mock_context
    mock_create_connection.return_value.__enter__.return_value = mock_socket

    info = _get_ssl_cert_info("https://example.com")
    assert info["ssl_valid"] is True
    assert info["ssl_days_left"] > 0

@patch('httpx.Client')
def test_probe_url(mock_httpx_client):
    # Test with successful response
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_httpx_client.return_value.__enter__.return_value.get.return_value = mock_response

    result = _probe_url("https://example.com")
    assert result["ok"] is True
    assert result["status_code"] == 200

    # Test with failed response
    mock_response.is_success = False
    mock_response.status_code = 500
    result = _probe_url("https://example.com")
    assert result["ok"] is False
    assert result["status_code"] == 500

    # Test with exception
    mock_httpx_client.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
    result = _probe_url("https://example.com")
    assert result["ok"] is False
    assert result["error"] == "timeout"
