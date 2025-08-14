[![CI](https://github.com/zopyx/zopyx-url-checker-dashboard/actions/workflows/tests.yml/badge.svg)](https://github.com/zopyx/zopyx-url-checker-dashboard/actions/workflows/tests.yml)
# Endpoint Pulse

Project URL: https://github.com/zopyx/zopyx-url-checker-dashboard

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
2) **Recommended:** Use `uv` for faster and more reliable dependency management.
   Install `uv` (see [uv installation docs](https://astral.sh/docs/uv/installation) for more options):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
   Then, create and activate a virtual environment, and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   uv sync
   ```
   Alternatively, using `pip`:
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
uvicorn endpoint_pulse.app:app --reload
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
Data and configuration are stored in a local SQLite database at `data.sqlite3` in the project root (override with `DB_FILE`). The schema has `folders`, `nodes`, and a small `meta` table for ID counters.

## Architecture Notes
- Startup initialization: The database schema is initialized once at app startup via FastAPI's lifespan. This avoids redundant schema checks per request and improves efficiency.
- Modularity: The current codebase is intentionally compact. Future work may extract database access and request handlers into separate modules (e.g., db.py, services.py, api_routes.py) and adopt an ORM like SQLAlchemy for more maintainable data access.

## UI Overview (Server-rendered)
- Left: collapsible tree of folders and their URLs.
- Right: context forms for adding/renaming/deleting folders, adding/editing/deleting/testing URLs.
- Test results show below the forms in a compact table.
- Preferences modal with a dark mode toggle (stored in a cookie).



## Notes
- Authentication/authorization: none (intended for local/network use). Place behind a reverse proxy with auth if needed.
- Timeouts: Configurable via Preferences (default 10 seconds) per request when probing URLs.
- Redirects: HTTP redirects are followed during probes.
- Dark mode preference is stored in a cookie (`theme` = `light`/`dark`).


## Visualization
- After running tests, the page shows a compact response time chart (inline SVG) beneath the results table, including number of requests (measured/total) and average response time.


## Author

Andreas Jung <info@zopyx.com>

This experiment was conducted using PyCharm, Junie, and GPT-5.
