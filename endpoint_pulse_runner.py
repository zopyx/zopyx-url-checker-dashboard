def main():
    """Run the Endpoint Pulse app with uvicorn.

    This is a simple entry point so that installed users can run:
        endpoint-pulse
    """
    import uvicorn
    # Allow overriding host/port via environment variables
    import os
    host = os.environ.get("ENDPOINT_PULSE_HOST", "127.0.0.1")
    port = int(os.environ.get("ENDPOINT_PULSE_PORT", "8000"))
    reload = os.environ.get("ENDPOINT_PULSE_RELOAD", "0") in ("1", "true", "True")
    uvicorn.run("main:app", host=host, port=port, reload=reload)
