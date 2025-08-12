# Master Prompt — “Generate a Complete Spec from a FastAPI Codebase”

## 1. Executive Summary

The URL Availability Dashboard is a small, self-hosted web application for organizing, monitoring, and testing website URLs. Its primary user is a developer, QA engineer, or system administrator who needs to track the health of multiple web endpoints. The application allows users to group URLs into folders, toggle their active status for testing, and probe their availability via HTTP GET requests. The entire user interface is server-rendered using FastAPI and Jinja2 templates, styled with Bootstrap, and requires no custom client-side JavaScript for its core functionality. Data is persisted in a single JSON file, making the application portable and easy to set up.

## 2. Glossary & Domain Model

*   **Folder**: A container for grouping related Nodes. It has a name and an ID.
*   **Node**: Represents a single URL to be monitored. It has a name, URL, an optional comment, an active status, an ID, and a parent Folder ID.
*   **Test Result**: The outcome of probing a Node's URL. It includes the HTTP status code, response time, and an "ok" status.

**Entity Model:**

*   `Folder`
    *   `id`: int (primary key)
    *   `name`: string
    *   `nodes`: List[`Node`] (one-to-many relationship)
*   `Node`
    *   `id`: int (primary key)
    *   `folder_id`: int (foreign key to `Folder`)
    *   `name`: string
    *   `url`: string (HttpUrl)
    *   `comment`: string (optional)
    *   `active`: boolean

## 3. System Context

*   **External Systems/Services**: The application makes outbound HTTP/HTTPS GET requests to the URLs defined in the **Nodes**. It also fetches Bootstrap and Bootstrap Icons from a CDN (`cdn.jsdelivr.net`).
*   **Secrets**: There are no secrets or API keys. The application is unauthenticated.
*   **Callbacks/Webhooks**: The application does not receive any callbacks or webhooks.

## 4. Functional Requirements (User-Facing)

### 4.1 Folder Management

*   **User Story**: As a user, I want to create, rename, and delete folders so I can organize my URLs by category.
*   **Preconditions & Triggers**: User navigates to the main page.
*   **Main Flow (Create)**:
    1.  User clicks the "Add" button in the "Folders" panel or fills the "Add Folder" form.
    2.  User enters a folder name in a modal or form.
    3.  User submits the form.
    4.  The system creates a new folder and refreshes the page, showing the new folder in the left-hand tree.
*   **Alternate Flow (Rename)**:
    1.  User clicks on a folder in the tree to select it.
    2.  The right-hand panel shows the "Rename folder" form.
    3.  User enters a new name and clicks "Save".
    4.  The system updates the folder name and refreshes the page.
*   **Alternate Flow (Delete)**:
    1.  User selects a folder.
    2.  User clicks the "Delete" button.
    3.  A confirmation modal appears.
    4.  User confirms the deletion.
    5.  The system deletes the folder and all its associated nodes, then refreshes the page.
*   **Acceptance Criteria**:
    *   A new folder can be created with a unique ID.
    *   A folder's name can be updated.
    *   Deleting a folder also deletes all nodes within it.
    *   Folder names must be between 1 and 200 characters.
*   **Evidence**:
    *   `main.py:L310-L320` (`form_add_folder`)
    *   `main.py:L323-L335` (`form_rename_folder`)
    *   `main.py:L338-L347` (`form_delete_folder`)
    *   `templates/index.html:L131-L140` (Add Folder Form)
    *   `templates/index.html:L145-L152` (Rename Folder Form)

### 4.2 Node (URL) Management

*   **User Story**: As a user, I want to add, edit, delete, and duplicate URLs within a folder to manage my monitored endpoints.
*   **Preconditions & Triggers**: A folder exists and is selected.
*   **Main Flow (Add)**:
    1.  User selects a folder.
    2.  The "Add Node" form appears in the right-hand panel.
    3.  User fills in the Name, URL, optional Comment, and sets the Active status.
    4.  User clicks "Add".
    5.  The system creates the node, associates it with the folder, and refreshes the page, focusing on the new node.
*   **Alternate Flow (Edit)**:
    1.  User clicks a node in the tree.
    2.  The "Edit Node" form appears.
    3.  User modifies the fields and clicks "Save".
    4.  The system updates the node and refreshes the page.
*   **Alternate Flow (Delete)**:
    1.  User clicks the delete icon next to a node in the folder's URL table or clicks the "Delete" button on the "Edit Node" form.
    2.  A confirmation modal appears.
    3.  User confirms.
    4.  The system deletes the node and refreshes the page.
*   **Alternate Flow (Bulk Delete)**:
    1.  User selects a folder.
    2.  User checks one or more checkboxes next to URLs in the table.
    3.  User clicks the "Delete selected" button.
    4.  The system deletes all selected nodes and refreshes.
*   **Alternate Flow (Duplicate)**:
    1.  User clicks the duplicate icon next to a node.
    2.  The system creates a copy of the node in the same folder with a name like `copy_1_<original_name>`.
*   **Acceptance Criteria**:
    *   A node must have a name (1-200 chars) and a valid HTTP/HTTPS URL.
    *   A node must belong to a folder.
    *   Nodes can be toggled between 'active' and 'inactive' status.
    *   Duplicated nodes have unique names.
*   **Evidence**:
    *   `main.py:L350-L383` (`form_add_node`)
    *   `main.py:L386-L413` (`form_edit_node`)
    *   `main.py:L416-L434` (`form_delete_node`)
    *   `main.py:L437-L508` (`form_bulk_delete`)
    *   `main.py:L511-L536` (`form_duplicate_node`)
    *   `main.py:L539-L562` (`form_toggle_node_active`)

### 4.3 URL Testing

*   **User Story**: As a user, I want to test a single URL or all URLs in a folder to check their availability and response time.
*   **Preconditions & Triggers**: At least one active node exists.
*   **Main Flow (Test Single)**:
    1.  User clicks the "Test" button next to a node.
    2.  The system sends an HTTP GET request to the node's URL.
    3.  The page reloads, showing a results table with the status code, response time, and success/fail status.
*   **Alternate Flow (Test Folder)**:
    1.  User clicks the "Test all" button for a folder.
    2.  The system sends parallel HTTP GET requests to all *active* nodes in that folder.
    3.  The page reloads, showing a results table and a bar chart visualizing the response times for all tested nodes.
*   **Acceptance Criteria**:
    *   Testing follows HTTP redirects.
    *   Testing has a configurable timeout (default 10s).
    *   Inactive nodes are skipped during tests.
    *   Test results display status code, elapsed milliseconds, and any errors.
*   **Evidence**:
    *   `main.py:L565-L606` (`form_test_node_html`)
    *   `main.py:L609-L660` (`form_test_folder_html`)
    *   `main.py:L141-L158` (`_probe_url`)
    *   `main.py:L161-L176` (`_aprobes`)

### 4.4 Data Management

*   **User Story**: As a user, I want to export my entire URL hierarchy to a file for backup and import it back later.
*   **Preconditions & Triggers**: User is on the main page.
*   **Main Flow (Export)**:
    1.  User clicks the "Export" button in the navbar.
    2.  The browser downloads a JSON file (`hierarchy-<timestamp>.json`) containing all folders and nodes.
*   **Main Flow (Import)**:
    1.  User clicks the "Import" button, which opens a modal.
    2.  User selects a valid JSON file.
    3.  User clicks "Import".
    4.  The system replaces the current data with the content from the file and refreshes the page.
*   **Acceptance Criteria**:
    *   Exported file is a valid JSON representation of the application's state.
    *   Importing a valid file completely overwrites existing data.
    *   Importing an invalid or malformed file shows an error.
*   **Evidence**:
    *   `main.py:L701-L710` (`export_data`)
    *   `main.py:L713-L771` (`import_data`)

## 5. API Specification (Inferred + Verified)

All endpoints are unauthenticated.

| Method | Path                          | Purpose                               |
| :----- | :---------------------------- | :------------------------------------ |
| GET    | `/api/tree`                   | Retrieve the full folder/node tree.   |
| POST   | `/api/folders`                | Create a new folder.                  |
| PUT    | `/api/folders/{folder_id}`    | Rename an existing folder.            |
| DELETE | `/api/folders/{folder_id}`    | Delete a folder and all its nodes.    |
| POST   | `/api/folders/{folder_id}/nodes` | Create a new node in a folder.      |
| PUT    | `/api/nodes/{node_id}`        | Update a node.                        |
| DELETE | `/api/nodes/{node_id}`        | Delete a node.                        |
| POST   | `/api/nodes/{node_id}/test`   | Probe a single URL.                   |
| POST   | `/api/folders/{folder_id}/test` | Probe all active nodes in a folder. |
| GET    | `/healthz`                    | Simple health check.                  |

### Request/Response Schemas

*   **FolderIn** (`name: str`)
*   **NodeIn** (`name: str`, `url: HttpUrl`, `comment: str`, `active: bool`)

A full OpenAPI spec could be generated from `app.openapi()`, but the `README.md` provides an accurate summary. There are no mismatches found between the code and the documentation.

*   **Evidence**:
    *   `main.py:L220-L299` (All JSON API endpoint definitions)
    *   `main.py:L40-L57` (Pydantic models for schemas)

## 6. Data & State

*   **Data Persistence**: State is stored in a single JSON file, `data.json`, in the project root. The path can be overridden by the `DATA_FILE` environment variable.
*   **Data Models**:
    *   `NodeIn` / `Node`: Defines the structure of a URL entry.
    *   `FolderIn` / `Folder`: Defines the structure of a folder.
    *   The top-level JSON object contains `next_folder_id`, `next_node_id`, and a list of `folders`.
*   **Constraints**:
    *   `NodeIn.name`, `FolderIn.name`: 1 to 200 characters.
    *   `NodeIn.url`: Must be a valid HTTP/HTTPS URL.
*   **Caching**: There is no caching layer. Data is read from `data.json` on each request that needs it.
*   **Evidence**:
    *   `main.py:L18-L35` (`_load_data`, `_save_data`)
    *   `main.py:L40-L57` (Pydantic models)

## 7. Security Model

*   **Authentication/Authorization**: None. The application is intended for local or trusted network use. The `README.md` suggests placing it behind a reverse proxy for authentication.
*   **Permissions**: There are no users, roles, or permissions. All operations are public.
*   **Input Validation**:
    *   API endpoints use Pydantic models for request body validation, which prevents malformed data.
    *   HTML form endpoints perform basic `strip()` and presence checks on inputs. Pydantic models are used for validation where applicable.
*   **CSRF/CORS**: No CSRF protection is implemented. CORS is not explicitly configured, so default browser same-origin policies apply.
*   **Secrets Handling**: No secrets are used or stored.
*   **Evidence**:
    *   `main.py:L40-L57` (Pydantic models for validation)
    *   `main.py:L356-L362`, `L396-L404` (Form input validation)

## 8. Error Handling & Observability

*   **Error Taxonomy**:
    *   **404 Not Found**: Returned for API or form requests targeting a `folder_id` or `node_id` that does not exist.
    *   **422 Unprocessable Entity**: Returned by API endpoints if the request body fails Pydantic validation.
    *   **400 Bad Request**: Returned by the `/import` endpoint for file read errors or invalid JSON.
    *   **303 See Other**: Used for redirects after successful form submissions.
*   **Logging**: No structured logging is configured. Uvicorn provides access logging.
*   **Metrics/Tracing**: No metrics or tracing are implemented.
*   **Timeouts**: URL probing has a configurable timeout (1-120 seconds, default 10), stored in a browser cookie.
*   **Evidence**:
    *   `main.py:L240`, `L250`, `L261`, etc. (HTTPException usage)
    *   `main.py:L663-L698` (`set_preferences` for timeout)

## 9. Non-Functional Requirements

*   **Performance**: The use of `httpx.AsyncClient` and `asyncio.gather` for folder tests implies a requirement for concurrent, non-blocking I/O when probing multiple URLs.
*   **Availability**: The application runs as a single `uvicorn` process. High availability is not an inherent feature and would require external process management.
*   **I18n/L10n**: No internationalization support. All text is in English.
*   **Accessibility**: Uses standard Bootstrap 5 components, which have good accessibility practices. Some `aria-label` attributes are used for icon-only buttons.
*   **Evidence**:
    *   `main.py:L161-L176` (`_aprobes` for concurrent requests)
    *   `templates/index.html:L80`, `L230` (Use of `aria-label`)

## 10. UI/UX Flows

*   **Screen Inventory**:
    *   **Main Page (`/`)**: A two-pane layout.
        *   **Left Pane**: A collapsible tree view of Folders and their child Nodes.
        *   **Right Pane**: A contextual area that displays forms for adding/editing folders/nodes based on the selection in the left pane.
        *   **Results Area**: Below the forms, a table and chart appear after a test is run.
*   **Wire-flow**:
    1.  User lands on `/`. Left pane shows folders. Right pane shows "Add Folder" form.
    2.  User clicks "Add" to create a folder. Page reloads, new folder appears in tree, right pane shows folder details and "Add Node" form.
    3.  User clicks a folder. Right pane updates to that folder's context.
    4.  User adds a node. Page reloads, new node appears under its folder in the tree, right pane updates to show the new node's "Edit" form.
    5.  User clicks "Test". Page reloads to show results in a table and chart below the form area.
*   **Form Fields & Validations**:
    *   All name fields are `required` and have `minlength="1"`.
    *   URL fields are `type="url"` with a `pattern="https?://.+"`.
    *   The `active` flag is a checkbox.
*   **Evidence**:
    *   `templates/index.html`: The entire file defines the UI structure and flow.
    *   `main.py:L72-L101` (`index` endpoint controls what is displayed based on query parameters).

## 11. Sequence Diagrams (text descriptions)

### 1. Add and Test a Node

1.  **User** -> **Browser**: Fills "Add Node" form and clicks "Add".
2.  **Browser** -> **FastAPI**: `POST /nodes/add` with form data.
3.  **FastAPI** -> **`data.json`**: Reads current data.
4.  **FastAPI**: Validates data, creates new node, assigns new ID.
5.  **FastAPI** -> **`data.json`**: Writes updated data.
6.  **FastAPI** -> **Browser**: Responds with `303 Redirect` to `/?node_id=<new_id>`.
7.  **Browser** -> **FastAPI**: `GET /?node_id=<new_id>`.
8.  **FastAPI** -> **Browser**: Renders `index.html` with the new node selected.
9.  **User** -> **Browser**: Clicks "Test" button for the new node.
10. **Browser** -> **FastAPI**: `POST /nodes/<id>/test/html`.
11. **FastAPI** -> **External URL**: `httpx.get(node.url)`.
12. **External URL** -> **FastAPI**: Returns HTTP response.
13. **FastAPI** -> **Browser**: Renders `index.html` with test results table and chart.

## 12. Config & Deployment Assumptions

*   **Environment Variables**:
    *   `DATA_FILE`: Optional. Overrides the path to the `data.json` file. Used in tests to prevent data corruption.
*   **Startup Command**: `uvicorn main:app --reload` (for development).
*   **Dependencies**: Listed in `requirements.txt`.
*   **Python Version**: 3.12 is specified in the `README.md`.
*   **Evidence**:
    *   `main.py:L18-L19` (DATA_FILE env var)
    *   `README.md` (Setup and run commands)
    *   `requirements.txt` (Dependencies)

## 13. Traceability Matrix

| Requirement ID | Description                 | Evidence                               | Endpoints Impacted                                                                                             |
| :------------- | :-------------------------- | :------------------------------------- | :------------------------------------------------------------------------------------------------------------- |
| FR-4.1         | Folder Management           | `main.py:L310-L347`                    | `/folders/add`, `/folders/{id}/rename`, `/folders/{id}/delete`, `/api/folders`, `/api/folders/{id}`             |
| FR-4.2         | Node Management             | `main.py:L350-L562`                    | `/nodes/add`, `/nodes/{id}/edit`, `/nodes/{id}/delete`, `/nodes/bulk_delete`, `/nodes/{id}/duplicate`, `/api/nodes`, `/api/nodes/{id}` |
| FR-4.3         | URL Testing                 | `main.py:L565-L660`                    | `/nodes/{id}/test/html`, `/folders/{id}/test/html`, `/api/nodes/{id}/test`, `/api/folders/{id}/test`         |
| FR-4.4         | Data Import/Export          | `main.py:L701-L771`                    | `/export`, `/import`                                                                                           |
| SEC-7.1        | No Authentication           | Entire codebase                        | All                                                                                                            |
| DATA-6.1       | JSON File Persistence       | `main.py:L18-L35`                      | All state-changing endpoints                                                                                   |

## 14. Open Questions & Assumptions

1.  **Assumption**: The application is designed for a single user or a small, trusted group. The lack of authentication and file-based storage implies it is not suitable for a multi-tenant or high-concurrency environment without significant changes.
2.  **Assumption**: The user is expected to manage the `uvicorn` process. There is no built-in daemonization or service management.
3.  **Open Question**: How should the application behave if the `data.json` file becomes corrupted or is not writable due to file permissions? The current implementation might raise an unhandled exception or fail silently. `_load_data` has a `try-except` block that returns a default empty state, which could lead to data loss if the file is temporarily unreadable. `_save_data` does not have similar protection.
