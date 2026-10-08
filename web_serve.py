#!/usr/bin/env python3
"""web_serve.py — serve the browser front end from this folder.

`katana web` lands here. It starts a plain HTTP server on localhost and opens the page.

Why a server rather than just opening the file. The page fetches Katana's own `.py`
modules and its reference set, and a browser refuses those requests from a `file://`
origin -- so double-clicking index.html gets a page that loads and then cannot do
anything, which is worse than one that does not load. One command avoids that, and the
constraint is worth stating rather than letting someone discover it.

Nothing leaves the machine: the server is bound to the loopback interface, and the audit
itself runs inside the browser through Pyodide. Pyodide's own runtime comes from a CDN
on first load, which is the one outbound request; after that the browser caches it and
the page works offline.
"""
import os
import sys
import webbrowser
from functools import partial

HERE = os.path.dirname(os.path.abspath(__file__))

# Only what the page needs, and nothing else. A plain SimpleHTTPRequestHandler on the
# repository root would also serve the private working files of anybody who put some
# here, which is not a thing a convenience command should do.
SERVE = (
    "ui/web/index.html",
    "ui/web/index.js",
    "core/__init__.py",
    "core/hashing.py",
    "core/lock.py",
    "core/parts.py",
    "core/result.py",
    "kagami/kg_parse.py",
    "kagami/kg_refs.py",
    "kagami/kg_seedmatch.py",
    "kagami/kg_identify.py",
    "kagami/kg_audit.py",
    "kagami/kg_bridge.py",
    "kagami/refs/reference_parts.tsv",
    "kagami/refs/reference_parts.fasta",
    "kagami/genomes/MG1655_ecoli_NC_000913.3.fna",
)

_TYPES = {".html": "text/html; charset=utf-8",
          ".js": "text/javascript; charset=utf-8",
          ".py": "text/plain; charset=utf-8",
          ".tsv": "text/plain; charset=utf-8",
          ".fasta": "text/plain; charset=utf-8",
          ".fna": "text/plain; charset=utf-8"}


def _handler_class():
    from http.server import BaseHTTPRequestHandler

    allowed = set(SERVE)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass                      # a server log is noise a student cannot act on

        def do_GET(self):
            rel = self.path.split("?", 1)[0].lstrip("/")
            # index.html references index.js relatively, so the browser asks for
            # /index.js. Both page files are served from the root rather than from
            # ui/web/, so the published site and this server have the same shape.
            if rel in ("", "index.html"):
                rel = "ui/web/index.html"
            elif rel == "index.js":
                rel = "ui/web/index.js"
            if rel not in allowed:
                self.send_error(404, "not served")
                return
            path = os.path.join(HERE, rel)
            if not os.path.isfile(path):
                self.send_error(404, "missing: " + rel)
                return
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type",
                             _TYPES.get(os.path.splitext(rel)[1],
                                        "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            # Pyodide needs these to use the faster threaded runtime where the browser
            # offers it. Harmless when it does not.
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def missing_files():
    """Everything the page needs that is not here. Empty means it will work."""
    return [p for p in SERVE if not os.path.isfile(os.path.join(HERE, p))]


def _server_class():
    """An HTTPServer that does not look up its own hostname.

    http.server's server_bind() calls socket.getfqdn() on the bind address, which is a
    REVERSE DNS lookup. On a machine whose resolver is slow to answer for the loopback
    address -- a school network behind a captive portal, a laptop on a VPN -- that
    blocks for several seconds before the socket starts answering, so the page appears to
    load and then fail. Measured here: the first four requests timed out and the fifth
    succeeded.

    The name is only used in the Server: header, so there is nothing to lose by not
    asking.
    """
    from http.server import HTTPServer

    class LocalServer(HTTPServer):
        def server_bind(self):
            import socketserver
            socketserver.TCPServer.server_bind(self)
            host, port = self.server_address[:2]
            self.server_name = "localhost"
            self.server_port = port

    return LocalServer


def serve(port=8731, open_browser=True, once=False):
    """Serve on localhost. Returns an exit code."""
    HTTPServer = _server_class()

    missing = missing_files()
    if missing:
        print("These files the page needs are not here:")
        for m in missing:
            print("  " + m)
        print("\nIf you unzipped the bundle, take a fresh copy of it.")
        return 2

    for attempt in range(port, port + 20):
        try:
            httpd = HTTPServer(("127.0.0.1", attempt), _handler_class())
            break
        except OSError:
            continue
    else:
        print("Could not find a free port between %d and %d." % (port, port + 19))
        return 2

    url = "http://127.0.0.1:%d/" % httpd.server_address[1]
    print("katana-kagami is running in your browser at")
    print()
    print("    " + url)
    print()
    print("Nothing you check there is uploaded: the audit runs inside the browser.")
    print("Press Ctrl-C here when you are finished.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        if once:
            httpd.handle_request()
        else:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    port = 8731
    open_browser = True
    for i, tok in enumerate(argv):
        if tok == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
        elif tok == "--no-open":
            open_browser = False
    return serve(port=port, open_browser=open_browser)


if __name__ == "__main__":
    sys.exit(main())
