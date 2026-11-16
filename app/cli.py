"""An offline-help launcher for the optional loopback API server."""

import argparse


def server_main() -> int:
    parser = argparse.ArgumentParser(description="Start the local Notion2API server")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "::1"],
                        help="Loopback bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run("app.server:app", host=args.host, port=args.port)
    return 0
