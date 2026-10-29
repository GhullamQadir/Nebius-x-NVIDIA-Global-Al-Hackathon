"""Single-origin dev server for local E2E testing.

Serves the static Odysseus frontend from ``nexora/frontend`` and reverse-proxies
the FastAPI backend prefixes (``/api/``, ``/docs``, ``/redoc``, ``/openapi.json``)
to a local uvicorn process, so the browser only ever needs one origin.

Usage:
    python scripts/dev_server.py --port 3000 --api-port 8001

Stdlib only. No application code is modified or imported.
"""
from __future__ import annotations

import argparse
import http.server
import socketserver
import threading
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "nexora" / "frontend"
PROXY_PREFIXES = ("/api/", "/docs", "/redoc", "/openapi.json")
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


class DevHandler(http.server.SimpleHTTPRequestHandler):
    api_port: int = 8001
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _is_proxy_path(self, path: str) -> bool:
        return any(path == p or path.startswith(p) for p in PROXY_PREFIXES)

    def _proxy(self):
        upstream = f"http://127.0.0.1:{self.api_port}{self.path}"
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() != "host"
        }
        req = urllib.request.Request(
            upstream, data=body, headers=headers, method=self.command
        )
        try:
            resp = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as err:
            resp = err
        except (urllib.error.URLError, ConnectionError, TimeoutError) as err:
            payload = f'{{"detail":"upstream unreachable: {err}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        with resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            is_sse = "text/event-stream" in content_type

            resp_headers = [
                (k, v)
                for k, v in resp.headers.items()
                if k.lower() not in HOP_BY_HOP
            ]

            if is_sse:
                self.send_response(status)
                for key, value in resp_headers:
                    if key.lower() != "content-length":
                        self.send_header(key, value)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                while True:
                    chunk = resp.read(64)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (ConnectionError, BrokenPipeError):
                        break
                return

            payload = resp.read()
            self.send_response(status)
            for key, value in resp_headers:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

    def _serve_static(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        rel = path.lstrip("/") or "index.html"
        target = (FRONTEND_DIR / rel).resolve()
        if not str(target).startswith(str(FRONTEND_DIR.resolve())):
            self.send_error(403)
            return
        if not target.is_file():
            if "." not in Path(rel).name:
                target = FRONTEND_DIR / "index.html"
            else:
                self.send_error(404)
                return
        try:
            payload = target.read_bytes()
        except OSError:
            self.send_error(404)
            return
        ctype = self.guess_type(str(target))
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self' http://127.0.0.1:* http://localhost:*; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
            "img-src 'self' data: https:; "
            "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
            "frame-ancestors 'self';"
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _dispatch(self):
        if self._is_proxy_path(self.path.split("?", 1)[0]):
            self._proxy()
        else:
            self._serve_static()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = (
        _dispatch
    )


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--api-port", type=int, default=8001)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    DevHandler.api_port = args.api_port
    server = Server(("127.0.0.1", args.port), DevHandler)
    server.verbose = args.verbose
    print(
        f"dev server: http://127.0.0.1:{args.port} -> static {FRONTEND_DIR}, "
        f"/api/* -> 127.0.0.1:{args.api_port}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
