from io import BytesIO
from fastapi.testclient import TestClient
import json


def test_export_import_and_html_tests(client: TestClient):
    # create folder and nodes
    fid = client.post("/api/folders", json={"name": "Imp"}).json()["id"]
    client.post(f"/api/folders/{fid}/nodes", json={"name": "N1", "url": "https://example.com", "comment": "", "active": True})

    # export
    res = client.get("/export")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    exported = res.content

    # import same content (multipart)
    files = {"file": ("data.json", exported, "application/json")}
    res = client.post("/import", files=files, allow_redirects=False)
    assert res.status_code == 303

    # html test endpoints should render
    # need a node id
    tree = client.get("/api/tree").json()
    nid = tree["folders"][0]["nodes"][0]["id"]
    res = client.post(f"/nodes/{nid}/test/html", data={"keep_folder_context": "1"})
    assert res.status_code == 200
    res = client.post(f"/folders/{fid}/test/html")
    assert res.status_code == 200


def test_preferences(client: TestClient):
    # Set dark mode and timeout, check redirect
    res = client.post("/preferences", data={"dark_mode": "on", "timeout_seconds": "5"}, headers={"referer": "/?folder_id=1"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.cookies.get("theme") in ("dark", "light")
    assert res.cookies.get("timeout") in ("5", "1", "120")
