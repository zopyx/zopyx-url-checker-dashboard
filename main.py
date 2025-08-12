from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, HttpUrl

# Simple file-based persistence
DATA_FILE = Path(__file__).parent / "data.json"


def _load_data() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        return {"next_folder_id": 1, "next_node_id": 1, "folders": []}
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"next_folder_id": 1, "next_node_id": 1, "folders": []}


def _save_data(data: Dict[str, Any]) -> None:
    tmp = DATA_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, DATA_FILE)


# Pydantic models
class NodeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    comment: Optional[str] = ""
    active: bool = True


class Node(NodeIn):
    id: int
    folder_id: int


class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class Folder(FolderIn):
    id: int
    nodes: List[Node] = []


# Initialize app
app = FastAPI(title="URL Availability Dashboard", version="0.1.0")

# Static and templates
BASE_DIR = Path(__file__).parent
static_dir = BASE_DIR / "static"
templates_dir = BASE_DIR / "templates"
static_dir.mkdir(parents=True, exist_ok=True)
templates_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, folder_id: Optional[int] = None, node_id: Optional[int] = None):
    data = _load_data()
    selected_folder = None
    selected_node = None
    if node_id is not None:
        selected_node = _find_node(data, node_id)
        if selected_node:
            selected_folder = _find_folder(data, selected_node.get("folder_id"))
    elif folder_id is not None:
        selected_folder = _find_folder(data, folder_id)
    ctx = {
        "request": request,
        "folders": data.get("folders", []),
        "test_result": None,
        "selected_folder": selected_folder,
        "selected_node": selected_node,
    }
    return templates.TemplateResponse("index.html", ctx)


# Helper finders

def _find_folder(data: Dict[str, Any], folder_id: int) -> Optional[Dict[str, Any]]:
    for f in data["folders"]:
        if f["id"] == folder_id:
            return f
    return None


def _find_node(data: Dict[str, Any], node_id: int) -> Optional[Dict[str, Any]]:
    for f in data["folders"]:
        for n in f.get("nodes", []):
            if n["id"] == node_id:
                return n
    return None


def _probe_url(url: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        timeout = httpx.Timeout(10.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": resp.is_success,
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "error": str(e),
            "elapsed_ms": elapsed_ms,
        }


# API endpoints (JSON)
@app.get("/api/tree")
async def get_tree() -> Dict[str, Any]:
    data = _load_data()
    return {"folders": data.get("folders", [])}


@app.post("/api/folders")
async def create_folder(folder: FolderIn) -> Dict[str, Any]:
    data = _load_data()
    folder_id = data.get("next_folder_id", 1)
    data["next_folder_id"] = folder_id + 1
    new_folder = {"id": folder_id, "name": folder.name, "nodes": []}
    data["folders"].append(new_folder)
    _save_data(data)
    return new_folder


@app.put("/api/folders/{folder_id}")
async def rename_folder(folder_id: int, folder: FolderIn) -> Dict[str, Any]:
    data = _load_data()
    f = _find_folder(data, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    f["name"] = folder.name
    _save_data(data)
    return f


@app.delete("/api/folders/{folder_id}")
async def delete_folder(folder_id: int) -> Dict[str, Any]:
    data = _load_data()
    before = len(data["folders"]) 
    data["folders"] = [f for f in data["folders"] if f["id"] != folder_id]
    if len(data["folders"]) == before:
        raise HTTPException(status_code=404, detail="Folder not found")
    _save_data(data)
    return {"ok": True}


@app.post("/api/folders/{folder_id}/nodes")
async def create_node(folder_id: int, node: NodeIn) -> Dict[str, Any]:
    data = _load_data()
    f = _find_folder(data, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    node_id = data.get("next_node_id", 1)
    data["next_node_id"] = node_id + 1
    new_node = {
        "id": node_id,
        "folder_id": folder_id,
        "name": node.name,
        "url": str(node.url),
        "comment": node.comment or "",
        "active": bool(node.active),
    }
    f.setdefault("nodes", []).append(new_node)
    _save_data(data)
    return new_node


@app.put("/api/nodes/{node_id}")
async def update_node(node_id: int, node: NodeIn) -> Dict[str, Any]:
    data = _load_data()
    target = _find_node(data, node_id)
    if not target:
        raise HTTPException(status_code=404, detail="Node not found")
    target.update({
        "name": node.name,
        "url": str(node.url),
        "comment": node.comment or "",
        "active": bool(node.active),
    })
    _save_data(data)
    return target


@app.delete("/api/nodes/{node_id}")
async def delete_node(node_id: int) -> Dict[str, Any]:
    data = _load_data()
    found = False
    for f in data["folders"]:
        nodes = f.get("nodes", [])
        new_nodes = [n for n in nodes if n["id"] != node_id]
        if len(new_nodes) != len(nodes):
            f["nodes"] = new_nodes
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Node not found")
    _save_data(data)
    return {"ok": True}


@app.post("/api/nodes/{node_id}/test")
async def test_node(node_id: int) -> Dict[str, Any]:
    data = _load_data()
    n = _find_node(data, node_id)
    if not n:
        raise HTTPException(status_code=404, detail="Node not found")
    if not n.get("active", True):
        return {"id": node_id, "active": False, "tested": False, "reason": "Node inactive"}

    url = n["url"]
    res = _probe_url(url)
    res.update({"id": node_id, "url": url})
    return res


@app.post("/api/folders/{folder_id}/test")
async def test_folder(folder_id: int) -> Dict[str, Any]:
    data = _load_data()
    f = _find_folder(data, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    results: List[Dict[str, Any]] = []
    for n in f.get("nodes", []) or []:
        entry = {
            "id": n.get("id"),
            "name": n.get("name"),
            "url": n.get("url"),
            "active": bool(n.get("active", True)),
        }
        if not entry["active"]:
            entry.update({"tested": False, "reason": "Node inactive"})
        else:
            probe = _probe_url(entry["url"]) 
            entry.update(probe)
        results.append(entry)
    return {"folder_id": folder_id, "results": results}


# Form-based HTML routes
@app.post("/folders/add")
async def form_add_folder(name: str = Form(...)):
    # Trim and validate
    name = (name or "").strip()
    if not name:
        return RedirectResponse(url="/", status_code=303)
    data = _load_data()
    folder_id = data.get("next_folder_id", 1)
    data["next_folder_id"] = folder_id + 1
    data.setdefault("folders", []).append({"id": folder_id, "name": name, "nodes": []})
    _save_data(data)
    # After adding a folder, focus the folder in the right pane
    return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)


@app.post("/folders/{folder_id}/rename")
async def form_rename_folder(folder_id: int, name: str = Form(...)):
    # Trim and validate
    name = (name or "").strip()
    if not name:
        return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)
    data = _load_data()
    f = _find_folder(data, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    f["name"] = name
    _save_data(data)
    return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)


@app.post("/folders/{folder_id}/delete")
async def form_delete_folder(folder_id: int):
    data = _load_data()
    before = len(data.get("folders", []))
    data["folders"] = [f for f in data.get("folders", []) if f["id"] != folder_id]
    if len(data["folders"]) == before:
        raise HTTPException(status_code=404, detail="Folder not found")
    _save_data(data)
    # After deleting, go back to root with no selection
    return RedirectResponse(url="/", status_code=303)


@app.post("/nodes/add")
async def form_add_node(
    folder_id: int = Form(...),
    name: str = Form(...),
    url: str = Form(...),
    comment: str = Form("") ,
    active: Optional[str] = Form(None),
):
    # Trim values
    name = (name or "").strip()
    url = (url or "").strip()
    comment = (comment or "").strip()
    if not name or not url:
        return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)
    try:
        node_in = NodeIn(name=name, url=url, comment=comment, active=bool(active))
    except Exception:
        # If validation fails, keep focus on the folder
        return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)
    data = _load_data()
    f = _find_folder(data, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    node_id = data.get("next_node_id", 1)
    data["next_node_id"] = node_id + 1
    new_node = {
        "id": node_id,
        "folder_id": folder_id,
        "name": node_in.name,
        "url": str(node_in.url),
        "comment": node_in.comment or "",
        "active": bool(node_in.active),
    }
    f.setdefault("nodes", []).append(new_node)
    _save_data(data)
    # After adding, focus the new node
    return RedirectResponse(url=f"/?node_id={node_id}", status_code=303)


@app.post("/nodes/{node_id}/edit")
async def form_edit_node(
    node_id: int,
    name: str = Form(...),
    url: str = Form(...),
    comment: str = Form(""),
    active: Optional[str] = Form(None),
):
    data = _load_data()
    target = _find_node(data, node_id)
    if not target:
        raise HTTPException(status_code=404, detail="Node not found")
    # Trim values
    name = (name or "").strip()
    url = (url or "").strip()
    comment = (comment or "").strip()
    if not name or not url:
        return RedirectResponse(url=f"/?node_id={node_id}", status_code=303)
    try:
        node_in = NodeIn(name=name, url=url, comment=comment, active=bool(active))
    except Exception:
        return RedirectResponse(url=f"/?node_id={node_id}", status_code=303)
    target.update({
        "name": node_in.name,
        "url": str(node_in.url),
        "comment": node_in.comment or "",
        "active": bool(node_in.active),
    })
    _save_data(data)
    return RedirectResponse(url=f"/?node_id={node_id}", status_code=303)


@app.post("/nodes/{node_id}/delete")
async def form_delete_node(node_id: int):
    data = _load_data()
    parent_folder_id = None
    for f in data.get("folders", []):
        nodes = f.get("nodes", [])
        if any(n.get("id") == node_id for n in nodes):
            parent_folder_id = f.get("id")
        new_nodes = [n for n in nodes if n["id"] != node_id]
        if len(new_nodes) != len(nodes):
            f["nodes"] = new_nodes
            _save_data(data)
            # After deleting a node, focus the parent folder
            if parent_folder_id is not None:
                return RedirectResponse(url=f"/?folder_id={parent_folder_id}", status_code=303)
            return RedirectResponse(url="/", status_code=303)
    raise HTTPException(status_code=404, detail="Node not found")


@app.post("/nodes/{node_id}/test/html")
async def form_test_node_html(request: Request, node_id: int):
    # Run test and show results table (same layout as multi-URL); keep the node selected on the right pane
    data = _load_data()
    n = _find_node(data, node_id)
    if not n:
        raise HTTPException(status_code=404, detail="Node not found")

    # Build a single-row results list consistent with folder test rows
    row: Dict[str, Any] = {
        "id": n.get("id"),
        "name": n.get("name"),
        "url": n.get("url"),
        "active": bool(n.get("active", True)),
    }
    if not row["active"]:
        row.update({"tested": False, "reason": "Node inactive"})
    else:
        probe = _probe_url(row["url"])  # includes ok, status_code, elapsed_ms or error
        row.update(probe)

    selected_folder = _find_folder(data, n.get("folder_id")) if n else None
    ctx = {
        "request": request,
        "folders": data.get("folders", []),
        "selected_folder": selected_folder,
        "selected_node": n,
        "test_results": [row],
    }
    return templates.TemplateResponse("index.html", ctx)


@app.post("/folders/{folder_id}/test/html")
async def form_test_folder_html(request: Request, folder_id: int):
    data = _load_data()
    f = _find_folder(data, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    results: List[Dict[str, Any]] = []
    for n in f.get("nodes", []) or []:
        row = {
            "id": n.get("id"),
            "name": n.get("name"),
            "url": n.get("url"),
            "active": bool(n.get("active", True)),
        }
        if not row["active"]:
            row.update({"tested": False, "reason": "Node inactive"})
        else:
            probe = _probe_url(row["url"]) 
            row.update(probe)
        results.append(row)
    ctx = {
        "request": request,
        "folders": data.get("folders", []),
        "selected_folder": f,
        "selected_node": None,
        "test_results": results,
    }
    return templates.TemplateResponse("index.html", ctx)


# Basic healthcheck
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
