# This file is part of the Endpoint Pulse project.
#
# Copyright (c) 2025, Andreas Jung
#
# This software is released under the WTFPL, Version 2.0.
# See the LICENSE file for more details.

def main():
    """Run the Endpoint Pulse app with uvicorn.

    This is a simple entry point so that installed users can run:
        endpoint-pulse [--host 0.0.0.0] [--port 8000] [--reload]

    Precedence of configuration:
    1) CLI args (--host/--port/--reload)
    2) Environment variables ENDPOINT_PULSE_HOST/PORT/RELOAD
    3) Defaults: host=127.0.0.1, port=8000, reload=False
    """
    import os
    import argparse
    import uvicorn

    # Defaults (lowest precedence)
    default_host = "127.0.0.1"
    default_port = 8000
    default_reload = False

    # Environment overrides (middle precedence)
    env_host = os.environ.get("ENDPOINT_PULSE_HOST")
    env_port = os.environ.get("ENDPOINT_PULSE_PORT")
    env_reload = os.environ.get("ENDPOINT_PULSE_RELOAD")

    # CLI (highest precedence)
    parser = argparse.ArgumentParser(prog="endpoint-pulse", description="Run Endpoint Pulse (FastAPI) with uvicorn")
    parser.add_argument("--host", "-H", dest="host", help=f"Host/IP to bind (default: %(default)s)", default=env_host or default_host)
    parser.add_argument("--port", "-p", dest="port", type=int, help=f"Port to bind (default: %(default)s)", default=int(env_port) if env_port else default_port)
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (overrides env)")
    args = parser.parse_args()

    # Reload: CLI flag wins; otherwise derive from env
    if args.reload:
        reload = True
    else:
        reload = str(env_reload).lower() in ("1", "true", "yes", "on")

    uvicorn.run("endpoint_pulse.app:app", host=args.host, port=args.port, reload=reload)

if __name__ == "__main__":
    main()
