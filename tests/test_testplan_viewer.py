import json
import io
import shutil
import subprocess
from http.client import HTTPResponse
from types import SimpleNamespace

import pytest

from dv_agent.cli import main
from dv_agent.report.html_report import _CONTROLS_SCRIPT, render_html
from dv_agent.report.testplan_viewer import create_report_server


@pytest.fixture
def viewer(tmp_path, monkeypatch):
    out = tmp_path / "run"
    out.mkdir()
    (out / "testplan_doc.md").write_text("# Testplan\n\nBefore edits.\n")
    (out / "testplan_doc.json").write_text('{"preserved": true}')
    def fail(*args, **kwargs):
        raise AssertionError("the viewer must not call a model")
    monkeypatch.setattr("dv_agent.core.llm.MetaClient.structured", fail)
    # Exercise real HTTP parsing/handling without opening sockets: some coding
    # environments prohibit even loopback sockets, and unit tests stay offline.
    def server(address, handler):
        assert address[0] == "127.0.0.1"
        return SimpleNamespace(server_port=8765, RequestHandlerClass=handler)
    monkeypatch.setattr("dv_agent.report.testplan_viewer.HTTPServer", server)
    server = create_report_server(out, port=0)
    return out, server


def request(server, method="GET", path="/", headers=None):
    headers = {"Host": f"127.0.0.1:{server.server_port}", **(headers or {})}
    raw = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    output = io.BytesIO()
    class Connection:
        def makefile(self, *args, **kwargs):
            return io.BytesIO(raw.encode())
        def sendall(self, data):
            output.write(data)
    server.RequestHandlerClass(Connection(), ("127.0.0.1", 1234), server)
    class ResponseConnection:
        def makefile(self, *args, **kwargs):
            return io.BytesIO(output.getvalue())
    response = HTTPResponse(ResponseConnection())
    response.begin()
    return response.status, response.read().decode(), dict(response.getheaders())


def test_render_button_reads_edited_markdown_and_saves_identical_html(viewer):
    out, server = viewer
    status, body, headers = request(server)
    assert status == 200 and 'id="render-testplan"' in body
    assert headers["Cache-Control"] == "no-store"
    edited = "# Edited testplan\n\n| Register | Access |\n|---|---|\n| CTRL | RW |\n"
    (out / "testplan_doc.md").write_text(edited)
    code, rendered, _ = request(server, "POST", "/render", {"X-Testplan-Render": "1"})
    assert code == 200 and "<h1>Edited testplan</h1>" in rendered
    assert rendered == render_html(edited) == (out / "testplan_doc.html").read_text()
    assert (out / "testplan_doc.md").read_text() == edited
    assert (out / "testplan_doc.json").read_text() == '{"preserved": true}'
    assert request(server, path="/testplan_doc.md")[1] == edited


def test_viewer_serves_only_report_files_and_rejects_foreign_write_requests(viewer):
    out, server = viewer
    original = (out / "testplan_doc.html").read_text()
    for path in ("/.env", "/testplan_doc.json", "/../.env", "/?path=../../.env"):
        status, body, _ = request(server, path=path)
        if path.startswith("/?"):
            assert status == 200 and body == original  # Query cannot choose a source.
        else:
            assert status == 404
    assert request(server, "POST", "/render")[0] == 403
    assert request(server, "POST", "/render", {"X-Testplan-Render": "1", "Origin": "https://example.org"})[0] == 403
    assert request(server, headers={"Host": "foreign.invalid"})[0] == 403
    assert (out / "testplan_doc.html").read_text() == original


def test_missing_markdown_reports_an_error_and_retains_previous_html(viewer):
    out, server = viewer
    original = (out / "testplan_doc.html").read_text()
    (out / "testplan_doc.md").unlink()
    (out / "testplan_doc.json").unlink()
    status, body, _ = request(server, "POST", "/render", {"X-Testplan-Render": "1"})
    assert status == 400 and "no generated testplans" in json.loads(body)["error"]
    assert (out / "testplan_doc.html").read_text() == original


def test_selector_lists_sibling_and_new_plans_and_renders_only_selected(viewer):
    out, server = viewer
    other = out.parent / "other"
    other.mkdir()
    (other / "testplan_doc.md").write_text("# Other plan\n\nFirst draft.\n")
    catalog = json.loads(request(server, path="/plans")[1])
    assert catalog["selected"] == "run"
    assert [p["id"] for p in catalog["plans"]] == ["other", "run"]
    assert json.loads(request(server, path="/plans?plan=other")[1])["selected"] == "other"
    assert "<h1>Other plan</h1>" in request(server, path="/?plan=other")[1]
    original = (out / "testplan_doc.html").read_text()
    (other / "testplan_doc.md").write_text("# Other plan\n\nEdited only this plan.\n")
    assert "Edited only this plan." in request(server, "POST", "/render?plan=other", {"X-Testplan-Render": "1"})[1]
    assert (other / "testplan_doc.html").read_text() == render_html((other / "testplan_doc.md").read_text())
    assert (out / "testplan_doc.html").read_text() == original
    assert request(server, path="/?plan=../../etc")[0] == 404
    assert request(server, "POST", "/render?plan=../../etc", {"X-Testplan-Render": "1"})[0] == 400
    fresh = out.parent / "fresh"
    fresh.mkdir()
    (fresh / "testplan_doc.md").write_text("# Fresh plan\n")
    assert "fresh" in [p["id"] for p in json.loads(request(server, path="/plans")[1])["plans"]]


def test_runs_root_opens_first_plan_and_nested_plans(tmp_path, monkeypatch):
    from dv_agent.report import testplan_viewer
    root = tmp_path / "runs"
    nested = root / "design" / "feature"
    nested.mkdir(parents=True)
    (nested / "testplan_doc.md").write_text("# Nested\n")
    monkeypatch.setattr(testplan_viewer, "HTTPServer", lambda address, handler: SimpleNamespace(
        server_port=8765, RequestHandlerClass=handler))
    server = create_report_server(root, port=0)
    assert "<h1>Nested</h1>" in request(server)[1]
    assert json.loads(request(server, path="/plans")[1])["plans"] == [
        {"id": "design/feature", "label": "design/feature"}]


def test_root_view_refreshes_a_previous_html_copy(viewer):
    out, server = viewer
    (out / "testplan_doc.html").write_text("<html>Old viewer without selector</html>")
    status, body, _ = request(server)
    assert status == 200 and 'id="testplan-select"' in body
    assert body == (out / "testplan_doc.html").read_text()


def test_viewer_rejects_report_symlinks_outside_the_selected_run(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    target = tmp_path / "private.md"
    target.write_text("private")
    (out / "testplan_doc.md").symlink_to(target)
    with pytest.raises(ValueError, match="inside the selected run"):
        create_report_server(out, port=0)


def test_cli_serve_prints_the_viewer_url_without_model_calls(tmp_path, monkeypatch, capsys):
    from dv_agent.report import testplan_viewer
    class Server:
        server_port = 9876
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def serve_forever(self, **kwargs):
            raise KeyboardInterrupt
    monkeypatch.setattr(testplan_viewer, "create_report_server", lambda out, port: Server())
    assert main(["render-testplan", "--out", str(tmp_path), "--serve", "--port", "9876"]) == 0
    assert json.loads(capsys.readouterr().out)["url"] == "http://127.0.0.1:9876/"


def test_cli_serve_defaults_to_repository_runs_directory(monkeypatch, capsys):
    from dv_agent import cli
    from dv_agent.report import testplan_viewer
    chosen = []
    class Server:
        server_port = 8765
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def serve_forever(self, **kwargs):
            raise KeyboardInterrupt
    monkeypatch.setattr(testplan_viewer, "create_report_server",
                        lambda out, port: chosen.append(out) or Server())
    assert main(["render-testplan", "--serve"]) == 0
    assert chosen == [cli.PACKAGE_ROOT / "runs"]
    assert json.loads(capsys.readouterr().out)["url"] == "http://127.0.0.1:8765/"


def test_browser_button_click_refreshes_the_report_and_recovers_from_errors():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the report button interaction test")
    harness = r"""
const assert = require('node:assert/strict');
let handler, replacement, request, fail = false;
let onSelection, navigation;
const button = {disabled: false, addEventListener: (event, fn) => {assert.equal(event, 'click'); handler = fn;}};
const status = {textContent: ''};
const selector = {value: '', disabled: false, options: [], replaceChildren() {this.options = [];},
  appendChild(option) {this.options.push(option);}, addEventListener(event, fn) {assert.equal(event, 'change'); onSelection = fn;}};
global.window = {location: {protocol: 'http:', search: '', assign: url => {navigation = url;}}};
global.document = {
  getElementById: id => id === 'render-testplan' ? button : id === 'testplan-select' ? selector : status,
  createElement: tag => {assert.equal(tag, 'option'); return {};},
  querySelector: selector => ({replaceWith: node => {replacement = node;}}),
  importNode: node => node
};
global.DOMParser = class {parseFromString(text) {return {querySelector: () => ({text})};}};
global.fetch = async (url, options) => {
  if (url === '/plans') return {ok: true, json: async () => ({selected: 'run', plans: [
    {id: 'other', label: 'other'}, {id: 'run', label: 'run'}]})};
  request = {url, options};
  assert.equal(button.disabled, true);
  if (fail) return {ok: false, json: async () => ({error: 'Markdown is missing'})};
  return {ok: true, text: async () => '<main>Updated plan</main>'};
};
__SCRIPT__
(async () => {
  await new Promise(setImmediate);
  assert.deepEqual(selector.options.map(option => option.value), ['other', 'run']);
  assert.equal(selector.value, 'run');
  selector.value = 'other';
  onSelection();
  assert.equal(navigation, '/?plan=other');
  await handler();
  assert.equal(request.url, '/render?plan=other');
  assert.equal(request.options.method, 'POST');
  assert.equal(request.options.headers['X-Testplan-Render'], '1');
  assert.equal(replacement.text, '<main>Updated plan</main>');
  assert.match(status.textContent, /saved testplan_doc.html/);
  assert.equal(button.disabled, false);
  fail = true;
  await handler();
  assert.match(status.textContent, /Markdown is missing/);
  assert.equal(button.disabled, false);
  window.location.protocol = 'file:';
  request = null;
  await handler();
  assert.equal(request, null);
  assert.match(status.textContent, /--serve/);
})().catch(error => {console.error(error); process.exitCode = 1;});
""".replace("__SCRIPT__", _CONTROLS_SCRIPT)
    result = subprocess.run([node, "-"], input=harness, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
