
from fastapi.testclient import TestClient
from endpoint_pulse.app import _next_copy_name, _build_chart_stats, _resolve_db_file
import os
from pathlib import Path
from unittest.mock import patch

def test_index(client: TestClient):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Endpoint Pulse" in res.content


def test_form_folder_and_nodes_and_bulk_delete(client: TestClient):
    # Add folder via form
    res = client.post("/folders/add", data={"name": "Prod"}, allow_redirects=False)
    assert res.status_code == 303
    # Extract folder id by reading API tree
    fid = client.get("/api/tree").json()["folders"][0]["id"]

    # Rename via form
    res = client.post(f"/folders/{fid}/rename", data={"name": "Production"}, allow_redirects=False)
    assert res.status_code == 303

    # Add nodes via form
    for i in range(3):
        res = client.post("/nodes/add", data={
            "folder_id": str(fid),
            "name": f"N{i}",
            "url": "https://example.com",
            "comment": "",
            "active": "on",
        }, allow_redirects=False)
        assert res.status_code == 303

    # Toggle first node to inactive
    nid0 = client.get("/api/tree").json()["folders"][0]["nodes"][0]["id"]
    res = client.post(f"/nodes/{nid0}/toggle_active", allow_redirects=False)
    assert res.status_code == 303

    # Duplicate second node
    nid1 = client.get("/api/tree").json()["folders"][0]["nodes"][1]["id"]
    res = client.post(f"/nodes/{nid1}/duplicate", allow_redirects=False)
    assert res.status_code == 303

    # Bulk delete: select two node ids
    tree = client.get("/api/tree").json()
    ids = [n["id"] for n in tree["folders"][0]["nodes"]][:2]
    res = client.post("/nodes/bulk_delete", data=[
        ("node_ids", str(ids[0])),
        ("node_ids", str(ids[1])),
        ("folder_id", str(fid)),
    ], allow_redirects=False)
    assert res.status_code == 303

    # Ensure deletions applied
    remaining = client.get("/api/tree").json()["folders"][0]["nodes"]
    remaining_ids = [n["id"] for n in remaining]
    for rid in ids:
        assert rid not in remaining_ids

    # Delete all in folder
    res = client.post("/nodes/bulk_delete", data={
        "folder_id": str(fid),
        "delete_all_in_folder": "1",
    }, allow_redirects=False)
    assert res.status_code == 303
    assert client.get("/api/tree").json()["folders"][0]["nodes"] == []

    # Delete folder
    res = client.post(f"/folders/{fid}/delete", allow_redirects=False)
    assert res.status_code == 303
    assert client.get("/api/tree").json() == {"folders": []}


def test_form_preferences(client: TestClient):
    res = client.post("/preferences", data={"dark_mode": "on", "timeout_seconds": "20"}, allow_redirects=False)
    assert res.status_code == 303
    assert "theme=dark" in res.headers["set-cookie"]
    assert "timeout=20" in res.headers["set-cookie"]


def test_form_tests(client: TestClient, mock_http_ok):
    # Add folder and node
    fid = client.post("/api/folders", json={"name": "Test"}).json()["id"]
    nid = client.post(f"/api/folders/{fid}/nodes", json={"name": "N", "url": "https://e.com"}).json()["id"]

    # Test node via form
    res = client.post(f"/nodes/{nid}/test/html", allow_redirects=False)
    assert res.status_code == 200
    assert b"Test Results" in res.content

    # Test folder via form
    res = client.post(f"/folders/{fid}/test/html", data={"runs": "3"}, allow_redirects=False)
    assert res.status_code == 200
    assert b"Test Results" in res.content

    # Test selected in folder
    res = client.post(f"/folders/{fid}/test_selected/html", data={"node_ids": str(nid)}, allow_redirects=False)
    assert res.status_code == 200
    assert b"Test Results" in res.content

def test_form_folder_errors(client: TestClient):
    # Add folder with empty name
    res = client.post("/folders/add", data={"name": " "}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/"

    # Add a folder to test rename and delete errors
    res = client.post("/folders/add", data={"name": "test"}, allow_redirects=False)
    fid = client.get("/api/tree").json()["folders"][0]["id"]

    # Rename folder with empty name
    res = client.post(f"/folders/{fid}/rename", data={"name": " "}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/?folder_id={fid}"

    # Rename non-existent folder
    res = client.post("/folders/999/rename", data={"name": "new"}, allow_redirects=False)
    assert res.status_code == 404

    # Delete non-existent folder
    res = client.post("/folders/999/delete", allow_redirects=False)
    assert res.status_code == 404

def test_form_node_errors(client: TestClient):
    # Add a folder to test node errors
    res = client.post("/folders/add", data={"name": "test"}, allow_redirects=False)
    fid = client.get("/api/tree").json()["folders"][0]["id"]

    # Add node with empty name
    res = client.post("/nodes/add", data={"folder_id": fid, "name": " ", "url": "https://example.com"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/?folder_id={fid}"

    # Add node with invalid url
    res = client.post("/nodes/add", data={"folder_id": fid, "name": "test", "url": "invalid"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/?folder_id={fid}"

    # Add node to non-existent folder
    res = client.post("/nodes/add", data={"folder_id": 999, "name": "test", "url": "https://example.com"}, allow_redirects=False)
    assert res.status_code == 404

    # Add a node to test edit and delete errors
    res = client.post("/nodes/add", data={"folder_id": fid, "name": "test", "url": "https://example.com"}, allow_redirects=False)
    nid = client.get("/api/tree").json()["folders"][0]["nodes"][0]["id"]

    # Edit node with empty name
    res = client.post(f"/nodes/{nid}/edit", data={"name": " ", "url": "https://example.com"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/?node_id={nid}"

    # Edit node with invalid url
    res = client.post(f"/nodes/{nid}/edit", data={"name": "test", "url": "invalid"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/?node_id={nid}"

    # Edit non-existent node
    res = client.post("/nodes/999/edit", data={"name": "test", "url": "https://example.com"}, allow_redirects=False)
    assert res.status_code == 404

    # Delete non-existent node
    res = client.post("/nodes/999/delete", allow_redirects=False)
    assert res.status_code == 404

def test_form_bulk_delete_no_ids(client: TestClient):
    # Add a folder and some nodes
    res = client.post("/folders/add", data={"name": "test"}, allow_redirects=False)
    fid = client.get("/api/tree").json()["folders"][0]["id"]
    for i in range(3):
        client.post("/nodes/add", data={"folder_id": fid, "name": f"N{i}", "url": "https://example.com"}, allow_redirects=False)

    # Bulk delete with no node_ids (folder-scoped fallback)
    res = client.post("/nodes/bulk_delete", data={"folder_id": fid}, allow_redirects=False)
    assert res.status_code == 303
    assert len(client.get("/api/tree").json()["folders"][0]["nodes"]) == 1

    # Bulk delete with no node_ids (global fallback)
    res = client.post("/nodes/bulk_delete", data={}, allow_redirects=False)
    assert res.status_code == 303
    assert len(client.get("/api/tree").json()["folders"][0]["nodes"]) == 0

def test_form_duplicate_folder(client: TestClient):
    # Add a folder and a node
    res = client.post("/folders/add", data={"name": "test"}, allow_redirects=False)
    fid = client.get("/api/tree").json()["folders"][0]["id"]
    client.post("/nodes/add", data={"folder_id": fid, "name": "N1", "url": "https://example.com"}, allow_redirects=False)

    # Duplicate the folder
    res = client.post(f"/folders/{fid}/duplicate", allow_redirects=False)
    assert res.status_code == 303

    # Check that the folder and node were duplicated
    tree = client.get("/api/tree").json()
    assert len(tree["folders"]) == 2
    assert tree["folders"][1]["name"] == "copy_1_test"
    assert len(tree["folders"][1]["nodes"]) == 1
    assert tree["folders"][1]["nodes"][0]["name"] == "N1"

    # Duplicate non-existent folder
    res = client.post("/folders/999/duplicate", allow_redirects=False)
    assert res.status_code == 404

def test_form_toggle_node_active(client: TestClient):
    # Add a folder and a node
    res = client.post("/folders/add", data={"name": "test"}, allow_redirects=False)
    fid = client.get("/api/tree").json()["folders"][0]["id"]
    res = client.post("/nodes/add", data={"folder_id": fid, "name": "N1", "url": "https://example.com"}, allow_redirects=False)
    nid = client.get("/api/tree").json()["folders"][0]["nodes"][0]["id"]

    # Toggle active with no referer
    res = client.post(f"/nodes/{nid}/toggle_active", allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/?folder_id={fid}"

    # Toggle active with referer to folder
    res = client.post(f"/nodes/{nid}/toggle_active", headers={"referer": f"/?folder_id={fid}"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/?folder_id={fid}"

    # Toggle active with referer to node
    res = client.post(f"/nodes/{nid}/toggle_active", headers={"referer": f"/?node_id={nid}"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/?node_id={nid}"

def test_set_preferences_referer(client: TestClient):
    # Set preferences with no referer
    res = client.post("/preferences", data={"dark_mode": "on"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/"

    # Set preferences with referer to folder
    res = client.post("/preferences", data={"dark_mode": "on"}, headers={"referer": "/?folder_id=1"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/?folder_id=1"

    # Set preferences with referer to node
    res = client.post("/preferences", data={"dark_mode": "on"}, headers={"referer": "/?node_id=1"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/?node_id=1"

    # Set preferences with referer to test/html
    res = client.post("/preferences", data={"dark_mode": "on"}, headers={"referer": "/folders/1/test/html"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/?folder_id=1"

def test_form_test_selected_no_nodes(client: TestClient):
    # Add a folder
    res = client.post("/folders/add", data={"name": "test"}, allow_redirects=False)
    fid = client.get("/api/tree").json()["folders"][0]["id"]

    # Test selected with no nodes selected
    res = client.post(f"/folders/{fid}/test_selected/html", data={}, allow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/?folder_id={fid}"

def test_form_duplicate_node_error(client: TestClient):
    # Duplicate non-existent node
    res = client.post("/nodes/999/duplicate", allow_redirects=False)
    assert res.status_code == 404

    # Add a folder and a node, then delete the folder
    res = client.post("/folders/add", data={"name": "test"}, allow_redirects=False)
    fid = client.get("/api/tree").json()["folders"][0]["id"]
    res = client.post("/nodes/add", data={"folder_id": fid, "name": "N1", "url": "https://example.com"}, allow_redirects=False)
    nid = client.get("/api/tree").json()["folders"][0]["nodes"][0]["id"]
    client.post(f"/folders/{fid}/delete", allow_redirects=False)

    # Duplicate node whose folder is gone
    res = client.post(f"/nodes/{nid}/duplicate", allow_redirects=False)
    assert res.status_code == 404

def test_next_copy_name():
    assert _next_copy_name([], "base") == "copy_1_base"
    assert _next_copy_name(["copy_1_base"], "base") == "copy_2_base"
    assert _next_copy_name(["copy_2_base"], "base") == "copy_3_base"
    assert _next_copy_name(["copy_1_base", "copy_3_base"], "base") == "copy_4_base"
    assert _next_copy_name(["copy_1_base", "copy_2_base"], "base") == "copy_3_base"
    assert _next_copy_name(["copy_1_base"], "copy_1_base") == "copy_2_base"
    assert _next_copy_name(["copy_2_base"], "copy_1_base") == "copy_3_base"
    assert _next_copy_name(["copy_1_base", "copy_3_base"], "copy_1_base") == "copy_4_base"

def test_build_chart_stats():
    # Test with no results
    stats = _build_chart_stats([])
    assert stats["count_total"] == 0
    assert stats["count_measured"] == 0
    assert stats["avg_ms"] is None

    # Test with some results
    results = [
        {"elapsed_ms": 100, "ok": True, "name": "N1"},
        {"elapsed_ms": 200, "ok": False, "name": "N2"},
        {"elapsed_ms": 300, "ok": True, "name": "N3"},
        {"tested": False, "name": "N4"},
    ]
    stats = _build_chart_stats(results)
    assert stats["count_total"] == 4
    assert stats["count_measured"] == 3
    assert stats["avg_ms"] == 200
    assert stats["max_ms"] == 300
    assert len(stats["series"]) == 4
    assert len(stats["y_ticks"]) > 0

@patch.dict(os.environ, {"DB_FILE": "/tmp/test.db"})
def test_resolve_db_file_db_file():
    assert _resolve_db_file() == Path("/tmp/test.db")

@patch.dict(os.environ, {"DATA_FILE": "/tmp/test.data"})
def test_resolve_db_file_data_file():
    assert _resolve_db_file() == Path("/tmp/test.data").with_suffix(".sqlite3")
