import os
import tempfile
import subprocess
import time
import socket
from pathlib import Path

import pytest
import requests


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def e2e_server():
    # Temporary data file for E2E, isolated
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "e2e_data.sqlite3"
        port = find_free_port()
        env = os.environ.copy()
        env["DB_FILE"] = str(db_path)
        cmd = [
            "python",
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Wait for server
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                r = requests.get(base + "/healthz", timeout=0.5)
                if r.ok:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        else:
            try:
                proc.kill()
            finally:
                pass
            raise RuntimeError("Server failed to start for E2E")

        yield base

        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()



@pytest.mark.playwright
async def test_e2e_add_and_delete_urls(page, e2e_server):
    base = e2e_server
    await page.goto(base + "/")

    # Open Add Folder modal and add folder
    await page.get_by_role("button", name="Add").click()
    await page.fill("#add-folder-name", "E2E Folder")
    await page.get_by_role("button", name="Add Folder").click()

    # Click the folder in left tree
    await page.get_by_text("E2E Folder").click()

    # Add two nodes in right form
    async def add_node(name):
        await page.fill("input[name=\"name\"]", name)
        await page.fill("input[name=\"url\"]", "https://example.com")
        await page.click("button:has-text('Add')")

    await add_node("A1")
    # after submit, the form resets; click folder again to ensure form visible
    await page.get_by_text("E2E Folder").click()
    await add_node("A2")

    # Select both checkboxes and delete selected
    await page.get_by_role("checkbox", name="Select all").check() if False else None  # fallback
    # Use table checkboxes
    boxes = await page.query_selector_all("input.node-checkbox")
    for b in boxes:
        await b.check()
    await page.get_by_role("button", name="Delete selected").click()

    # Confirm that table is empty or only actions remain
    # Reload tree via clicking folder link
    await page.get_by_text("E2E Folder").click()
    # Short wait and check that there is 'No URLs' text or table body empty
    content = await page.content()
    assert "No URLs in this folder yet" in content or "node-checkbox" not in content
