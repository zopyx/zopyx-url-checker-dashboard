from __future__ import annotations

# Thin wrapper to expose the FastAPI app from the repository's main.py
# as endpoint_pulse.app:app for packaging/entry points.

try:
    # Reuse the existing app defined in the project root.
    from main import app  # type: ignore
except Exception:  # fallback if main is not available
    from fastapi import FastAPI
    app = FastAPI(title="Endpoint Pulse")

            
            
            
