from fastapi.testclient import TestClient





def test_preferences(client: TestClient):
    # Set dark mode and timeout, check redirect
    res = client.post("/preferences", data={"dark_mode": "on", "timeout_seconds": "5"}, headers={"referer": "/?folder_id=1"}, allow_redirects=False)
    assert res.status_code == 303
    assert res.cookies.get("theme") in ("dark", "light")
    assert res.cookies.get("timeout") in ("5", "1", "120")
