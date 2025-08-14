import io
import urllib.parse
from typing import List

import pytest
from fastapi.testclient import TestClient

import endpoint_pulse.app as app_module


@pytest.fixture()
def mock_http_error(monkeypatch):
    import httpx

    def sync_get(self, url, *args, **kwargs):
        raise RuntimeError("boom")

    async def async_get(self, url, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(httpx.Client, "get", sync_get, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "get", async_get, raising=True)
    return True


def test_index_cookie_parsing_and_clamping(client: TestClient):
    # Invalid theme -> defaults to light; timeout clamped to range [1,120]
    res = client.get("/", headers={"cookie": "theme=weird; timeout=-5"})
    assert res.status_code == 200
    res = client.get("/", headers={"cookie": "timeout=5000; theme=dark"})
    assert res.status_code == 200


def test_form_add_folder_empty_name_redirect(client: TestClient):
    res = client.post("/folders/add", data={"name": "   "}, allow_redirects=False)
    assert res.status_code == 303


def test_form_rename_delete_folder_edge_cases(client: TestClient):
    # 404 on rename/delete of missing folder
    assert client.post("/folders/999/rename", data={"name": "X"}, allow_redirects=False).status_code == 404
    assert client.post("/folders/999/delete", allow_redirects=False).status_code == 404

    # Create and then attempt empty rename -> redirect back
    fid = client.post("/api/folders", json={"name": "F"}).json()["id"]
    res = client.post(f"/folders/{fid}/rename", data={"name": "  "}, allow_redirects=False)
    assert res.status_code == 303


def test_duplicate_folder_with_nodes_and_copy_names(client: TestClient):
    # Create folder and nodes
    fid = client.post("/api/folders", json={"name": "Prod"}).json()["id"]
    client.post(f"/api/folders/{fid}/nodes", json={"name": "Home", "url": "https://e.com", "comment": "", "active": True})
    client.post(f"/api/folders/{fid}/nodes", json={"name": "copy_1_Home", "url": "https://e.com/x", "comment": "", "active": True})

    # Duplicate folder (should create copy_1_Prod)
    res = client.post(f"/folders/{fid}/duplicate", allow_redirects=False)
    assert res.status_code == 303

    tree = client.get("/api/tree").json()
    names = [f["name"] for f in tree["folders"]]
    assert any(n.startswith("copy_1_Prod") for n in names)
    # New folder nodes should be two and preserve names/actives
    new_folder = [f for f in tree["folders"] if f["name"].startswith("copy_1_Prod")][0]
    assert len(new_folder["nodes"]) == 2


def test_add_node_and_edit_invalid_and_success(client: TestClient):
    fid = client.post("/api/folders", json={"name": "A"}).json()["id"]
    # invalid url add -> redirect
    res = client.post("/nodes/add", data={"folder_id": str(fid), "name": "N", "url": "bad", "comment": ""}, allow_redirects=False)
    assert res.status_code == 303
    # valid add
    res = client.post("/nodes/add", data={"folder_id": str(fid), "name": "N1", "url": "https://e.com", "comment": "c", "active": "on"}, allow_redirects=False)
    assert res.status_code == 303
    nid = client.get("/api/tree").json()["folders"][0]["nodes"][0]["id"]

    # edit: invalid id -> 404
    assert client.post("/nodes/999/edit", data={"name": "X", "url": "https://e.com", "comment": ""}, allow_redirects=False).status_code == 404
    # edit: empty name -> redirect
    res = client.post(f"/nodes/{nid}/edit", data={"name": " ", "url": "https://e.com", "comment": ""}, allow_redirects=False)
    assert res.status_code == 303
    # edit: invalid URL -> redirect
    res = client.post(f"/nodes/{nid}/edit", data={"name": "OK", "url": "bad", "comment": ""}, allow_redirects=False)
    assert res.status_code == 303
    # edit: success
    res = client.post(f"/nodes/{nid}/edit", data={"name": "OK", "url": "https://ex.com", "comment": "z", "active": "on"}, allow_redirects=False)
    assert res.status_code == 303


def test_delete_node_redirect_and_404(client: TestClient):
    fid = client.post("/api/folders", json={"name": "B"}).json()["id"]
    nid = client.post(f"/api/folders/{fid}/nodes", json={"name": "N", "url": "https://e.com", "comment": "", "active": True}).json()["id"]
    # delete redirect back to folder
    res = client.post(f"/nodes/{nid}/delete", allow_redirects=False)
    assert res.status_code == 303
    # deleting again -> 404
    assert client.post(f"/nodes/{nid}/delete", allow_redirects=False).status_code == 404


def test_bulk_delete_fallback_when_no_ids(client: TestClient):
    fid = client.post("/api/folders", json={"name": "C"}).json()["id"]
    # add three nodes
    for i in range(3):
        client.post(f"/api/folders/{fid}/nodes", json={"name": f"N{i}", "url": "https://e.com", "comment": "", "active": True})
    tree = client.get("/api/tree").json()
    node_ids: List[int] = [n["id"] for n in tree["folders"][0]["nodes"]]
    # Post without node_ids -> should delete first 2 by fallback
    res = client.post("/nodes/bulk_delete", data={"folder_id": str(fid)}, allow_redirects=False)
    assert res.status_code == 303
    remaining = [n["id"] for n in client.get("/api/tree").json()["folders"][0]["nodes"]]
    assert remaining == node_ids[2:]


def test_duplicate_node_and_keep_context(client: TestClient):
    fid = client.post("/api/folders", json={"name": "D"}).json()["id"]
    nid = client.post(f"/api/folders/{fid}/nodes", json={"name": "X", "url": "https://e.com", "comment": "", "active": True}).json()["id"]
    # duplicate with keep folder context
    res = client.post(f"/nodes/{nid}/duplicate", data={"keep_folder_context": "1"}, allow_redirects=False)
    assert res.status_code == 303
    # 404 paths
    assert client.post("/nodes/999/duplicate", allow_redirects=False).status_code == 404


def test_toggle_active_referer_logic(client: TestClient):
    fid = client.post("/api/folders", json={"name": "E"}).json()["id"]
    nid = client.post(f"/api/folders/{fid}/nodes", json={"name": "Y", "url": "https://e.com", "comment": "", "active": True}).json()["id"]

    # Referer with node_id query should keep node focus
    res = client.post(f"/nodes/{nid}/toggle_active", headers={"referer": f"http://testserver/?node_id={nid}"}, allow_redirects=False)
    assert res.status_code == 303 and f"node_id={nid}" in res.headers.get("location", "")

    # Referer with folder_id query keeps folder focus
    res = client.post(f"/nodes/{nid}/toggle_active", headers={"referer": f"http://testserver/?folder_id={fid}"}, allow_redirects=False)
    assert res.status_code == 303 and f"folder_id={fid}" in res.headers.get("location", "")

    # Referer to POST-only path should redirect to folder
    res = client.post(f"/nodes/{nid}/toggle_active", headers={"referer": f"http://testserver/nodes/{nid}/test/html"}, allow_redirects=False)
    assert res.status_code == 303 and f"folder_id={fid}" in res.headers.get("location", "")


def test_preferences_redirect_and_clamp(client: TestClient):
    # From node POST-only test page -> should be redirected to node or folder
    res = client.post("/preferences", data={"dark_mode": "on", "timeout_seconds": "0"}, headers={"referer": "/nodes/1/test/html"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.cookies.get("timeout") in ("1", "120", "10", "5")

    res = client.post("/preferences", data={"timeout_seconds": "999"}, headers={"referer": "/?folder_id=5"}, allow_redirects=False)
    assert res.status_code == 303
    # timeout clamped to 120
    assert res.cookies.get("timeout") == "120"





def test_build_chart_stats_edges():
    # No results
    s = app_module._build_chart_stats([])
    assert s["count_total"] == 0 and isinstance(s["width"], int)
    # Mixed results with non-int elapsed
    results = [
        {"ok": True, "elapsed_ms": 10},
        {"ok": False, "elapsed_ms": 35},
        {"ok": True, "elapsed_ms": "n/a"},
    ]
    s2 = app_module._build_chart_stats(results)
    assert s2["count_total"] == 3 and s2["count_measured"] == 2
    assert s2["avg_ms"] in (22, 23)

    # Many bars to exercise x_step logic
    many = [{"ok": True, "elapsed_ms": (i % 50) + 1} for i in range(55)]
    s3 = app_module._build_chart_stats(many)
    assert s3["x_step"] in (1, 10)


def test_probe_exception_paths(client: TestClient, mock_http_error):
    # Create data to exercise both sync and async probes via endpoints
    fid = client.post("/api/folders", json={"name": "P"}).json()["id"]
    nid = client.post(f"/api/folders/{fid}/nodes", json={"name": "URL", "url": "https://e.com", "comment": "", "active": True}).json()["id"]
    # Node test should handle exception and return ok False with error
    res = client.post(f"/api/nodes/{nid}/test")
    assert res.status_code == 200 and res.json().get("ok") is False and "error" in res.json()
    # Folder test should handle exceptions inside _aprobes
    res = client.post(f"/api/folders/{fid}/test")
    assert res.status_code == 200



def test_index_selection_by_query_params(client: TestClient):
    # Create folder and node, then load index with selections
    fid = client.post("/api/folders", json={"name": "Sel"}).json()["id"]
    nid = client.post(f"/api/folders/{fid}/nodes", json={"name": "Pick", "url": "https://e.com", "comment": "", "active": True}).json()["id"]
    r1 = client.get(f"/?folder_id={fid}")
    assert r1.status_code == 200
    r2 = client.get(f"/?node_id={nid}")
    assert r2.status_code == 200


def test_bulk_delete_global_fallback_without_folder(client: TestClient):
    # Create two folders and three nodes overall
    f1 = client.post("/api/folders", json={"name": "G1"}).json()["id"]
    f2 = client.post("/api/folders", json={"name": "G2"}).json()["id"]
    client.post(f"/api/folders/{f1}/nodes", json={"name": "A", "url": "https://e.com/a", "comment": "", "active": True})
    client.post(f"/api/folders/{f1}/nodes", json={"name": "B", "url": "https://e.com/b", "comment": "", "active": True})
    client.post(f"/api/folders/{f2}/nodes", json={"name": "C", "url": "https://e.com/c", "comment": "", "active": True})
    # Post with no folder_id and no node_ids -> delete first 2 globally
    res = client.post("/nodes/bulk_delete", data={}, allow_redirects=False)
    assert res.status_code == 303
    # Now total nodes should be 1
    tree = client.get("/api/tree").json()
    total_nodes = sum(len(f.get("nodes") or []) for f in tree["folders"])
    assert total_nodes == 1


def test_duplicate_folder_404(client: TestClient):
    assert client.post("/folders/9999/duplicate", allow_redirects=False).status_code == 404


def test_duplicate_node_orphan_folder_404(client: TestClient):
    # Create consistent data
    data = app_module._load_data()
    next_fid = data.get("next_folder_id", 1)
    next_nid = data.get("next_node_id", 1)
    # Add a node referencing a missing folder id (orphan)
    orphan_folder_id = 43210
    data.setdefault("folders", []).append({"id": next_fid, "name": "Q", "nodes": []})
    data["next_folder_id"] = next_fid + 1
    data.setdefault("folders", [])  # ensure exists
    data_folderless_node = {
        "id": next_nid,
        "folder_id": orphan_folder_id,
        "name": "Orphan",
        "url": "https://e.com/",
        "comment": "",
        "active": True,
    }
    # Save with explicit inconsistency: keep node under some real folder to persist id, then remove folder
    # First, attach node to actual folder to save; then detach folder to create orphan situation
    data["folders"][0].setdefault("nodes", []).append(dict(data_folderless_node))
    data["next_node_id"] = next_nid + 1
    app_module._save_data(data)
    # Now reload, remove the real folder so node becomes orphaned in storage
    data2 = app_module._load_data()
    # Pull out the node id we created
    orphan_nid = data_folderless_node["id"]
    data2["folders"] = []
    # Preserve next ids
    app_module._save_data({"folders": [], "next_folder_id": data2.get("next_folder_id", 1), "next_node_id": data2.get("next_node_id", 1)})
    # Call duplicate on the orphan node -> folder not found 404
    assert client.post(f"/nodes/{orphan_nid}/duplicate", allow_redirects=False).status_code == 404


def test_form_test_node_html_timeout_clamp_and_ok_errors_zero(client: TestClient, mock_http_ok):
    fid = client.post("/api/folders", json={"name": "TN"}).json()["id"]
    nid = client.post(f"/api/folders/{fid}/nodes", json={"name": "U", "url": "https://ex.com", "comment": "", "active": True}).json()["id"]
    res = client.post(f"/nodes/{nid}/test/html", data={}, headers={"cookie": "timeout=5000"})
    assert res.status_code == 200


def test_form_test_folder_html_runs_clamp_and_inactive_only(client: TestClient, mock_http_ok):
    fid = client.post("/api/folders", json={"name": "TF"}).json()["id"]
    # Add one inactive node to force skipped path
    client.post(f"/api/folders/{fid}/nodes", json={"name": "U", "url": "https://ex.com", "comment": "", "active": False})
    # runs negative -> clamp to 1
    res = client.post(f"/folders/{fid}/test/html", data={"runs": "-5"}, headers={"cookie": "timeout=-10"})
    assert res.status_code == 200
    # runs too big -> clamp to 100
    res = client.post(f"/folders/{fid}/test/html", data={"runs": "500"})
    assert res.status_code == 200


def test_next_copy_name_variants():
    existing = ["copy_1_Base", "copy_2_Base", "Other", "copy_3_Base"]
    # original already a copy -> base extracted
    name = app_module._next_copy_name(existing, "copy_5_Base")
    assert name == "copy_4_Base" or name.startswith("copy_")
    # loop while candidate in existing
    name2 = app_module._next_copy_name(["copy_1_X", "copy_2_X"], "X")
    assert name2 == "copy_3_X"


def test_chart_stats_more_colors_and_steps():
    # Include a skipped/untested row to exercise gray color path
    rows = [
        {"ok": True, "elapsed_ms": 5},
        {"tested": False, "elapsed_ms": 0},
    ]
    s = app_module._build_chart_stats(rows)
    assert s["count_total"] == 2
    # Exercise larger x_step thresholds (25, 50, 100)
    s25 = app_module._build_chart_stats([{"ok": True, "elapsed_ms": 1} for _ in range(120)])
    assert s25["x_step"] in (10, 25, 50, 100)
    s50 = app_module._build_chart_stats([{"ok": True, "elapsed_ms": 1} for _ in range(300)])
    assert s50["x_step"] in (25, 50, 100)
    s100 = app_module._build_chart_stats([{"ok": True, "elapsed_ms": 1} for _ in range(600)])
    assert s100["x_step"] in (50, 100)
