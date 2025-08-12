# Project Specifications: URL Availability Dashboard

This document defines the complete functionality, architecture, backend and frontend behavior, data model, and testing strategy of the URL Availability Dashboard so that another engineer (or AI) can fully regenerate the project.


## 1. Purpose and Scope
A lightweight, self-hosted dashboard to:
- Organize URLs into folders (categories)
- Probe availability (HTTP status + response time)
- Toggle URLs active/inactive
- Perform single or bulk tests
- Import/export configuration as JSON
- Manage everything through a server-rendered Bootstrap UI

Non-goals:
- No persistent DB (file-based JSON storage only)
- No authentication/authorization (intended for local/network use)
- No background schedulers or uptime alerts


## 2. Technology Stack
- Language: Python 3.12
- Framework: FastAPI (backend + JSON API)
- Templates: Jinja2 (server-rendered HTML)
- UI: Bootstrap 5 + Bootstrap Icons
- HTTP client: httpx
- Validation: Pydantic v2
- Web server: uvicorn (dev/test)
- Tests: pytest, pytest-asyncio, pytest-playwright, Playwright (browsers)


## 3. Project Layout (expected)
- main.py — FastAPI app and all endpoints
- templates/index.html — primary UI template
- static/css/style.css — custom styles (optional/minimal)
- static/js/app.js — optional client helpers (not required for core UI)
- data.json — JSON storage (runtime); overridden by DATA_FILE env var for tests
- requirements.txt — pinned dependencies
- pytest.ini — config and markers (playwright)
- tests/ — pytest suite (API + HTML + misc)
- tests_e2e/ — Playwright tests (browser-based)


## 4. Data Model and Persistence
Single JSON file at project root by default: data.json. Path can be overridden using env var DATA_FILE (used by tests).

Structure:
```
{
  "next_folder_id": 1,
  "next_node_id": 1,
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

- next_folder_id and next_node_id are monotonic counters used to assign new IDs.
- Each node stores folder_id redundantly for convenience.
- File I/O: write is performed using a tmp file + os.replace to avoid corruption.
- On missing or unreadable file: default structure is returned (empty state).


## 5. Backend: API Endpoints (JSON)
All return JSON; content-type application/json.

Models:
- FolderIn: { name: str, 1..200 }
- Folder: { id: int, name: str, nodes: List[Node] }
- NodeIn: { name: str (1..200), url: HttpUrl, comment: str opt, active: bool default true }
- Node: NodeIn + { id: int, folder_id: int }

Endpoints:
1) GET /api/tree
- Returns: { folders: [...] } (entire hierarchy)

2) POST /api/folders
- Body: FolderIn (JSON)
- Creates and returns new folder object {id, name, nodes: []}
- 422 on validation error

3) PUT /api/folders/{folder_id}
- Body: FolderIn (JSON)
- Renames folder; 404 if not found

4) DELETE /api/folders/{folder_id}
- Deletes folder and all nodes; 404 if not found
- Returns {"ok": true}

5) POST /api/folders/{folder_id}/nodes
- Body: NodeIn (JSON)
- Creates new node in folder; 404 if folder not found

6) PUT /api/nodes/{node_id}
- Body: NodeIn (JSON)
- Updates node; 404 if not found

7) DELETE /api/nodes/{node_id}
- Deletes node; 404 if not found
- Returns {"ok": true}

8) POST /api/nodes/{node_id}/test
- Probes a single URL with httpx (follow redirects, timeout default 10s)
- Response on active node: { id, url, ok, status_code?, elapsed_ms, error? }
- If node inactive: { id, active: false, tested: false, reason: "Node inactive" }
- 404 if node not found

9) POST /api/folders/{folder_id}/test
- Probes all active nodes concurrently (httpx.AsyncClient)
- Returns: { folder_id, results: [ per-node rows including ok/status_code/elapsed_ms or inactive reason ] }
- 404 if folder not found

10) GET /healthz
- Returns { "status": "ok" }

Notes for probing:
- Synchronous single URL probe uses httpx.Client with follow_redirects=True
- Parallel folder probe uses httpx.AsyncClient with gather
- Timeout derived from preferences for HTML flows; default 10 seconds in JSON API


## 6. Backend: HTML Form Endpoints (server-rendered UI)
These endpoints accept form data and redirect back to the main GET page (or render index with results for test/html). They are not meant as public API.

- POST /folders/add — add a folder; field: name; redirects to /?folder_id={id}
- POST /folders/{folder_id}/rename — field: name; 404 if not found; redirects back to selected folder
- POST /folders/{folder_id}/delete — deletes folder; redirects to root "/"
- POST /nodes/add — fields: folder_id, name, url, comment, active(on|None); redirects to /?node_id={id}
- POST /nodes/{node_id}/edit — fields: name, url, comment, active; 404 if not found; redirects to /?node_id={id}
- POST /nodes/{node_id}/delete — deletes node; redirects to parent folder
- POST /nodes/{node_id}/toggle_active — toggles boolean; redirects safely to a GET page (tries to preserve current selection, avoids POST-only URLs)
- POST /nodes/{node_id}/duplicate — creates a copy named copy_N_<base>; redirects to new node
- POST /nodes/{node_id}/test/html — probes the node and renders results below forms; default keeps node selected unless keep_folder_context=1 provided
- POST /folders/{folder_id}/test/html — probes all nodes and renders results in the same page, with summary chart
- GET /export — downloads JSON of full hierarchy (including next ids)
- POST /import — multipart upload of exported JSON; replaces current hierarchy; recalculates next ids; redirects to first folder (if any) or root
- POST /nodes/bulk_delete — deletes selected nodes or all nodes in a folder:
  - Fields: folder_id; optional node_ids (multiple values) OR delete_all_in_folder=1
  - For selected delete, the backend reads all sent node_ids (using getlist) and removes them from all folders; redirects back to the current folder (or root)
  - If delete_all_in_folder provided, wipes nodes list of the given folder; redirects back to that folder
  - Empty selection is safe; simply redirects


## 7. Frontend (Server-rendered UI)
Single main template: templates/index.html. Layout:
- Navbar with Export, Import, Preferences, About
- Left column: folder tree (collapsible details/summary per folder) with badges showing node counts and buttons per folder/node for quick actions (test, toggle active)
- Right column: contextual forms
  - No selection: add folder form
  - Folder selected: rename/delete folder; add node form; nodes table with bulk operations
  - Node selected: edit node form with actions (test, duplicate, delete)
- Test results panel shows a table and an inline SVG chart (response times) when running tests via HTML forms
- Preferences modal allows toggling dark mode and timeout (1–120 seconds), stored in cookies

Nodes table behaviors:
- Each row has a checkbox with name="node_ids"; a hidden form field folder_id is provided by a standalone form (id="bulkDeleteForm").
- A top right "Delete selected" button submits bulkDeleteForm.
- A select-all checkbox controls all row checkboxes and displays an indeterminate state when partially selected.
- Minimal inline JavaScript manages select-all and enables/disables the delete button based on selection. With JS disabled, the button remains functional and server safely handles empty selections.
- A "Delete all" button opens a confirmation modal that posts delete_all_in_folder=1.

Accessibility & UX:
- Buttons include titles/aria labels
- Links to URLs open in new tab with rel="noopener"
- Indeterminate checkbox state for select-all
- Bootstrap classes for visual consistency


## 8. Preferences and Cookies
- theme cookie: "light" or "dark" (default: light) used to render data-bs-theme
- timeout cookie: integer seconds (1..120; default 10) used by HTML testing endpoints to set probe timeout
- Preferences form (/preferences) sets both cookies and safely redirects to a GET page


## 9. Import/Export
- GET /export: returns JSON content of the current hierarchy as an attachment (filename includes UNIX timestamp)
- POST /import: accepts multipart file "file" with JSON structure; normalizes data, ensures each node has its folder_id, recalculates next ids as max+1; replaces existing data atomically and redirects


## 10. URL Probing and Results Visualization
- Synchronous single-node test: httpx.Client; returns ok + status or error with elapsed_ms
- Parallel folder test: httpx.AsyncClient; results for active nodes are mapped back to the original order; inactive nodes are included with tested=false and reason
- Inline SVG chart shows per-row bars with color coding: green (OK), red (error/fail), gray (skipped/inactive). Also shows counts and average response time.


## 11. Error Handling
- 404 for missing folders/nodes
- 422 for validation errors in JSON API
- Form endpoints generally redirect back to a safe GET page upon invalid input or missing data (fail-safe UX)
- Import endpoint validates and normalizes incoming JSON


## 12. Security Notes
- No authentication/authorization; intended for trusted local/network environments
- If exposing externally, place behind a reverse proxy with authentication
- Import replaces configuration completely; treat uploaded file as trusted in local environment


## 13. Testing Strategy
- Unit/Integration tests (pytest): cover API CRUD, probing workflows (mocked httpx), HTML endpoints behaviors, preferences, export/import, and bulk delete.
- Playwright E2E test (pytest-playwright): launches uvicorn with isolated DATA_FILE, opens the page, adds folder and URLs, selects and deletes via checkboxes, verifies outcome.
- Tests override DATA_FILE environment variable to isolate data file; production data.json is never touched.

How to run tests locally:
- pip install -r requirements.txt
- pytest -m "not playwright"  # runs unit/integration tests
- python -m playwright install  # once
- pytest -m playwright tests_e2e  # runs E2E


## 14. Dependencies (requirements.txt)
- fastapi==0.111.0
- uvicorn[standard]==0.30.1
- jinja2==3.1.4
- httpx==0.27.0
- pydantic==2.8.2
- pytest==8.3.2
- pytest-asyncio==0.23.8
- pytest-playwright==0.5.0
- playwright==1.45.0
- requests==2.32.3


## 15. Build/Run Instructions
- Install deps: `pip install -r requirements.txt`
- Dev server: `uvicorn main:app --reload`
- Visit: http://127.0.0.1:8000/


## 16. Implementation Details and Edge Cases
- Bulk delete form parsing: HTML with multiple checkboxes requires reading all values; the backend uses `await request.form()` and `form.getlist("node_ids")` to capture all selections (also tolerates comma/space separated input).
- Nested forms are avoided in the template. Checkboxes use the `form="bulkDeleteForm"` attribute to associate with the standalone form.
- Toggle active redirects safely (avoids POST-only URLs) while attempting to preserve prior selection from referer query string.
- Copy name generation: `copy_N_<base>`, if original name already starts with `copy_<k>_`, base is taken as the original base name; ensures uniqueness within folder by incrementing N.
- Import recalculates next ids irrespective of incoming values; folder_id for nodes is normalized to match container folder id.
- Timeouts are clamped to [1,120] seconds.


## 17. Acceptance Criteria (behavioral)
- Creating/renaming/deleting folders works via API and forms.
- Adding/editing/deleting nodes works via API and forms.
- Toggling active and testing single/folder via HTML renders results and chart.
- Bulk delete removes all selected nodes (not just one); delete-all wipes the folder’s nodes.
- Export/Import roundtrip preserves structure and recalculates next ids.
- Preferences set cookies and redirect to a safe GET page; theme switches and timeout is respected in HTML test routes.
- All provided pytest suites pass in a fresh environment with dependencies installed.
