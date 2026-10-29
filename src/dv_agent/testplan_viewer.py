"""Small loopback-only viewer for rendering saved Markdown from a report button."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_RUN_DIRECTORIES = 32768
MAX_PLANS = 32768


def discover_testplans(root: Path) -> dict[str, Path]:
    """Find generated plans beneath one selected runs directory."""
    found: dict[str, Path] = {}
    visited = 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        visited += 1
        if visited > MAX_RUN_DIRECTORIES or len(found) >= MAX_PLANS:
            break
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(parent) / d).is_symlink())
        if "testplan_doc.md" not in files and "testplan_doc.json" not in files:
            continue
        plan = Path(parent)
        plan_id = plan.relative_to(root).as_posix()
        try:
            _check_artifacts(plan)
        except ValueError:
            continue
        found[plan_id] = plan
    return dict(sorted(found.items()))


def _check_artifacts(out: Path) -> None:
    for name in ("testplan_doc.md", "testplan_doc.html", "testplan_doc.json"):
        path = out / name
        if path.resolve().parent != out:
            raise ValueError(f"{name} must be inside the selected run directory")
        if path.exists() and path.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError(f"{name} exceeds the viewer's 16 MiB limit")


def create_report_server(out: Path, port: int = 8765) -> HTTPServer:
    """Bind a viewer for a selected run or runs directory; caller owns it."""
    from .pipeline import render_testplan

    if not 0 <= port <= 65535:
        raise ValueError("viewer port must be between 0 and 65535")
    out = out.resolve()
    if not out.is_dir():
        raise ValueError(f"testplan runs directory not found: {out}")
    selected_run = (out / "testplan_doc.md").is_file() or (out / "testplan_doc.json").is_file()
    root = out.parent if selected_run else out
    initial = out.relative_to(root).as_posix() if selected_run else None
    if selected_run:
        _check_artifacts(out)
        render_testplan(out)

    def catalog() -> dict[str, Path]:
        return discover_testplans(root)

    def selected(path: str) -> tuple[str | None, Path | None]:
        plans = catalog()
        query = parse_qs(urlsplit(path).query, keep_blank_values=True)
        if "plan" in query:
            values = query["plan"]
            if len(values) != 1 or values[0] not in plans:
                raise ValueError("unknown testplan selection")
            plan_id = values[0]
        else:
            plan_id = initial if initial in plans else next(iter(plans), None)
        return plan_id, plans.get(plan_id)

    class Handler(BaseHTTPRequestHandler):
        server_version = "DVTestplanViewer/0.1"
        sys_version = ""

        def log_message(self, format: str, *args) -> None:
            pass

        def _reply(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._reply(status, json.dumps({"error": message}).encode(), "application/json; charset=utf-8")

        def _allowed_host(self) -> bool:
            actual_port = self.server.server_port
            allowed = {f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"}
            if actual_port == 80:
                allowed.update({"127.0.0.1", "localhost"})
            if self.headers.get("Host") not in allowed:
                self._error(403, "Use the local viewer URL printed by dv-agent")
                return False
            return True

        def do_GET(self) -> None:
            if not self._allowed_host():
                return
            url = urlsplit(self.path)
            if url.path == "/plans":
                try:
                    plan_id, _ = selected(self.path)
                    self._reply(200, json.dumps(dict(selected=plan_id,
                        plans=[dict(id=key, label=key) for key in catalog()])).encode(),
                        "application/json; charset=utf-8")
                except ValueError as exc:
                    self._error(404, str(exc))
                return
            routes = {"/": "testplan_doc.html", "/testplan_doc.html": "testplan_doc.html",
                      "/testplan_doc.md": "testplan_doc.md"}
            name = routes.get(url.path)
            if name is None:
                self._error(404, "Not found")
                return
            try:
                _, run = selected(self.path)
                if run is None:
                    self._reply(200, render_html("# Testplans\n\n_No generated testplans found in this runs directory._\n").encode(),
                                "text/html; charset=utf-8")
                    return
                _check_artifacts(run)
                if name == "testplan_doc.html":
                    render_testplan(run)
                data = (run / name).read_bytes()
                mime = "text/html" if name.endswith(".html") else "text/plain"
                self._reply(200, data, mime + "; charset=utf-8")
            except FileNotFoundError:
                self._error(404, "Report file not found")
            except ValueError as exc:
                self._error(404, str(exc))
            except OSError as exc:
                self._error(400, str(exc))

        def do_POST(self) -> None:
            if not self._allowed_host():
                return
            if urlsplit(self.path).path != "/render":
                self._error(404, "Not found")
                return
            # A custom header plus same-origin check prevents another website
            # from driving local writes. No CORS or arbitrary paths/commands.
            origin = self.headers.get("Origin")
            if (self.headers.get("X-Testplan-Render") != "1"
                    or origin is not None and origin != f"http://{self.headers['Host']}"):
                self._error(403, "Render requests must come from this viewer")
                return
            if self.headers.get("Content-Length", "0") != "0" or self.headers.get("Transfer-Encoding"):
                self._error(400, "Render requests do not accept a body")
                self.close_connection = True
                return
            try:
                _, run = selected(self.path)
                if run is None:
                    raise ValueError("no generated testplans found")
                _check_artifacts(run)
                render_testplan(run)
                self._reply(200, (run / "testplan_doc.html").read_bytes(), "text/html; charset=utf-8")
            except (OSError, ValueError, KeyError) as exc:
                self._error(400, str(exc))

    try:
        from .html_report import render_html
        return HTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        raise ValueError(f"Cannot start testplan viewer on port {port}: {exc.strerror}") from None
