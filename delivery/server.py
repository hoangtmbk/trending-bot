from __future__ import annotations
import http.server
import logging
import sys
from pathlib import Path
from functools import partial

logger = logging.getLogger(__name__)


def serve_dashboard(serve_dir: str, port: int = 8080):
    serve_path = Path(serve_dir)
    if not serve_path.exists():
        logger.error(f"Dashboard directory not found: {serve_dir}")
        sys.exit(1)

    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(serve_path))
    with http.server.HTTPServer(("", port), handler) as server:
        logger.info(f"Dashboard serving at http://localhost:{port}")
        print(f"Dashboard serving at http://localhost:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Dashboard server stopped")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Directory to serve")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve_dashboard(args.dir, args.port)
