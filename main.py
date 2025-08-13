from __future__ import annotations

import json
import os
import time
import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, HttpUrl

# Simple file-based persistence
# Allow overriding the data file path via environment variable for tests
_DATA_FILE_ENV = os.environ.get("DATA_FILE")
DATA_FILE = Path(_DATA_FILE_ENV) if _DATA_FILE_ENV else Path(__file__).parent / "data.json"


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
    theme = request.cookies.get("theme", "light")
    if theme not in ("light", "dark"):
        theme = "light"
    try:
        timeout_seconds = int(request.cookies.get("timeout", "10"))
    except Exception:
        timeout_seconds = 10
    if timeout_seconds < 1:
        timeout_seconds = 1
    if timeout_seconds > 120:
        timeout_seconds = 120
    ctx = {
        "request": request,
        "folders": data.get("folders", []),
        "test_result": None,
        "selected_folder": selected_folder,
        "selected_node": selected_node,
        "theme": theme,
        "timeout_seconds": timeout_seconds,
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


def _probe_url(url: str, timeout_seconds: int = 10) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        timeout = httpx.Timeout(timeout_seconds)
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


async def _aprobes(urls: List[str], timeout_seconds: int = 10) -> List[Dict[str, Any]]:
    async def fetch_one(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
        t0 = time.perf_counter()
        try:
            resp = await client.get(url)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return {"ok": resp.is_success, "status_code": resp.status_code, "elapsed_ms": elapsed_ms}
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return {"ok": False, "error": str(e), "elapsed_ms": elapsed_ms}

    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        tasks = [fetch_one(client, u) for u in urls]
        return await asyncio.gather(*tasks)


def _build_chart_stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build improved geometry for a cleaner inline SVG chart.
    - Adds margins, proper axes, "nice" y-ticks, and an average line.
    Returns a dict used by the template to render the SVG.
    """
    # Overall SVG size and margins
    width = 720
    height = 220
    margin_left = 48
    margin_right = 12
    margin_top = 12
    margin_bottom = 28
    plot_w = max(1, width - margin_left - margin_right)
    plot_h = max(1, height - margin_top - margin_bottom)

    # Data prep
    measured = [r for r in results if isinstance(r.get("elapsed_ms"), int)]
    count_total = len(results)
    count_measured = len(measured)
    avg_ms: Optional[int] = None
    dmax = 0
    if count_measured:
        total_ms = sum(r.get("elapsed_ms", 0) for r in measured)
        avg_ms = int(round(total_ms / count_measured))
        dmax = max(r.get("elapsed_ms", 0) for r in measured)
    if dmax <= 0:
        dmax = 1

    # Compute a "nice" maximum and tick step for the y-axis (1-2-5 progression)
    def nice_step(raw: float) -> int:
        if raw <= 0:
            return 1
        from math import log10, floor
        exp = floor(log10(raw))
        base = raw / (10 ** exp)
        if base <= 1:
            nice = 1
        elif base <= 2:
            nice = 2
        elif base <= 5:
            nice = 5
        else:
            nice = 10
        return int(nice * (10 ** exp))

    nice_max = ((dmax + 9) // 10) * 10  # round up to nearest 10 as baseline
    step = nice_step(nice_max / 5)  # aim ~5 ticks
    # Recompute nice_max to be a multiple of step that covers dmax
    if step <= 0:
        step = 1
    nice_max = ((dmax + step - 1) // step) * step

    # Scale helper: ms -> y coordinate within plot
    def y_for(ms: int) -> int:
        frac = min(1.0, max(0.0, ms / nice_max))
        return margin_top + int(round((1.0 - frac) * plot_h))

    # Bars geometry
    n = count_total if count_total > 0 else 1
    gap = 8
    bar_width = max(3, int((plot_w - (n + 1) * gap) / n))
    series: List[Dict[str, Any]] = []
    for idx, r in enumerate(results):
        ms = r.get("elapsed_ms") if isinstance(r.get("elapsed_ms"), int) else 0
        y = y_for(ms)
        x = margin_left + gap + idx * (bar_width + gap)
        h = margin_top + plot_h - y
        if r.get("tested") is False:
            color = "#6c757d"
        else:
            color = "#198754" if r.get("ok") else ("#dc3545" if (r.get("error") is not None or r.get("status_code") is not None) else "#6c757d")
        label = str(r.get("name") or idx + 1)
        series.append({
            "x": x,
            "y": y,
            "width": bar_width,
            "height": h,
            "color": color,
            "label": label,
            "ms": ms,
            "xlabel": str(idx + 1),
        })

    # Y-axis ticks
    y_ticks: List[Dict[str, Any]] = []
    tick = 0
    while tick <= nice_max:
        y = y_for(tick)
        y_ticks.append({"y": y, "ms": tick, "label": f"{tick} ms"})
        tick += step

    baseline_y = margin_top + plot_h
    avg_y = y_for(avg_ms) if avg_ms is not None else None

    return {
        "count_total": count_total,
        "count_measured": count_measured,
        "avg_ms": avg_ms,
        "width": width,
        "height": height,
        "series": series,
        "y_ticks": y_ticks,
        "max_ms": nice_max,
        "margin_left": margin_left,
        "margin_right": margin_right,
        "margin_top": margin_top,
        "margin_bottom": margin_bottom,
        "plot_w": plot_w,
        "plot_h": plot_h,
        "baseline_y": baseline_y,
        "avg_y": avg_y,
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

    nodes = f.get("nodes", []) or []
    # Prepare order and active mask
    active_urls: List[str] = []
    active_indices: List[int] = []
    for idx, n in enumerate(nodes):
        if bool(n.get("active", True)):
            active_urls.append(n.get("url"))
            active_indices.append(idx)
    # Run active URLs in parallel with default timeout 10s
    parallel_results: List[Dict[str, Any]] = []
    if active_urls:
        parallel_results = await _aprobes(active_urls, timeout_seconds=10)

    # Stitch results back preserving order
    results: List[Dict[str, Any]] = []
    pr_iter = iter(parallel_results)
    next_map: Dict[int, Dict[str, Any]] = {}
    # Build a map from active index to result
    for i, res in zip(active_indices, parallel_results):
        next_map[i] = res

    for idx, n in enumerate(nodes):
        row = {
            "id": n.get("id"),
            "name": n.get("name"),
            "url": n.get("url"),
            "active": bool(n.get("active", True)),
        }
        if not row["active"]:
            row.update({"tested": False, "reason": "Node inactive", "fetch": "skipped"})
        else:
            probe = next_map.get(idx, {})
            probe = dict(probe)
            probe["fetch"] = "parallel"
            row.update(probe)
        results.append(row)

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


@app.post("/folders/{folder_id}/duplicate")
async def form_duplicate_folder(folder_id: int):
    """Duplicate a folder and all its nodes.
    The new folder name follows copy_N_<base> to ensure uniqueness among folders.
    All nodes are copied with new IDs and linked to the new folder.
    """
    data = _load_data()
    src = _find_folder(data, folder_id)
    if not src:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Compute a unique copy name among folder names
    existing_names = [f.get("name", "") for f in data.get("folders", [])]
    copy_name = _next_copy_name(existing_names, src.get("name", ""))

    # Allocate new folder id
    new_folder_id = data.get("next_folder_id", 1)
    data["next_folder_id"] = new_folder_id + 1

    # Prepare cloned nodes with fresh IDs and correct folder_id
    new_nodes: List[Dict[str, Any]] = []
    for n in src.get("nodes", []) or []:
        new_node_id = data.get("next_node_id", 1)
        data["next_node_id"] = new_node_id + 1
        new_nodes.append({
            "id": new_node_id,
            "folder_id": new_folder_id,
            "name": n.get("name", ""),  # keep original node names
            "url": n.get("url", ""),
            "comment": n.get("comment", ""),
            "active": bool(n.get("active", True)),
        })

    # Append the new folder
    new_folder = {"id": new_folder_id, "name": copy_name, "nodes": new_nodes}
    data.setdefault("folders", []).append(new_folder)
    _save_data(data)

    # Focus the new folder
    return RedirectResponse(url=f"/?folder_id={new_folder_id}", status_code=303)


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
    # After adding from the folder view, keep folder context and update the list
    return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)


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


@app.post("/nodes/bulk_delete")
async def form_bulk_delete(
    request: Request,
    folder_id: Optional[int] = Form(None),
    delete_all_in_folder: Optional[str] = Form(None),
):
    # Load data and determine scope
    data = _load_data()

    # If delete_all_in_folder flag is present and folder_id provided, delete all nodes in that folder
    if delete_all_in_folder and folder_id is not None:
        folder = _find_folder(data, int(folder_id))
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        # Wipe nodes list
        folder["nodes"] = []
        _save_data(data)
        return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)

    # Read raw form to capture multiple values for the same field name
    try:
        form = await request.form()
    except Exception:
        form = {}

    raw_ids = []
    try:
        # Starlette's FormData supports getlist
        if hasattr(form, "getlist"):
            raw_ids = form.getlist("node_ids") or []
        else:
            v = form.get("node_ids") if isinstance(form, dict) else None
            if v is None:
                raw_ids = []
            elif isinstance(v, list):
                raw_ids = v
            else:
                raw_ids = [str(v)]
    except Exception:
        raw_ids = []

    # Normalize node_ids into a list of ints (handles single/multiple/CSV)
    norm_ids: List[int] = []
    for x in raw_ids:
        s = str(x).strip()
        if not s:
            continue
        parts = [p for p in re.split(r"[,\s]+", s) if p]
        for p in parts:
            if p.isdigit():
                try:
                    norm_ids.append(int(p))
                except Exception:
                    pass

    # Otherwise, delete selected node_ids (may be empty -> just redirect)
    to_delete = set(norm_ids)
    if not to_delete:
        # Nothing selected; just go back to folder view if available
        if folder_id is not None:
            return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)
        return RedirectResponse(url="/", status_code=303)

    # Build a mapping folder_id -> filtered nodes after deletion
    for f in data.get("folders", []):
        before = len(f.get("nodes", []))
        if before == 0:
            continue
        f["nodes"] = [n for n in f.get("nodes", []) if int(n.get("id")) not in to_delete]

    _save_data(data)

    # Redirect back to the folder if given; otherwise root
    if folder_id is not None:
        return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)
    return RedirectResponse(url="/", status_code=303)


@app.post("/nodes/{node_id}/duplicate")
async def form_duplicate_node(node_id: int, keep_folder_context: Optional[str] = Form(None)):
    data = _load_data()
    src = _find_node(data, node_id)
    if not src:
        raise HTTPException(status_code=404, detail="Node not found")
    folder = _find_folder(data, int(src.get("folder_id")))
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Compute next copy name within the folder
    existing_names = [n.get("name", "") for n in folder.get("nodes", [])]
    copy_name = _next_copy_name(existing_names, src.get("name", ""))

    new_id = data.get("next_node_id", 1)
    data["next_node_id"] = new_id + 1
    new_node = {
        "id": new_id,
        "folder_id": int(src.get("folder_id")),
        "name": copy_name,
        "url": src.get("url", ""),
        "comment": src.get("comment", ""),
        "active": bool(src.get("active", True)),
    }
    folder.setdefault("nodes", []).append(new_node)
    _save_data(data)
    # Redirect based on context: keep folder view if requested, else focus the new node
    if keep_folder_context:
        return RedirectResponse(url=f"/?folder_id={folder.get('id')}", status_code=303)
    return RedirectResponse(url=f"/?node_id={new_id}", status_code=303)


@app.post("/nodes/{node_id}/toggle_active")
async def form_toggle_node_active(request: Request, node_id: int):
    data = _load_data()
    n = _find_node(data, node_id)
    if not n:
        raise HTTPException(status_code=404, detail="Node not found")
    n["active"] = not bool(n.get("active", True))
    _save_data(data)

    # Compute a safe GET redirect target. Avoid redirecting back to POST-only paths like /folders/{id}/test/html.
    target_url = f"/?folder_id={n.get('folder_id')}"
    ref = request.headers.get("referer") or ""
    try:
        from urllib.parse import urlparse, parse_qs
        pr = urlparse(ref)
        # If the referer path is not a POST-only endpoint, try to preserve selection from its query string.
        if not pr.path.endswith("/test/html"):
            qs = parse_qs(pr.query or "")
            if qs.get("node_id") and qs["node_id"][0].isdigit():
                target_url = f"/?node_id={qs['node_id'][0]}"
            elif qs.get("folder_id") and qs["folder_id"][0].isdigit():
                target_url = f"/?folder_id={qs['folder_id'][0]}"
    except Exception:
        pass

    return RedirectResponse(url=target_url, status_code=303)


@app.post("/nodes/{node_id}/test/html")
async def form_test_node_html(request: Request, node_id: int, keep_folder_context: Optional[str] = Form(None)):
    # Run test and show results table (same layout as multi-URL); by default keep the node selected
    data = _load_data()
    n = _find_node(data, node_id)
    if not n:
        raise HTTPException(status_code=404, detail="Node not found")

    # Get timeout preference
    try:
        timeout_seconds = int(request.cookies.get("timeout", "10"))
    except Exception:
        timeout_seconds = 10
    if timeout_seconds < 1:
        timeout_seconds = 1
    if timeout_seconds > 120:
        timeout_seconds = 120

    # Build a single-row results list consistent with folder test rows
    row: Dict[str, Any] = {
        "id": n.get("id"),
        "name": n.get("name"),
        "url": n.get("url"),
        "active": bool(n.get("active", True)),
    }
    if not row["active"]:
        row.update({"tested": False, "reason": "Node inactive", "fetch": "skipped"})
    else:
        probe = _probe_url(row["url"], timeout_seconds=timeout_seconds)  # includes ok, status_code, elapsed_ms or error
        probe["fetch"] = "single"
        row.update(probe)

    selected_folder = _find_folder(data, n.get("folder_id")) if n else None
    theme = request.cookies.get("theme", "light")
    if theme not in ("light", "dark"):
        theme = "light"
    # Determine whether to keep folder context (no selected_node) or node context
    selected_node_ctx = None if keep_folder_context else n
    chart = _build_chart_stats([row])
    ctx = {
        "request": request,
        "folders": data.get("folders", []),
        "selected_folder": selected_folder,
        "selected_node": selected_node_ctx,
        "test_results": [row],
        "chart": chart,
        "theme": theme,
        "timeout_seconds": timeout_seconds,
    }
    return templates.TemplateResponse("index.html", ctx)


@app.post("/folders/{folder_id}/test/html")
async def form_test_folder_html(request: Request, folder_id: int):
    data = _load_data()
    f = _find_folder(data, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Get timeout preference
    try:
        timeout_seconds = int(request.cookies.get("timeout", "10"))
    except Exception:
        timeout_seconds = 10
    if timeout_seconds < 1:
        timeout_seconds = 1
    if timeout_seconds > 120:
        timeout_seconds = 120

    nodes = f.get("nodes", []) or []
    active_urls: List[str] = []
    active_indices: List[int] = []
    for idx, n in enumerate(nodes):
        if bool(n.get("active", True)):
            active_urls.append(n.get("url"))
            active_indices.append(idx)

    parallel_results: List[Dict[str, Any]] = []
    if active_urls:
        parallel_results = await _aprobes(active_urls, timeout_seconds=timeout_seconds)

    # Map active index to its probe result
    idx_to_result: Dict[int, Dict[str, Any]] = {}
    for i, res in zip(active_indices, parallel_results):
        idx_to_result[i] = res

    results: List[Dict[str, Any]] = []
    for idx, n in enumerate(nodes):
        row = {
            "id": n.get("id"),
            "name": n.get("name"),
            "url": n.get("url"),
            "active": bool(n.get("active", True)),
        }
        if not row["active"]:
            row.update({"tested": False, "reason": "Node inactive", "fetch": "skipped"})
        else:
            probe = dict(idx_to_result.get(idx, {}))
            probe["fetch"] = "parallel"
            row.update(probe)
        results.append(row)

    theme = request.cookies.get("theme", "light")
    if theme not in ("light", "dark"):
        theme = "light"
    chart = _build_chart_stats(results)
    ctx = {
        "request": request,
        "folders": data.get("folders", []),
        "selected_folder": f,
        "selected_node": None,
        "test_results": results,
        "chart": chart,
        "theme": theme,
        "timeout_seconds": timeout_seconds,
    }
    return templates.TemplateResponse("index.html", ctx)


@app.post("/preferences")
async def set_preferences(request: Request, dark_mode: Optional[str] = Form(None), timeout_seconds: Optional[int] = Form(None)):
    # Determine where to redirect back to
    referer = request.headers.get("referer") or "/"
    theme = "dark" if dark_mode else "light"
    # Validate timeout
    ts = 10
    try:
        if timeout_seconds is not None:
            ts = int(timeout_seconds)
    except Exception:
        ts = 10
    if ts < 1:
        ts = 1
    if ts > 120:
        ts = 120

    # Compute a safe GET redirect target. Avoid redirecting back to POST-only paths like */test/html.
    target_url = referer or "/"
    try:
        from urllib.parse import urlparse, parse_qs
        pr = urlparse(referer)
        path = pr.path or ""
        if path.endswith("/test/html"):
            # Patterns: /folders/{id}/test/html or /nodes/{id}/test/html
            parts = path.strip("/").split("/")
            if len(parts) >= 4 and parts[2] == "test":
                if parts[0] == "folders" and parts[1].isdigit():
                    target_url = f"/?folder_id={parts[1]}"
                elif parts[0] == "nodes" and parts[1].isdigit():
                    target_url = f"/?node_id={parts[1]}"
        else:
            # Try to preserve selection from query string if present
            qs = parse_qs(pr.query or "")
            if qs.get("node_id") and qs["node_id"][0].isdigit():
                target_url = f"/?node_id={qs['node_id'][0]}"
            elif qs.get("folder_id") and qs["folder_id"][0].isdigit():
                target_url = f"/?folder_id={qs['folder_id'][0]}"
    except Exception:
        pass

    response = RedirectResponse(url=target_url, status_code=303)
    # Persist for a year
    response.set_cookie(key="theme", value=theme, max_age=60*60*24*365, httponly=False, samesite="lax")
    response.set_cookie(key="timeout", value=str(ts), max_age=60*60*24*365, httponly=False, samesite="lax")
    return response


# Basic healthcheck
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# Export/Import hierarchy
@app.get("/export")
async def export_data():
    data = _load_data()
    # Download as attachment
    filename = f"hierarchy-{int(time.time())}.json"
    return Response(
        content=json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )


@app.post("/import")
async def import_data(file: UploadFile = File(...)):
    # Read and parse uploaded JSON file and replace the current hierarchy.
    try:
        raw = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Unable to read uploaded file")
    try:
        incoming = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    # Basic validation and normalization
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=400, detail="Root JSON must be an object")

    folders = incoming.get("folders")
    if folders is None:
        # allow exporting subset; default to empty
        folders = []
    if not isinstance(folders, list):
        raise HTTPException(status_code=400, detail='"folders" must be a list')

    # Normalize folders and nodes; ensure folder_id is consistent
    norm_folders: List[Dict[str, Any]] = []
    max_folder_id = 0
    max_node_id = 0
    for f in folders:
        if not isinstance(f, dict):
            continue
        fid = int(f.get("id") or 0)
        name = f.get("name") or ""
        nodes = f.get("nodes") or []
        if not isinstance(nodes, list):
            nodes = []
        max_folder_id = max(max_folder_id, fid)
        norm_nodes: List[Dict[str, Any]] = []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            nid = int(n.get("id") or 0)
            # Maintain required fields with safe defaults
            norm_node = {
                "id": nid,
                "folder_id": fid,
                "name": n.get("name") or "",
                "url": n.get("url") or "",
                "comment": n.get("comment") or "",
                "active": bool(n.get("active", True)),
            }
            max_node_id = max(max_node_id, nid)
            norm_nodes.append(norm_node)
        norm_folders.append({"id": fid, "name": str(name), "nodes": norm_nodes})

    # Recalculate next ids regardless of what the file had
    new_data = {
        "next_folder_id": max_folder_id + 1,
        "next_node_id": max_node_id + 1,
        "folders": norm_folders,
    }
    _save_data(new_data)
    # After import, redirect to root; if a folder exists, select the first
    target = "/"
    if norm_folders:
        target = f"/?folder_id={norm_folders[0]['id']}"
    return RedirectResponse(url=target, status_code=303)


def _next_copy_name(existing_names: List[str], original_name: str) -> str:
    """Compute the next copy name like copy_N_<base>.
    If original_name is already a copy (copy_N_base), treat <base> as the base name.
    Ensures uniqueness among existing_names in the folder.
    """
    base = original_name
    m = re.match(r"^copy_(\d+)_+(.*)$", original_name)
    if m and m.group(2):
        base = m.group(2)
    max_n = 0
    pattern = re.compile(rf"^copy_(\d+)_+{re.escape(base)}$")
    for nm in existing_names:
        mm = pattern.match(nm)
        if mm:
            try:
                max_n = max(max_n, int(mm.group(1)))
            except Exception:
                pass
    n = max_n + 1
    candidate = f"copy_{n}_{base}"
    while candidate in existing_names:
        n += 1
        candidate = f"copy_{n}_{base}"
    return candidate
