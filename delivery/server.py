from __future__ import annotations
import http.server
import json
import logging
import mimetypes
import re
import socketserver
from pathlib import Path
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PATH_RE = re.compile(r"^/(\d{4}-\d{2}-\d{2})(/.*)?$")


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    base_dir: Path = Path("data")

    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _available_dates(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        dates: list[str] = []
        for child in self.base_dir.iterdir():
            if not child.is_dir() or not DATE_RE.match(child.name):
                continue
            if (child / "reports" / "dashboard" / "index.html").exists():
                dates.append(child.name)
        dates.sort(reverse=True)
        return dates

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_empty(self) -> None:
        html = (
            b"<!doctype html><meta charset=utf-8><title>AI Trending Bot</title>"
            b"<body style=\"font-family:-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;padding:2rem\">"
            b"<h1 style=\"color:#58a6ff\">AI Trending Bot</h1>"
            b"<p>No dashboards generated yet. Run <code>python run.py</code> to create one.</p>"
            b"</body>"
        )
        self._send(200, html, "text/html; charset=utf-8")

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)

        if path == "/api/dates":
            body = json.dumps({"dates": self._available_dates()}).encode("utf-8")
            self._send(200, body, "application/json", {"Cache-Control": "no-store"})
            return

        if path in ("/", ""):
            dates = self._available_dates()
            if not dates:
                self._send_empty()
                return
            self._redirect(f"/{dates[0]}/")
            return

        if path == "/favicon.ico":
            self._send(404, b"", "text/plain")
            return

        m = PATH_RE.match(path)
        if not m:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return

        date = m.group(1)
        rest = m.group(2) or ""
        date_root = self.base_dir / date / "reports" / "dashboard"
        if not date_root.exists():
            self._send(404, b"Date not found", "text/plain; charset=utf-8")
            return

        if rest == "":
            self._redirect(f"/{date}/")
            return

        rel = rest.lstrip("/") or "index.html"
        if ".." in rel.split("/"):
            self._send(400, b"Bad request", "text/plain; charset=utf-8")
            return

        file_path = date_root / rel
        if file_path.is_dir():
            file_path = file_path / "index.html"

        try:
            resolved = file_path.resolve()
            resolved.relative_to(date_root.resolve())
        except (ValueError, OSError):
            self._send(400, b"Bad request", "text/plain; charset=utf-8")
            return

        if not resolved.is_file():
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return

        ctype, _ = mimetypes.guess_type(str(resolved))
        if ctype is None:
            ctype = "application/octet-stream"

        try:
            body = resolved.read_bytes()
        except OSError:
            self._send(500, b"Internal error", "text/plain; charset=utf-8")
            return

        self._send(200, body, ctype)


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve_dashboard(data_dir: str = "data", port: int = 8080) -> None:
    DashboardHandler.base_dir = Path(data_dir)
    with _ThreadingServer(("", port), DashboardHandler) as server:
        msg = f"Dashboard serving at http://localhost:{port} (data dir: {data_dir})"
        logger.info(msg)
        print(msg)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Dashboard server stopped")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Serve all trending-bot dashboards with date selector")
    parser.add_argument("--data-dir", default="data", help="Root data directory (default: data)")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve_dashboard(args.data_dir, args.port)
