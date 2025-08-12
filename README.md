# URL Availability Dashboard

A minimal FastAPI + Bootstrap app to manage folders and nodes (URLs) and test their availability.

## Requirements
- Python 3.12

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
uvicorn main:app --reload
```
Then open http://127.0.0.1:8000/ in your browser.

## Features
- Bootstrap-based HTML forms (no custom JS required)
- Folders
  - Add, rename, delete
- Nodes (inside folders)
  - Add, edit, delete
  - Fields: Name, URL, Comment, Active
  - Test availability (HTTP GET) with status and latency; results shown on page

## Data Persistence
Data is stored in a local `data.json` file in the project root using a simple file-based approach.
