# URL Availability Dashboard - Technical Specification

## Overview

The URL Availability Dashboard is a FastAPI-based web application that allows users to organize URLs into folders and monitor their availability. It provides both API endpoints and a web interface for managing hierarchical URL collections and testing their accessibility.

## Core Architecture

### Technology Stack
- **Backend Framework**: FastAPI 0.111.0
- **HTTP Client**: httpx 0.27.0 (for URL testing)
- **Template Engine**: Jinja2 3.1.4
- **Data Validation**: Pydantic 2.8.2
- **Frontend**: Bootstrap 5.3.3, Bootstrap Icons 1.11.3
- **Testing**: pytest 8.3.2, pytest-asyncio 0.23.8, Playwright 1.45.0
- **Server**: Uvicorn 0.30.1

### Data Storage
- **Persistence**: JSON file-based storage (default: `data.json`)
- **Backup Strategy**: Atomic writes using temporary files with `os.replace()`
- **Configuration**: Data file path configurable via `DATA_FILE` environment variable

## Data Models

### Core Entities

#### NodeIn (Input Model)
```python
class NodeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)  # Display name
    url: HttpUrl                                     # Target URL (validated)
    comment: Optional[str] = ""                      # Optional description
    active: bool = True                              # Whether to include in tests
```

#### Node (Complete Model)
```python
class Node(NodeIn):
    id: int        # Unique identifier
    folder_id: int # Parent folder reference
```

#### FolderIn (Input Model)
```python
class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)  # Folder display name
```

#### Folder (Complete Model)
```python
class Folder(FolderIn):
    id: int             # Unique identifier
    nodes: List[Node]   # Child nodes/URLs
```

### Data File Structure
```json
{
  "next_folder_id": 1,    # Auto-incrementing folder ID counter
  "next_node_id": 1,      # Auto-incrementing node ID counter
  "folders": [            # Array of folder objects
    {
      "id": 1,
      "name": "Production",
      "nodes": [
        {
          "id": 1,
          "folder_id": 1,
          "name": "Homepage",
          "url": "https://example.com",
          "comment": "Main site",
          "active": true
        }
      ]
    }
  ]
}
```

## API Endpoints

### Core Data Management

#### GET `/api/tree`
- **Purpose**: Retrieve complete folder/node hierarchy
- **Response**: `{"folders": [Folder]}`
- **Status**: 200 OK

#### POST `/api/folders`
- **Purpose**: Create new folder
- **Body**: `FolderIn`
- **Response**: Created `Folder` object
- **Status**: 200 OK

#### PUT `/api/folders/{folder_id}`
- **Purpose**: Rename existing folder
- **Body**: `FolderIn`
- **Response**: Updated `Folder` object
- **Status**: 200 OK, 404 if not found

#### DELETE `/api/folders/{folder_id}`
- **Purpose**: Delete folder and all contained nodes
- **Response**: `{"ok": true}`
- **Status**: 200 OK, 404 if not found

#### POST `/api/folders/{folder_id}/nodes`
- **Purpose**: Create new node in specified folder
- **Body**: `NodeIn`
- **Response**: Created `Node` object
- **Status**: 200 OK, 404 if folder not found

#### PUT `/api/nodes/{node_id}`
- **Purpose**: Update existing node
- **Body**: `NodeIn`
- **Response**: Updated `Node` object
- **Status**: 200 OK, 404 if not found

#### DELETE `/api/nodes/{node_id}`
- **Purpose**: Delete specific node
- **Response**: `{"ok": true}`
- **Status**: 200 OK, 404 if not found

### URL Testing

#### POST `/api/nodes/{node_id}/test`
- **Purpose**: Test single node URL availability
- **Response**: 
  ```json
  {
    "id": 1,
    "url": "https://example.com",
    "ok": true,
    "status_code": 200,
    "elapsed_ms": 150
  }
  ```
- **Inactive nodes**: `{"id": 1, "active": false, "tested": false, "reason": "Node inactive"}`
- **Error cases**: Include `"error"` field with exception message

#### POST `/api/folders/{folder_id}/test`
- **Purpose**: Test all active nodes in folder (parallel execution)
- **Response**:
  ```json
  {
    "folder_id": 1,
    "results": [
      {
        "id": 1,
        "name": "Homepage",
        "url": "https://example.com",
        "active": true,
        "ok": true,
        "status_code": 200,
        "elapsed_ms": 150,
        "fetch": "parallel"
      }
    ]
  }
  ```

### System Endpoints

#### GET `/healthz`
- **Purpose**: Health check endpoint
- **Response**: `{"status": "ok"}`
- **Status**: 200 OK

#### GET `/export`
- **Purpose**: Export complete data as downloadable JSON
- **Response**: JSON file download with timestamp filename
- **Headers**: `Content-Disposition: attachment`

#### POST `/import`
- **Purpose**: Import data from uploaded JSON file
- **Body**: Multipart file upload (`file` field)
- **Validation**: Normalizes data structure and recalculates ID counters
- **Response**: Redirect to imported folder or root

## Web Interface

### Main Layout
- **Left Panel**: Hierarchical folder/node tree with inline controls
- **Right Panel**: Context-sensitive forms and results
- **Navigation**: Bootstrap navbar with export/import/preferences

### Page States
1. **Default**: Add folder form
2. **Folder Selected**: Rename/delete folder + add node form + nodes table
3. **Node Selected**: Edit node form with test/duplicate/delete actions

### Form-based Endpoints (HTML)

#### POST `/folders/add`
- **Body**: `name` (form field)
- **Redirect**: `/?folder_id={new_folder_id}`

#### POST `/folders/{folder_id}/rename`
- **Body**: `name` (form field)
- **Redirect**: `/?folder_id={folder_id}`

#### POST `/folders/{folder_id}/delete`
- **Redirect**: `/` (root)

#### POST `/nodes/add`
- **Body**: `folder_id`, `name`, `url`, `comment`, `active` (form fields)
- **Redirect**: `/?node_id={new_node_id}`

#### POST `/nodes/{node_id}/edit`
- **Body**: `name`, `url`, `comment`, `active` (form fields)
- **Redirect**: `/?node_id={node_id}`

#### POST `/nodes/{node_id}/delete`
- **Redirect**: `/?folder_id={parent_folder_id}` or `/`

#### POST `/nodes/bulk_delete`
- **Body**: `folder_id`, `node_ids[]` (checkboxes), `delete_all_in_folder` (flag)
- **Purpose**: Delete multiple nodes or all nodes in folder
- **Redirect**: `/?folder_id={folder_id}` or `/`

#### POST `/nodes/{node_id}/duplicate`
- **Purpose**: Create copy with auto-generated name (`copy_N_originalname`)
- **Redirect**: `/?node_id={new_node_id}`

#### POST `/nodes/{node_id}/toggle_active`
- **Purpose**: Toggle node active/inactive status
- **Redirect**: Preserves current context from referer

### Testing Interface

#### POST `/nodes/{node_id}/test/html`
- **Body**: `keep_folder_context` (optional flag)
- **Purpose**: Test single node and display results table
- **Response**: HTML page with test results and response time chart

#### POST `/folders/{folder_id}/test/html`
- **Purpose**: Test all active nodes in folder and display results
- **Response**: HTML page with comprehensive results table and chart

### User Preferences

#### POST `/preferences`
- **Body**: `dark_mode` (checkbox), `timeout_seconds` (1-120)
- **Purpose**: Set UI theme and HTTP timeout
- **Storage**: Browser cookies (1 year expiry)
- **Redirect**: Preserves current context

## URL Testing Implementation

### Single URL Testing (`_probe_url`)
- **Method**: Synchronous HTTP GET with httpx.Client
- **Timeout**: Configurable (1-120 seconds, default 10)
- **Redirects**: Follows redirects automatically
- **Metrics**: Response time measurement using `time.perf_counter()`
- **Error Handling**: Catches all exceptions, returns structured error info

### Parallel Testing (`_aprobes`)
- **Method**: Asynchronous with httpx.AsyncClient and asyncio.gather
- **Concurrency**: All active URLs tested simultaneously
- **Timeout**: Same as single URL testing
- **Result Mapping**: Preserves original node order in results

### Test Results Structure
```python
{
    "ok": bool,              # Success indicator
    "status_code": int,      # HTTP status code (if available)
    "elapsed_ms": int,       # Response time in milliseconds
    "error": str,            # Exception message (if error occurred)
    "fetch": str,            # "single", "parallel", or "skipped"
    "tested": bool,          # Whether test was actually performed
    "reason": str            # Explanation for skipped tests
}
```

## Chart Generation (`_build_chart_stats`)

### Purpose
Generate SVG bar chart data for response time visualization

### Input
List of test result objects with `elapsed_ms`, `ok`, and `tested` fields

### Output
```python
{
    "count_total": int,      # Total number of URLs
    "count_measured": int,   # Number of URLs actually tested
    "avg_ms": int,          # Average response time (or None)
    "width": 640,           # Chart width
    "height": 160,          # Chart height
    "gap": 8,               # Bar spacing
    "series": [             # Bar data for SVG rendering
        {
            "x": int,       # X position
            "y": int,       # Y position
            "width": int,   # Bar width
            "height": int,  # Bar height
            "color": str,   # Color (#198754=OK, #dc3545=error, #6c757d=inactive)
            "label": str,   # Node name
            "ms": int       # Response time
        }
    ]
}
```

## Utility Functions

### Copy Name Generation (`_next_copy_name`)
- **Purpose**: Generate unique copy names for node duplication
- **Pattern**: `copy_N_basename` where N is auto-incremented
- **Logic**: Detects existing copy pattern and increments from highest number
- **Uniqueness**: Ensures no conflicts within target folder

### File Operations
- **Loading**: `_load_data()` - Safely loads JSON with fallback to empty structure
- **Saving**: `_save_data()` - Atomic write using temporary file + `os.replace()`
- **Path Resolution**: Supports `DATA_FILE` environment variable for testing

### Helper Functions
- `_find_folder(data, folder_id)` - Locate folder by ID
- `_find_node(data, node_id)` - Locate node by ID (searches all folders)

## Frontend JavaScript (`static/js/app.js`)

### API Client
- **Function**: `api(path, options)` - Generic fetch wrapper with JSON handling
- **Error Handling**: Extracts detail from error responses

### DOM Utilities
- **Function**: `el(tag, attrs, ...children)` - createElement helper
- **Features**: Event binding, class/attribute setting, nested child support

### Tree Management
- **Function**: `loadTree()` - Renders complete folder/node hierarchy
- **Function**: `toggleFolder(id)` - Show/hide folder contents
- **CRUD Operations**: Add/rename/delete folders and nodes with prompt-based input

### Testing Interface
- **Function**: `testNode(id)` - Single URL test with result display
- **Result Display**: Updates `#details` element with formatted test results

## Deployment Requirements

### Environment Variables
- `DATA_FILE`: Optional path to data file (defaults to `./data.json`)

### Dependencies
All dependencies specified in `requirements.txt`:
- FastAPI ecosystem (fastapi, uvicorn, jinja2)
- HTTP client (httpx, requests)
- Data validation (pydantic)
- Testing framework (pytest, pytest-asyncio, playwright)

### Static Assets
- `/static/css/style.css`: Theme-aware Bootstrap overrides
- `/static/js/app.js`: Frontend interaction logic (alternative to HTML forms)
- `/templates/index.html`: Main application template

### File Permissions
- Read/write access to data file location
- Read access to static and template directories

## Security Considerations

### Input Validation
- URL validation via Pydantic's `HttpUrl` type
- String length limits (1-200 characters)
- Form data sanitization (strip whitespace)

### File Safety
- Atomic file writes prevent data corruption
- JSON parsing with exception handling
- No direct file system access beyond data file

### HTTP Security
- HTTPX timeout enforcement prevents hanging requests
- No execution of user-provided code
- Bootstrap framework provides XSS protection in templates

### Data Privacy
- All data stored locally (no external services)
- No authentication system (suitable for private/internal use)
- Cookie-based preferences (non-sensitive data only)

## Testing Strategy

### Unit Tests (`tests/`)
- API endpoint testing with FastAPI TestClient
- CRUD operations validation
- Error condition handling
- Mock HTTP responses for URL testing

### End-to-End Tests (`tests_e2e/`)
- Browser-based testing with Playwright
- Complete user workflow validation
- JavaScript interaction testing

### Test Configuration (`pytest.ini`)
- Playwright marker for browser tests
- Selective test execution support

## Browser Compatibility

### Supported Browsers
- Modern browsers supporting ES6+ features
- Bootstrap 5.3.3 compatibility requirements
- JavaScript fetch API support required

### Progressive Enhancement
- Core functionality works without JavaScript
- Form-based fallbacks for all operations
- CSS custom properties for theming

## Performance Characteristics

### Scalability Limits
- File-based storage suitable for moderate datasets (< 10,000 URLs)
- Parallel testing limited by system resources and target server capacity
- Single-threaded request handling via FastAPI/Uvicorn

### Optimization Features
- Async URL testing for folder operations
- Atomic file operations minimize I/O blocking
- Client-side tree management reduces server requests (JS version)

### Response Time Expectations
- Local operations: < 10ms
- URL testing: Depends on target servers (configurable timeout 1-120s)
- File I/O: < 100ms for typical dataset sizes

This specification provides complete implementation guidance for recreating the URL Availability Dashboard functionality using the described technology stack and architectural patterns.