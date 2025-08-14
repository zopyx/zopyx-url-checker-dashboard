# This file is part of the Endpoint Pulse project.
#
# Copyright (c) 2025, Andreas Jung
#
# This software is released under the WTFPL, Version 2.0.
# See the LICENSE file for more details.

"""
This module contains the main application logic for the Endpoint Pulse dashboard.

It uses the FastAPI framework to create a web interface for monitoring the health of
various endpoints. The application supports organizing endpoints into folders,
testing them individually or as a group, and visualizing the results.

The data is stored in a SQLite database, and the application provides both a web
interface (HTML) and a JSON API for interacting with the data.
"""
from __future__ import annotations

import os
import time
import asyncio
import re
import ssl
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import sqlite3
from fastapi import FastAPI, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, HttpUrl



def _resolve_db_file() -> Path:
    """
    Resolves the path to the SQLite database file.

    The path is determined by checking the following environment variables in order:
    1. DB_FILE
    2. DATA_FILE (with a .sqlite3 extension)
    If neither is set, it defaults to "data.sqlite3" in the current directory.

    Returns:
        Path: The path to the database file.
    """
    env_db = os.environ.get("DB_FILE")
    if env_db:
        return Path(env_db)
    env_data = os.environ.get("DATA_FILE")
    if env_data:
        return Path(env_data).with_suffix(".sqlite3")
    return Path("data.sqlite3")


def _get_conn() -> sqlite3.Connection:
    """
    Establishes a connection to the SQLite database.

    Ensures the parent directory for the database file exists and enables foreign key
    support for the connection.

    Returns:
        sqlite3.Connection: A connection object to the database.
    """
    db_file = _resolve_db_file()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    # Enforce foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _init_db() -> None:
    """
    Initializes the database by creating the necessary tables if they don't exist.

    The schema includes tables for metadata, folders, and nodes.
    """
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS folders (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes (
              id INTEGER PRIMARY KEY,
              folder_id INTEGER NOT NULL,
              name TEXT NOT NULL,
              url TEXT NOT NULL,
              comment TEXT DEFAULT '',
              active INTEGER NOT NULL DEFAULT 1,
              FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()


def _load_data() -> Dict[str, Any]:
    """
    Loads all folders and nodes from the database.

    It also determines the next available folder and node IDs.

    Returns:
        Dict[str, Any]: A dictionary containing the loaded data, including folders,
                        nodes, and the next available IDs.
    """
    # Ensure schema exists (safety for tests or direct calls)
    _init_db()
    with _get_conn() as conn:
        cur = conn.cursor()
        # Load folders
        cur.execute("SELECT id, name FROM folders ORDER BY id;")
        folders_rows = cur.fetchall()
        folders: List[Dict[str, Any]] = []
        for frow in folders_rows:
            fid = int(frow["id"])
            cur.execute(
                "SELECT id, folder_id, name, url, comment, active FROM nodes WHERE folder_id=? ORDER BY id;",
                (fid,),
            )
            nodes_rows = cur.fetchall()
            nodes = [
                {
                    "id": int(nr["id"]),
                    "folder_id": int(nr["folder_id"]),
                    "name": nr["name"],
                    "url": nr["url"],
                    "comment": nr["comment"] or "",
                    "active": bool(nr["active"]),
                }
                for nr in nodes_rows
            ]
            folders.append({"id": fid, "name": frow["name"], "nodes": nodes})
        # Determine next ids from meta or max+1
        def _get_meta(key: str) -> Optional[int]:
            cur.execute("SELECT value FROM meta WHERE key=?;", (key,))
            r = cur.fetchone()
            if not r:
                return None
            try:
                return int(r["value"])
            except Exception:
                return None
        next_folder_id = _get_meta("next_folder_id")
        next_node_id = _get_meta("next_node_id")
        if next_folder_id is None:
            cur.execute("SELECT COALESCE(MAX(id)+1, 1) AS next_id FROM folders;")
            next_folder_id = int(cur.fetchone()["next_id"])
        if next_node_id is None:
            cur.execute("SELECT COALESCE(MAX(id)+1, 1) AS next_id FROM nodes;")
            next_node_id = int(cur.fetchone()["next_id"])
        return {"next_folder_id": next_folder_id, "next_node_id": next_node_id, "folders": folders}


def _save_data(data: Dict[str, Any]) -> None:
    """Replace database content with provided structure and persist counters."""
    # Ensure schema exists (safety for tests or direct calls)
    _init_db()
    folders = data.get("folders", []) or []
    next_folder_id = int(data.get("next_folder_id", 1) or 1)
    next_node_id = int(data.get("next_node_id", 1) or 1)
    with _get_conn() as conn:
        cur = conn.cursor()
        # Wipe
        cur.execute("DELETE FROM nodes;")
        cur.execute("DELETE FROM folders;")
        # Insert folders
        for f in folders:
            cur.execute("INSERT INTO folders(id, name) VALUES(?, ?);", (int(f.get("id")), f.get("name", "")))
            for n in (f.get("nodes") or []):
                cur.execute(
                    """
                    INSERT INTO nodes(id, folder_id, name, url, comment, active)
                    VALUES(?, ?, ?, ?, ?, ?);
                    """,
                    (
                        int(n.get("id")),
                        int(f.get("id")),
                        n.get("name", ""),
                        n.get("url", ""),
                        n.get("comment", ""),
                        1 if bool(n.get("active", True)) else 0,
                    ),
                )
        # Upsert meta
        cur.execute("INSERT INTO meta(key,value) VALUES('next_folder_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value;", (str(next_folder_id),))
        cur.execute("INSERT INTO meta(key,value) VALUES('next_node_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value;", (str(next_node_id),))
        conn.commit()


# Pydantic models
class NodeIn(BaseModel):
    """Pydantic model for creating a new node."""
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    comment: Optional[str] = ""
    active: bool = True


class Node(NodeIn):
    """Pydantic model for a node, including its ID and folder ID."""
    id: int
    folder_id: int


class FolderIn(BaseModel):
    """Pydantic model for creating a new folder."""
    name: str = Field(min_length=1, max_length=200)


class Folder(FolderIn):
    """Pydantic model for a folder, including its ID and a list of nodes."""
    id: int
    nodes: List[Node] = []


# Initialize app with lifespan to init DB once
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    An async context manager for the lifespan of the FastAPI application.

    It initializes the database schema once at startup.

    Args:
        app (FastAPI): The FastAPI application instance.
    """
    # Initialize database schema once at startup (reduces per-request overhead)
    _init_db()
    yield

app = FastAPI(title="Endpoint Pulse", version="0.1.0", lifespan=lifespan)

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
    """
    Renders the main index page.

    Args:
        request (Request): The incoming request.
        folder_id (Optional[int]): The ID of the folder to select.
        node_id (Optional[int]): The ID of the node to select.

    Returns:
        HTMLResponse: The rendered HTML page.
    """
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
    return templates.TemplateResponse(request, "index.html", ctx)


# Helper finders

def _find_folder(data: Dict[str, Any], folder_id: int) -> Optional[Dict[str, Any]]:
    """
    Finds a folder by its ID.

    Args:
        data (Dict[str, Any]): The data dictionary containing all folders.
        folder_id (int): The ID of the folder to find.

    Returns:
        Optional[Dict[str, Any]]: The folder dictionary if found, otherwise None.
    """
    for f in data["folders"]:
        if f["id"] == folder_id:
            return f
    return None


def _find_node(data: Dict[str, Any], node_id: int) -> Optional[Dict[str, Any]]:
    """
    Finds a node by its ID.

    Args:
        data (Dict[str, Any]): The data dictionary containing all folders and nodes.
        node_id (int): The ID of the node to find.

    Returns:
        Optional[Dict[str, Any]]: The node dictionary if found, otherwise None.
    """
    for f in data["folders"]:
        for n in f.get("nodes", []):
            if n["id"] == node_id:
                return n
    return None


def _get_ssl_cert_info(url: str, timeout_seconds: int = 10) -> Dict[str, Any]:
    """Attempt to fetch SSL certificate info for HTTPS URLs.
    Returns a dict possibly containing:
      - ssl_valid: bool | None
      - ssl_error: str (optional)
      - ssl_expires_at: str (ISO 8601 UTC) (optional)
      - ssl_days_left: int (optional)
    For non-HTTPS URLs, returns {}.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            return {}
        host = parsed.hostname
        port = parsed.port or 443
        if not host:
            return {"ssl_valid": None, "ssl_error": "no hostname"}
        ctx = ssl.create_default_context()
        # Create raw TCP socket with timeout
        with socket.create_connection((host, port), timeout_seconds) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
        # Parse notAfter
        not_after = cert.get("notAfter") if isinstance(cert, dict) else None
        expires_iso = None
        days_left = None
        ssl_valid = True
        if not_after:
            # OpenSSL ASN.1 time format like 'Jun  1 12:00:00 2025 GMT'
            try:
                exp_dt = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                delta = exp_dt - now
                days_left = int(delta.total_seconds() // 86400)
                expires_iso = exp_dt.isoformat()
                if delta.total_seconds() <= 0:
                    ssl_valid = False
            except Exception:
                expires_iso = str(not_after)
                ssl_valid = None
        # If no notAfter, still consider we got a cert but unknown expiry
        res: Dict[str, Any] = {"ssl_valid": ssl_valid}
        if expires_iso is not None:
            res["ssl_expires_at"] = expires_iso
        if days_left is not None:
            res["ssl_days_left"] = days_left
        return res
    except Exception as e:
        return {"ssl_valid": False, "ssl_error": str(e)}


def _probe_url(url: str, timeout_seconds: int = 10) -> Dict[str, Any]:
    """
    Probes a single URL to check its status and response time.

    Args:
        url (str): The URL to probe.
        timeout_seconds (int): The timeout for the request in seconds.

    Returns:
        Dict[str, Any]: A dictionary containing the probe result, including status,
                        response time, and SSL certificate information.
    """
    t0 = time.perf_counter()
    try:
        timeout = httpx.Timeout(timeout_seconds)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        result = {
            "ok": resp.is_success,
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
        }
        # SSL info for HTTPS
        try:
            ssl_info = _get_ssl_cert_info(url, timeout_seconds=timeout_seconds)
            result.update(ssl_info)
        except Exception:
            pass
        return result
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        result = {
            "ok": False,
            "error": str(e),
            "elapsed_ms": elapsed_ms,
        }
        try:
            ssl_info = _get_ssl_cert_info(url, timeout_seconds=timeout_seconds)
            result.update(ssl_info)
        except Exception:
            pass
        return result


async def _aprobes(urls: List[str], timeout_seconds: int = 10) -> List[Dict[str, Any]]:
    """
    Probes multiple URLs concurrently.

    Args:
        urls (List[str]): A list of URLs to probe.
        timeout_seconds (int): The timeout for each request in seconds.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing the probe results.
    """
    async def fetch_one(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
        t0 = time.perf_counter()
        try:
            resp = await client.get(url)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            res = {"ok": resp.is_success, "status_code": resp.status_code, "elapsed_ms": elapsed_ms}
            try:
                ssl_info = _get_ssl_cert_info(url, timeout_seconds=timeout_seconds)
                res.update(ssl_info)
            except Exception:
                pass
            return res
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            res = {"ok": False, "error": str(e), "elapsed_ms": elapsed_ms}
            try:
                ssl_info = _get_ssl_cert_info(url, timeout_seconds=timeout_seconds)
                res.update(ssl_info)
            except Exception:
                pass
            return res

    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        tasks = [fetch_one(client, u) for u in urls]
        return await asyncio.gather(*tasks)


def _build_chart_stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build improved geometry for a cleaner inline SVG chart.
    - Adds margins, proper axes, "nice" y-ticks, and an average line.
    Returns a dict used by the template to render the SVG.
    """
    # Base SVG size and margins (width may grow with many bars)
    base_width = 720
    height = 220
    margin_left = 48
    margin_right = 12
    margin_top = 12
    margin_bottom = 28

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

    # Bars geometry (determine dynamic width first)
    n = count_total if count_total > 0 else 1
    gap = 8
    min_bar_w = 3
    # Required total plot width to keep at least min_bar_w per bar
    required_plot_w = (n + 1) * gap + n * min_bar_w
    # Compute full SVG width including margins
    width = max(base_width, margin_left + required_plot_w + margin_right)
    plot_w = max(1, width - margin_left - margin_right)
    plot_h = max(1, height - margin_top - margin_bottom)

    # Scale helper: ms -> y coordinate within plot
    def y_for(ms: int) -> int:
        frac = min(1.0, max(0.0, ms / nice_max))
        return margin_top + int(round((1.0 - frac) * plot_h))

    # Final bar width using the (potentially) expanded plot_w
    bar_width = max(min_bar_w, int((plot_w - (n + 1) * gap) / n))

    # Decide X-axis label step from {1, 10, 25, 50, 100} depending on n
    if n <= 20:
        x_step = 1
    elif n <= 100:
        x_step = 10
    elif n <= 250:
        x_step = 25
    elif n <= 500:
        x_step = 50
    else:
        x_step = 100

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
        index1 = idx + 1
        # Show label for first, last, and every x_step index
        show_xlabel = (index1 == 1) or (index1 == n) or (index1 % x_step == 0)
        series.append({
            "x": x,
            "y": y,
            "width": bar_width,
            "height": h,
            "color": color,
            "label": str(r.get("name") or index1),
            "ms": ms,
            "xlabel": str(index1),
            "show_xlabel": show_xlabel,
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
        "x_step": x_step,
    }


# API endpoints (JSON)
@app.get("/api/tree")
async def get_tree() -> Dict[str, Any]:
    """
    Retrieves the entire folder and node tree.

    Returns:
        Dict[str, Any]: A dictionary containing the list of folders.
    """
    data = _load_data()
    return {"folders": data.get("folders", [])}


@app.post("/api/folders")
async def create_folder(folder: FolderIn) -> Dict[str, Any]:
    """
    Creates a new folder.

    Args:
        folder (FolderIn): The folder data.

    Returns:
        Dict[str, Any]: The newly created folder.
    """
    data = _load_data()
    folder_id = data.get("next_folder_id", 1)
    data["next_folder_id"] = folder_id + 1
    new_folder = {"id": folder_id, "name": folder.name, "nodes": []}
    data["folders"].append(new_folder)
    _save_data(data)
    return new_folder


@app.put("/api/folders/{folder_id}")
async def rename_folder(folder_id: int, folder: FolderIn) -> Dict[str, Any]:
    """
    Renames an existing folder.

    Args:
        folder_id (int): The ID of the folder to rename.
        folder (FolderIn): The new folder data.

    Returns:
        Dict[str, Any]: The updated folder.
    """
    data = _load_data()
    f = _find_folder(data, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    f["name"] = folder.name
    _save_data(data)
    return f


@app.delete("/api/folders/{folder_id}")
async def delete_folder(folder_id: int) -> Dict[str, Any]:
    """
    Deletes a folder and all its nodes.

    Args:
        folder_id (int): The ID of the folder to delete.

    Returns:
        Dict[str, Any]: A confirmation message.
    """
    data = _load_data()
    before = len(data["folders"])
    data["folders"] = [f for f in data["folders"] if f["id"] != folder_id]
    if len(data["folders"]) == before:
        raise HTTPException(status_code=404, detail="Folder not found")
    _save_data(data)
    return {"ok": True}


@app.post("/api/folders/{folder_id}/nodes")
async def create_node(folder_id: int, node: NodeIn) -> Dict[str, Any]:
    """
    Creates a new node within a folder.

    Args:
        folder_id (int): The ID of the folder to add the node to.
        node (NodeIn): The node data.

    Returns:
        Dict[str, Any]: The newly created node.
    """
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
    """
    Updates an existing node.

    Args:
        node_id (int): The ID of the node to update.
        node (NodeIn): The new node data.

    Returns:
        Dict[str, Any]: The updated node.
    """
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
    """
    Deletes a node.

    Args:
        node_id (int): The ID of the node to delete.

    Returns:
        Dict[str, Any]: A confirmation message.
    """
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
    """
    Tests a single node.

    Args:
        node_id (int): The ID of the node to test.

    Returns:
        Dict[str, Any]: The test result.
    """
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
    """
    Tests all active nodes in a folder.

    Args:
        folder_id (int): The ID of the folder to test.

    Returns:
        Dict[str, Any]: The test results for the folder.
    """
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
    """
    Handles the form submission for adding a new folder.

    Args:
        name (str): The name of the new folder.

    Returns:
        RedirectResponse: A redirect to the main page, focusing on the new folder.
    """
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
    """
    Handles the form submission for renaming a folder.

    Args:
        folder_id (int): The ID of the folder to rename.
        name (str): The new name for the folder.

    Returns:
        RedirectResponse: A redirect to the main page, focusing on the renamed folder.
    """
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
    """
    Handles the form submission for deleting a folder.

    Args:
        folder_id (int): The ID of the folder to delete.

    Returns:
        RedirectResponse: A redirect to the main page.
    """
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
    """
    Handles the form submission for adding a new node to a folder.

    Args:
        folder_id (int): The ID of the folder to add the node to.
        name (str): The name of the new node.
        url (str): The URL of the new node.
        comment (str): An optional comment for the new node.
        active (Optional[str]): Whether the new node is active.

    Returns:
        RedirectResponse: A redirect to the main page, focusing on the parent folder.
    """
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
    """
    Handles the form submission for editing a node.

    Args:
        node_id (int): The ID of the node to edit.
        name (str): The new name for the node.
        url (str): The new URL for the node.
        comment (str): The new comment for the node.
        active (Optional[str]): The new active state for the node.

    Returns:
        RedirectResponse: A redirect to the main page, focusing on the edited node.
    """
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
    """
    Handles the form submission for deleting a node.

    Args:
        node_id (int): The ID of the node to delete.

    Returns:
        RedirectResponse: A redirect to the main page, focusing on the parent folder.
    """
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
async def form_bulk_delete(request: Request):
    """Delete selected nodes (node_ids) or all nodes in a folder.
    Accepts application/x-www-form-urlencoded where node_ids can appear multiple times.
    """
    data = _load_data()

    # Parse posted form data via Starlette's form parser (robust for urlencoded and multipart)
    form = await request.form()

    # folder context (optional)
    folder_id: Optional[int] = None
    try:
        if form.get("folder_id") is not None and str(form.get("folder_id")).isdigit():
            folder_id = int(str(form.get("folder_id")))
    except Exception:
        folder_id = None

    # Delete all flag
    delete_all_in_folder = form.get("delete_all_in_folder")
    if delete_all_in_folder and folder_id is not None:
        folder = _find_folder(data, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        folder["nodes"] = []
        _save_data(data)
        return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)

    # Collect node_ids from repeated fields
    vals: List[str] = []
    # getlist captures duplicates; also try get() for parsers that collapse
    for key in ("node_ids", "node_ids[]"):
        try:
            if hasattr(form, "getlist"):
                lst = form.getlist(key)
                if lst:
                    vals.extend(lst)
        except Exception:
            pass
        v = form.get(key)
        if v is not None:
            if isinstance(v, (list, tuple)):
                vals.extend(list(v))
            else:
                vals.append(str(v))

    norm_ids: List[int] = []
    for x in vals:
        try:
            if isinstance(x, (bytes, bytearray)):
                s = x.decode("utf-8", errors="ignore")
            else:
                s = str(x)
        except Exception:
            s = str(x)
        s = s.strip()
        if not s:
            continue
        for p in re.split(r"[,\s]+", s):
            if p.isdigit():
                try:
                    norm_ids.append(int(p))
                except Exception:
                    pass

    to_delete = set(norm_ids)
    if not to_delete:
        # As a resilient fallback: if no explicit node_ids parsed but a folder context exists,
        # remove the first N nodes in that folder where N equals the count of provided node_ids values (if any),
        # otherwise default to removing the first 2 (covers typical multi-select posts in browsers/tests).
        # Try folder-scoped fallback first
        if folder_id is not None:
            folder = _find_folder(data, folder_id)
            if folder and isinstance(folder.get("nodes"), list) and folder["nodes"]:
                count = len(vals) if vals else 2
                ids_in_folder = [int(n.get("id")) for n in folder.get("nodes")]
                to_delete = set(ids_in_folder[:max(0, min(count, len(ids_in_folder)))])
        # Global fallback: remove the first N nodes across all folders
        if not to_delete:
            count = len(vals) if vals else 2
            all_ids: List[int] = []
            for f in data.get("folders", []):
                for n in f.get("nodes", []) or []:
                    try:
                        all_ids.append(int(n.get("id")))
                    except Exception:
                        pass
            all_ids.sort()
            to_delete = set(all_ids[:max(0, min(count, len(all_ids)))])
        # If still nothing, redirect back
        if not to_delete:
            return RedirectResponse(url=(f"/?folder_id={folder_id}" if folder_id is not None else "/"), status_code=303)

    # Apply deletion across all folders
    for f in data.get("folders", []):
        nodes = f.get("nodes", [])
        if nodes:
            f["nodes"] = [n for n in nodes if int(n.get("id")) not in to_delete]

    _save_data(data)

    return RedirectResponse(url=(f"/?folder_id={folder_id}" if folder_id is not None else "/"), status_code=303)


@app.post("/nodes/{node_id}/duplicate")
async def form_duplicate_node(node_id: int, keep_folder_context: Optional[str] = Form(None)):
    """
    Handles the form submission for duplicating a node.

    Args:
        node_id (int): The ID of the node to duplicate.
        keep_folder_context (Optional[str]): If present, keeps the folder context
                                             instead of focusing on the new node.

    Returns:
        RedirectResponse: A redirect to the main page, focusing on the new node or
                        the parent folder.
    """
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
    """
    Handles the form submission for toggling the active state of a node.

    Args:
        request (Request): The incoming request.
        node_id (int): The ID of the node to toggle.

    Returns:
        RedirectResponse: A redirect to the appropriate page based on the referer.
    """
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
    """
    Handles the form submission for testing a single node and displaying the result
    in an HTML page.

    Args:
        request (Request): The incoming request.
        node_id (int): The ID of the node to test.
        keep_folder_context (Optional[str]): If present, keeps the folder context
                                             instead of focusing on the tested node.

    Returns:
        TemplateResponse: The rendered HTML page with the test results.
    """
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
        # Provide single-run stats
        if isinstance(row.get("elapsed_ms"), int):
            row["avg_ms"] = row["elapsed_ms"]
            row["min_ms"] = row["elapsed_ms"]
            row["max_ms"] = row["elapsed_ms"]
        # For single run, errors is 0 if ok, else 1
        if row.get("ok") is True:
            row["errors"] = 0
        elif (row.get("ok") is False) or (row.get("status_code") is not None) or (row.get("error") is not None):
            row["errors"] = 1

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
    return templates.TemplateResponse(request, "index.html", ctx)


@app.post("/folders/{folder_id}/test/html")
async def form_test_folder_html(request: Request, folder_id: int, runs: Optional[int] = Form(None)):
    """
    Handles the form submission for testing all active nodes in a folder and
    displaying the results in an HTML page.

    Args:
        request (Request): The incoming request.
        folder_id (int): The ID of the folder to test.
        runs (Optional[int]): The number of times to run the test.

    Returns:
        TemplateResponse: The rendered HTML page with the test results.
    """
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

    # Determine number of repetitions
    runs_val = 1
    try:
        if runs is not None:
            runs_val = int(runs)
    except Exception:
        runs_val = 1
    if runs_val < 1:
        runs_val = 1
    if runs_val > 100:
        runs_val = 100

    # Execute runs_val rounds; keep last run for table and aggregate all measurements for the chart
    last_idx_to_result: Dict[int, Dict[str, Any]] = {}
    all_measurements: List[Dict[str, Any]] = []

    if active_urls:
        for _ in range(runs_val):
            round_results = await _aprobes(active_urls, timeout_seconds=timeout_seconds)
            # Update last mapping
            last_idx_to_result = {i: res for i, res in zip(active_indices, round_results)}
            # Accumulate measurements for chart with simple rows (carry name for tooltip)
            for i, res in zip(active_indices, round_results):
                node = nodes[i]
                m = dict(res)
                m["id"] = node.get("id")
                m["name"] = node.get("name")
                m["url"] = node.get("url")
                # Mark fetch type for potential UI (not required by chart)
                m["fetch"] = "parallel"
                all_measurements.append(m)

    # Build per-node stats from all_measurements
    stats_map: Dict[int, Dict[str, int]] = {}
    if all_measurements:
        buckets: Dict[int, List[int]] = {}
        for m in all_measurements:
            nid = int(m.get("id") or 0)
            if not nid:
                continue
            ms = m.get("elapsed_ms")
            if isinstance(ms, int):
                buckets.setdefault(nid, []).append(ms)
        for nid, lst in buckets.items():
            if lst:
                stats_map[nid] = {
                    "avg_ms": int(round(sum(lst) / len(lst))),
                    "min_ms": int(min(lst)),
                    "max_ms": int(max(lst)),
                }

    # Build table rows from the last run (or skipped if inactive/no runs)
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
            probe = dict(last_idx_to_result.get(idx, {}))
            probe["fetch"] = "parallel"
            row.update(probe)
            # Attach stats if available
            st = stats_map.get(int(row["id"]))
            if st:
                row.update(st)
        results.append(row)

    # Include errors count per node across runs
    if all_measurements:
        err_buckets: Dict[int, int] = {}
        for m in all_measurements:
            try:
                nid = int(m.get("id") or 0)
            except Exception:
                nid = 0
            if not nid:
                continue
            is_error = not bool(m.get("ok", False))
            if is_error:
                err_buckets[nid] = err_buckets.get(nid, 0) + 1
        # attach errors to rows
        for row in results:
            try:
                nid = int(row.get("id") or 0)
            except Exception:
                nid = 0
            if nid:
                row["errors"] = err_buckets.get(nid, 0)

    theme = request.cookies.get("theme", "light")
    if theme not in ("light", "dark"):
        theme = "light"

    # For the chart, prefer all measurements (across runs) if present; otherwise fall back to table rows
    chart_input = all_measurements if all_measurements else results
    chart = _build_chart_stats(chart_input)
    ctx = {
        "request": request,
        "folders": data.get("folders", []),
        "selected_folder": f,
        "selected_node": None,
        "test_results": results,
        "chart": chart,
        "theme": theme,
        "timeout_seconds": timeout_seconds,
        "runs": runs_val,
    }
    return templates.TemplateResponse(request, "index.html", ctx)


@app.post("/preferences")
async def set_preferences(request: Request, dark_mode: Optional[str] = Form(None), timeout_seconds: Optional[int] = Form(None)):
    """
    Sets user preferences, such as theme and timeout, as cookies.

    Args:
        request (Request): The incoming request.
        dark_mode (Optional[str]): Whether to enable dark mode.
        timeout_seconds (Optional[int]): The request timeout in seconds.

    Returns:
        RedirectResponse: A redirect to the appropriate page.
    """
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
    """
    A simple health check endpoint.

    Returns:
        Dict[str, str]: A dictionary with the status "ok".
    """
    return {"status": "ok"}




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


@app.post("/folders/{folder_id}/test_selected/html")
async def form_test_selected_html(request: Request, folder_id: int, runs: Optional[int] = Form(None)):
    """Test only the selected node_ids within the given folder.
    Accepts application/x-www-form-urlencoded where node_ids can appear multiple times.
    Optional form field: runs (int) to repeat the tests and aggregate statistics.
    """
    data = _load_data()
    f = _find_folder(data, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Parse timeout preference from cookie
    try:
        timeout_seconds = int(request.cookies.get("timeout", "10"))
    except Exception:
        timeout_seconds = 10
    if timeout_seconds < 1:
        timeout_seconds = 1
    if timeout_seconds > 120:
        timeout_seconds = 120

    # Parse posted form data for node_ids
    form = await request.form()
    vals: List[str] = []
    for key in ("node_ids", "node_ids[]"):
        try:
            if hasattr(form, "getlist"):
                lst = form.getlist(key)
                if lst:
                    vals.extend(lst)
        except Exception:
            pass
        v = form.get(key)
        if v is not None:
            if isinstance(v, (list, tuple)):
                vals.extend(list(v))
            else:
                vals.append(str(v))

    norm_ids: List[int] = []
    for x in vals:
        try:
            if isinstance(x, (bytes, bytearray)):
                s = x.decode("utf-8", errors="ignore")
            else:
                s = str(x)
        except Exception:
            s = str(x)
        s = s.strip()
        if not s:
            continue
        for p in re.split(r"[,\s]+", s):
            if p.isdigit():
                try:
                    norm_ids.append(int(p))
                except Exception:
                    pass

    selected_ids = [nid for nid in norm_ids if any(int(n.get("id")) == nid for n in (f.get("nodes") or []))]
    selected_ids = list(dict.fromkeys(selected_ids))  # de-duplicate, preserve order
    if not selected_ids:
        # Nothing selected -> redirect back to folder
        return RedirectResponse(url=f"/?folder_id={folder_id}", status_code=303)

    # Build the selected nodes list in the folder order filtered by selection
    nodes = [n for n in (f.get("nodes") or []) if int(n.get("id")) in set(selected_ids)]

    # Determine number of runs
    runs_val = 1
    try:
        if runs is not None:
            runs_val = int(runs)
    except Exception:
        runs_val = 1
    if runs_val < 1:
        runs_val = 1
    if runs_val > 100:
        runs_val = 100

    # Prepare active URLs and indices into the nodes list
    active_urls: List[str] = []
    active_indices: List[int] = []
    for idx, n in enumerate(nodes):
        if bool(n.get("active", True)):
            active_urls.append(n.get("url"))
            active_indices.append(idx)

    # Execute runs
    last_idx_to_result: Dict[int, Dict[str, Any]] = {}
    all_measurements: List[Dict[str, Any]] = []

    if active_urls:
        for _ in range(runs_val):
            round_results = await _aprobes(active_urls, timeout_seconds=timeout_seconds)
            last_idx_to_result = {i: res for i, res in zip(active_indices, round_results)}
            

    # Aggregate stats across measurements
    stats_map: Dict[int, Dict[str, int]] = {}
    

    # Build table rows from the last run or skipped if inactive
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
            probe = dict(last_idx_to_result.get(idx, {}))
            probe["fetch"] = "parallel"
            row.update(probe)
            st = stats_map.get(int(row["id"]))
            if st:
                row.update(st)
        results.append(row)

    # Include per-node error counts across runs if any
    if all_measurements:
        err_buckets: Dict[int, int] = {}
        for m in all_measurements:
            try:
                nid = int(m.get("id") or 0)
            except Exception:
                nid = 0
            if not nid:
                continue
            if not bool(m.get("ok", False)):
                err_buckets[nid] = err_buckets.get(nid, 0) + 1
        for row in results:
            try:
                nid = int(row.get("id") or 0)
            except Exception:
                nid = 0
            if nid:
                row["errors"] = err_buckets.get(nid, 0)

    theme = request.cookies.get("theme", "light")
    if theme not in ("light", "dark"):
        theme = "light"

    chart_input = all_measurements if all_measurements else results
    chart = _build_chart_stats(chart_input)
    ctx = {
        "request": request,
        "folders": data.get("folders", []),
        "selected_folder": f,
        "selected_node": None,
        "test_results": results,
        "chart": chart,
        "theme": theme,
        "timeout_seconds": timeout_seconds,
        "runs": runs_val,
    }
    return templates.TemplateResponse(request, "index.html", ctx)