# Endpoint Pulse

Note: This repository is a vibe coding experiment.

A small FastAPI + Bootstrap application to organize and monitor website URLs. You can group URLs in folders (categories), toggle whether a URL is active, and probe availability with HTTP status and response time. The left sidebar shows a collapsible tree of folders/URLs; the right pane shows context forms. Everything is server-rendered with Bootstrap forms.

## Purpose
This project provides a lightweight, self-hosted dashboard to:
- Keep URLs organized by category (folders)
- Quickly test the availability of a single URL or all URLs in a folder
- Track basic metadata (name, comment, active flag)
- Use a clean UI without writing any custom JavaScript

Typical use cases include health checking public endpoints, QA/staging links, and simple uptime spot checks.

## Tech Stack
- Python 3.12
- FastAPI (server + JSON API)
- Jinja2 templates (server-rendered UI)
- Bootstrap 5 (styling) + Bootstrap Icons
- httpx (HTTP client)
- Pydantic v2 (validation)

## Installation
1) Ensure Python 3.12 is installed.
2) Create and activate a virtual environment, then install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Installing the package from TestPyPI
When installing from TestPyPI, most third-party dependencies are not available on TestPyPI. Use the main PyPI as an extra index so pip can resolve dependencies like FastAPI and setuptools from PyPI while fetching this package from TestPyPI:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple \
            endpoint-pulse
```

Note: We constrain FastAPI to < 1.0 to avoid a known problematic fastapi==1.0 build on TestPyPI which requires setuptools from TestPyPI (not available). The extra-index-url ensures dependencies are pulled from the official PyPI.

## Running the App
Start the development server with auto-reload:
```bash
uvicorn main:app --reload
```
Or use the packaged console script (after installing the package):
```bash
endpoint-pulse --host 0.0.0.0 --port 8000 --reload
```
Environment variables are also supported when flags are omitted:
- ENDPOINT_PULSE_HOST (default: 127.0.0.1)
- ENDPOINT_PULSE_PORT (default: 8000)
- ENDPOINT_PULSE_RELOAD (set to 1/true/on to enable)

Open your browser at:
- http://127.0.0.1:8000/

## Testing
### Unit/Integration tests with coverage
```bash
pip install -r requirements.txt
make tests
```
This runs pytest (excluding Playwright/browser tests) with coverage and prints a term-missing coverage report for main.py. Tests run against a temporary, isolated database by overriding environment variables in fixtures, so your production data is not modified.

Alternatively, without make:
```bash
python -m pytest -m "not playwright" --cov=main --cov-report=term-missing
```

### End-to-end (Playwright) tests
Install browsers once:
```bash
python -m playwright install
```
Run E2E tests:
```bash
python -m pytest -m playwright tests_e2e
```
The E2E harness launches uvicorn on a random local port with an isolated data store.

## Data Persistence
Data and configuration are stored in a local SQLite database at `data.sqlite3` in the project root (override with `DB_FILE`). The schema has `folders`, `nodes`, and a small `meta` table for ID counters. On first run, if the database is empty and a legacy `data.json` exists, the app automatically imports it once to ease migration.

## Architecture Notes
- Startup initialization: The database schema is initialized once at app startup via FastAPI's lifespan. This avoids redundant schema checks per request and improves efficiency.
- Modularity: The current codebase is intentionally compact. Future work may extract database access and request handlers into separate modules (e.g., db.py, services.py, api_routes.py) and adopt an ORM like SQLAlchemy for more maintainable data access.

## UI Overview (Server-rendered)
- Left: collapsible tree of folders and their URLs.
- Right: context forms for adding/renaming/deleting folders, adding/editing/deleting/testing URLs.
- Test results show below the forms in a compact table.
- Preferences modal with a dark mode toggle (stored in a cookie).

## Data Export/Import
- Export: Click the “Export” button in the top navbar to download the current hierarchy JSON (folders, nodes, and next IDs).
- Import: Click the “Import” button in the navbar to open a modal. Upload a JSON exported file; this replaces the current configuration. Next IDs are recalculated automatically.

## JSON API Documentation
All JSON endpoints are unauthenticated and return JSON responses. Content type: `application/json`.

Schemas (request bodies):
- FolderIn
  - name: string (1..200)
- NodeIn
  - name: string (1..200)
  - url: HttpUrl (http/https)
  - comment: string (optional)
  - active: boolean (default true)

1) GET /api/tree
- Description: Retrieve the full folder/node tree.
- Response:
```json
{
  "folders": [
    {
      "id": 1,
      "name": "Production",
      "nodes": [
        {"id": 10, "folder_id": 1, "name": "Homepage", "url": "https://example.com", "comment": "", "active": true}
      ]
    }
  ]
}
```

2) POST /api/folders
- Description: Create a new folder.
- Body (JSON): FolderIn
```json
{"name": "Staging"}
```
- Response 200: the created folder object `{id, name, nodes: []}`
- Errors: 422 on validation failure

3) PUT /api/folders/{folder_id}
- Description: Rename an existing folder.
- Body (JSON): FolderIn
- Response 200: the updated folder object
- Errors: 404 if not found, 422 on validation failure

4) DELETE /api/folders/{folder_id}
- Description: Delete a folder and all its nodes.
- Response 200: `{ "ok": true }`
- Errors: 404 if not found

5) POST /api/folders/{folder_id}/nodes
- Description: Create a new node (URL) in a folder.
- Body (JSON): NodeIn
```json
{"name":"Homepage","url":"https://example.com","comment":"","active":true}
```
- Response 200: the created node `{id, folder_id, name, url, comment, active}`
- Errors: 404 if folder not found, 422 on validation failure

6) PUT /api/nodes/{node_id}
- Description: Update a node.
- Body (JSON): NodeIn
- Response 200: the updated node
- Errors: 404 if not found, 422 on validation failure

7) DELETE /api/nodes/{node_id}
- Description: Delete a node.
- Response 200: `{ "ok": true }`
- Errors: 404 if not found

8) POST /api/nodes/{node_id}/test
- Description: Probe a single URL (HTTP GET with redirects). 10s timeout.
- Response examples:
  - Active and successful:
```json
{"id": 10, "url": "https://example.com", "status_code": 200, "ok": true, "elapsed_ms": 123}
```
  - Active but failing HTTP:
```json
{"id": 10, "url": "https://example.com/404", "status_code": 404, "ok": false, "elapsed_ms": 95}
```
  - Network/other error:
```json
{"id": 10, "url": "https://bad.host/", "ok": false, "error": "...", "elapsed_ms": 10022}
```
  - Inactive node:
```json
{"id": 10, "active": false, "tested": false, "reason": "Node inactive"}
```
- Errors: 404 if node not found

9) POST /api/folders/{folder_id}/test
- Description: Probe all nodes in a folder (skips inactive nodes).
- Response 200:
```json
{
  "folder_id": 1,
  "results": [
    {"id": 10, "name": "Homepage", "url": "https://example.com", "active": true, "status_code": 200, "ok": true, "elapsed_ms": 123},
    {"id": 11, "name": "Docs", "url": "https://example.com/docs", "active": false, "tested": false, "reason": "Node inactive"}
  ]
}
```
- Errors: 404 if folder not found

10) GET /healthz
- Description: Simple health check.
- Response 200: `{ "status": "ok" }`

## Form-based HTML Endpoints (UI)
These endpoints power the server-rendered UI and redirect back to the main page. They are not intended as a public API but can be useful to know.
- POST /folders/add — add a folder (form field: name)
- POST /folders/{folder_id}/rename — rename a folder (form field: name)
- POST /folders/{folder_id}/delete — delete a folder
- POST /nodes/add — add a node (form fields: folder_id, name, url, comment, active)
- POST /nodes/{node_id}/edit — edit a node (form fields: name, url, comment, active)
- POST /nodes/{node_id}/delete — delete a node
- POST /nodes/{node_id}/toggle_active — toggle active flag
- POST /nodes/{node_id}/duplicate — duplicate a node (creates copy_N_<base> in same folder)
- POST /nodes/{node_id}/test/html — test a single node and render results below forms
- POST /folders/{folder_id}/test/html — test all nodes in the folder and render results below forms
- POST /folders/{folder_id}/duplicate — duplicate a folder and all its URLs
- GET /export — download the current hierarchy JSON
- POST /import — upload a JSON file (multipart/form-data) to replace current hierarchy

## Notes
- Authentication/authorization: none (intended for local/network use). Place behind a reverse proxy with auth if needed.
- Timeouts: Configurable via Preferences (default 10 seconds) per request when probing URLs.
- Redirects: HTTP redirects are followed during probes.
- Dark mode preference is stored in a cookie (`theme` = `light`/`dark`).


## Visualization
- After running tests, the page shows a compact response time chart (inline SVG) beneath the results table, including number of requests (measured/total) and average response time.


## Author

Andreas Jung <info@zopyx.com>
