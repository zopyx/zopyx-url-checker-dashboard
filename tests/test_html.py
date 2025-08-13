from fastapi.testclient import TestClient


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
