"""Offline tests for e2e-sim (no network, no subprocess side effects)."""

import argparse
import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from e2e_sim import cli as cli_mod
from e2e_sim import runner as runner_mod
from e2e_sim.client import (Client, E2EError, _redact, extract_node_id,
                            extract_public_ip)
from e2e_sim.config import (clear_state, load_config, load_state,
                            save_state)
from e2e_sim.config import Config
from e2e_sim.runner import (build_create_body, ensure_node, ensure_xezim,
                            is_paused, is_running, render_bootstrap,
                            run_remote_sim, upload_sources, wait_for)


class FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_urlopen(monkeypatch):
    calls = []
    payloads = []

    def _open(req, timeout=None):
        calls.append(req)
        payload = payloads.pop(0) if payloads else {"code": 200, "data": {}}
        if isinstance(payload, Exception):
            raise payload
        return FakeHTTPResponse(payload)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _open)
    return calls, payloads


def _client():
    return Client(auth_token="tok", project_id="42", location="Chennai",
                  api_key="key")


# -- client -----------------------------------------------------------

def test_auth_header_and_query(fake_urlopen):
    calls, _ = fake_urlopen
    _client().list_nodes()
    req = calls[0]
    assert req.get_header("Authorization") == "Bearer tok"
    assert "project_id=42" in req.full_url
    assert "location=Chennai" in req.full_url
    assert "apikey=key" in req.full_url


def test_project_id_omitted_when_empty(monkeypatch):
    import urllib.request
    seen = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: seen.append(req) or
                        FakeHTTPResponse({"code": 200, "data": {}}))
    Client(auth_token="tok", project_id="", location="Chennai").list_nodes()
    assert "project_id" not in seen[0].full_url
    assert "location=Chennai" in seen[0].full_url


def test_no_apikey_param_without_key(monkeypatch):
    import urllib.request
    seen = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: seen.append(req) or
                        FakeHTTPResponse({"code": 200, "data": {}}))
    Client(auth_token="tok", project_id="42",
           location="Chennai").list_nodes()
    assert "apikey" not in seen[0].full_url


def test_http_error_redacts_key(fake_urlopen):
    _, payloads = fake_urlopen
    payloads.append(urllib.error.HTTPError(
        "http://x", 403, "forbidden", {}, io.BytesIO(b"nope")))
    with pytest.raises(E2EError, match="403") as exc:
        _client().list_nodes()
    assert "apikey=%2A%2A%2A" in str(exc.value) or "***" in str(exc.value)
    assert "apikey=key" not in str(exc.value)


def test_redact_helper():
    url = "https://h/api?project_id=1&apikey=secret&location=X"
    assert "secret" not in _redact(url)
    assert "project_id=1" in _redact(url)


def test_unexpected_shape_rejected(fake_urlopen):
    _, payloads = fake_urlopen
    payloads.append({"weird": True})
    with pytest.raises(E2EError, match="unexpected"):
        _client().list_nodes()


def test_empty_token_rejected():
    with pytest.raises(E2EError, match="token"):
        Client(auth_token="", project_id="1", location="X")


def test_extract_node_id_shapes():
    assert extract_node_id({"data": {"id": 7}}) == "7"
    assert extract_node_id({"data": {"vm_id": 9}}) == "9"
    assert extract_node_id({"data": [{"node_id": 11}]}) == "11"
    assert extract_node_id({"data": {"node_create_response": [
        {"id": 352624, "vm_id": 30492}]}}) == "352624"
    with pytest.raises(E2EError):
        extract_node_id({"data": {}})


def test_extract_public_ip_shapes():
    assert extract_public_ip({"data": {"public_ip_address": "1.2.3.4"}}) \
        == "1.2.3.4"
    assert extract_public_ip({"data": {"public_ip": ["5.6.7.8"]}}) \
        == "5.6.7.8"
    assert extract_public_ip({"data": {"public_ip_address": "[]"}}) == ""


# -- create body: cheapest shape --------------------------------------

def _ready_cfg(**over):
    kw = dict(auth_token="t", project_id="1", plan="PLAN", image="IMG",
              ssh_pubkey="ssh-ed25519 AAA user@h")
    kw.update(over)
    return Config(**kw)


def test_create_body_has_zero_extras():
    body = build_create_body(_ready_cfg())
    assert body["backups"] is False
    assert body["isEncryptionEnabled"] is False
    assert body["is_encryption_required"] is False
    assert body["enable_bitninja"] is False
    assert body["is_ipv6_availed"] is False
    assert body["is_private"] is False
    assert body["number_of_instances"] == 1
    assert body["default_public_ip"] is True
    assert body["disable_password"] is True
    for forbidden in ("reserve_ip", "subnet_id", "vpc_id", "snapshot",
                      "volume", "ngc_container_id"):
        assert forbidden not in body
    assert body["start_scripts"] and len(body["start_scripts"][0]) < 16 * 1024


def test_create_body_disk_only_for_e1():
    assert "disk" not in build_create_body(_ready_cfg())
    assert build_create_body(_ready_cfg(disk_gb=100))["disk"] == 100


def test_bootstrap_renders_repo_ref():
    script = render_bootstrap(_ready_cfg())
    assert "__XEZIM" not in script
    assert "aionhw/xezim" in script
    assert "cargo build --release" in script
    assert "build.done" in script


def test_status_classifiers():
    assert is_running("Running".lower())
    assert not is_running("stopped")
    assert is_paused("stopped")
    assert is_paused("powered off")
    assert not is_paused("running")


# -- config/state -----------------------------------------------------

def test_config_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("E2E_AUTH_TOKEN", "abc")
    monkeypatch.setenv("E2E_PROJECT_ID", "7")
    monkeypatch.setenv("E2E_LOCATION", "Delhi")
    cfg = load_config()
    assert (cfg.auth_token, cfg.project_id, cfg.location) == (
        "abc", "7", "Delhi")
    assert "plan/image" in " ".join(cfg.check_create_ready())


def test_config_file_merge(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"location": "Chennai", "plan": "P",
                                "image": "I", "disk_gb": 120}))
    cfg = load_config(str(path))
    assert (cfg.location, cfg.plan, cfg.image, cfg.disk_gb) == (
        "Chennai", "P", "I", 120)


def test_pubkey_discovery(tmp_path, monkeypatch):
    key = tmp_path / "id_ed25519"
    key.write_text("x")
    (tmp_path / "id_ed25519.pub").write_text(
        "ssh-ed25519 AAAAC3 u@h\n")
    monkeypatch.setenv("E2E_SIM_SSH_KEY", str(key))
    assert load_config().ssh_pubkey == "ssh-ed25519 AAAAC3 u@h"


def test_state_roundtrip(tmp_path):
    assert load_state(str(tmp_path)) == {}
    save_state({"node_id": "5"}, str(tmp_path))
    assert load_state(str(tmp_path)) == {"node_id": "5"}
    clear_state(str(tmp_path))
    assert load_state(str(tmp_path)) == {}


# -- runner -----------------------------------------------------------

class FakeClient:
    def __init__(self, statuses=None):
        self.statuses = list(statuses or ["running"])
        self.created = []
        self.actions = []
        self.deleted = []

    def get_node(self, node_id):
        status = self.statuses[0] if len(self.statuses) == 1 \
            else self.statuses.pop(0)
        return {"code": 200,
                "data": {"id": node_id, "status": status,
                         "public_ip_address": "9.9.9.9", "plan": "P"}}

    def create_node(self, body):
        self.created.append(body)
        return {"code": 201, "data": {"id": 123}}

    def power_on(self, node_id):
        self.actions.append(("power_on", node_id))
        self.statuses.append("running")
        return {"code": 200, "data": {}}

    def power_off(self, node_id):
        self.actions.append(("power_off", node_id))
        return {"code": 200, "data": {}}

    def delete_node(self, node_id):
        self.deleted.append(node_id)
        return {"code": 200, "data": {}}


def test_wait_for_running(monkeypatch):
    monkeypatch.setattr(runner_mod.time, "sleep", lambda s: None)
    client = FakeClient(["pending", "pending", "running"])
    payload = wait_for(client, "1", "running", timeout_s=60, poll_s=0)
    assert payload["data"]["status"] == "running"


def test_wait_for_timeout(monkeypatch):
    monkeypatch.setattr(runner_mod.time, "sleep", lambda s: None)
    with pytest.raises(E2EError, match="did not become"):
        wait_for(FakeClient(["pending"]), "1", "running", timeout_s=0,
                 poll_s=0)


def test_ensure_node_reuses_running():
    node_id, ip = ensure_node(FakeClient(["running"]), _ready_cfg(),
                              {"node_id": "42"})
    assert (node_id, ip) == ("42", "9.9.9.9")


def test_ensure_node_resumes_paused(monkeypatch):
    monkeypatch.setattr(runner_mod.time, "sleep", lambda s: None)
    client = FakeClient(["powered off"])
    node_id, ip = ensure_node(client, _ready_cfg(), {"node_id": "42"})
    assert (node_id, ip) == ("42", "9.9.9.9")
    assert client.actions == [("power_on", "42")]


def test_ensure_node_creates(monkeypatch):
    monkeypatch.setattr(runner_mod.time, "sleep", lambda s: None)
    client = FakeClient(["running"])
    node_id, ip = ensure_node(client, _ready_cfg(), {})
    assert (node_id, ip) == ("123", "9.9.9.9")
    assert client.created[0]["plan"] == "PLAN"
    assert "aionhw/xezim" in client.created[0]["start_scripts"][0]


def test_ensure_node_refuses_without_plan():
    with pytest.raises(E2EError, match="missing"):
        ensure_node(FakeClient(), Config(auth_token="t"), {})


def test_ensure_xezim_upload(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "scp":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "xezim 0.11.3", "")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    remote = ensure_xezim(_ready_cfg(), str(tmp_path), "9.9.9.9",
                          local_bin="/tmp/xezim")
    assert remote == "/opt/xezim-sim/xezim-bin"
    assert calls[0][0] == "scp" and calls[1][0] == "ssh"
    assert "-i" not in calls[0]  # no key configured in this fixture


def test_ensure_xezim_bad_upload(monkeypatch, tmp_path):
    def fake_run(cmd, **kw):
        if cmd[0] == "scp":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", "Exec format error")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    with pytest.raises(E2EError, match="does not run"):
        ensure_xezim(_ready_cfg(), str(tmp_path), "9.9.9.9",
                     local_bin="/tmp/xezim")


def test_ensure_xezim_triggers_build_over_ssh(monkeypatch, tmp_path):
    monkeypatch.setattr(runner_mod.time, "sleep", lambda s: None)
    uploads = []
    launched = []

    probes = [(1, ""), (0, "exit=0")]

    def fake_run(cmd, **kw):
        if cmd[0] == "scp":
            uploads.append(cmd[-2])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if "setsid" in cmd[-1]:
            launched.append(cmd[-1])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        code, out = probes[0] if len(probes) == 1 else probes.pop(0)
        return subprocess.CompletedProcess(cmd, code, out, "")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    assert ensure_xezim(_ready_cfg(), str(tmp_path), "9.9.9.9",
                        timeout_s=60) == "/opt/xezim-sim/xezim-bin"
    assert len(uploads) == 1 and uploads[0].endswith("bootstrap.sh")
    assert len(launched) == 1


def test_ensure_xezim_waits_for_build(monkeypatch, tmp_path):
    monkeypatch.setattr(runner_mod.time, "sleep", lambda s: None)
    outputs = [(1, ""), (0, "exit=0")]

    def fake_run(cmd, **kw):
        code, out = outputs[0] if len(outputs) == 1 else outputs.pop(0)
        return subprocess.CompletedProcess(cmd, code, out, "")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    assert ensure_xezim(_ready_cfg(), str(tmp_path), "9.9.9.9",
                        timeout_s=60) == "/opt/xezim-sim/xezim-bin"


def test_upload_and_run(monkeypatch, tmp_path):
    src = tmp_path / "design"
    src.mkdir()
    (src / "top.sv").write_text("module top; endmodule\n")
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd[0])
        if cmd[0] == "tar" and "czf" in cmd:
            Path(cmd[2]).write_bytes(b"fake-tar")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    remote = upload_sources(_ready_cfg(), str(tmp_path), "9.9.9.9",
                            str(src))
    assert remote.endswith("/work")
    assert seen[:3] == ["tar", "scp", "ssh"]
    code = run_remote_sim(_ready_cfg(), str(tmp_path), "9.9.9.9", remote,
                          ["top.sv", "+UVM_TESTNAME=my_test"])
    assert code == 0


# -- cli --------------------------------------------------------------

def _args(monkeypatch, tmp_path, **over):
    ns = {"config": None, "workdir": str(tmp_path), "node_id": None}
    ns.update(over)
    monkeypatch.setattr(cli_mod, "load_env_file", lambda path: None)
    return argparse.Namespace(**ns)


def test_cli_discover_writes_config(monkeypatch, tmp_path, capsys):
    out_cfg = tmp_path / "e2e.json"
    args = _args(monkeypatch, tmp_path, family="C3.32GB",
                 write_config=str(out_cfg))

    class Cfg:
        auth_token = "t"
        project_id = "1"
        location = "Chennai"
        os = "Ubuntu"
        os_version = "24.04"
        plan_family = "C3.32GB"

    class FakeCat:
        def list_os_plans(self, **kw):
            return {"data": [
                {"name": "C3.32GB",
                 "plan": "C3-16vCPU-32RAM-200DISK-C3-Onetemplate-"
                         "Ubuntu24.04-Chennai",
                 "image": "Ubuntu-24.04-Distro"}]}

    monkeypatch.setattr(cli_mod, "load_config", lambda c=None: Cfg())
    monkeypatch.setattr(cli_mod, "_client", lambda cfg: FakeCat())
    assert cli_mod.cmd_discover(args) == 0
    saved = json.loads(out_cfg.read_text())
    assert saved["plan"].startswith("C3-16vCPU-32RAM")
    assert "Ubuntu-24.04" in capsys.readouterr().out


def test_cli_kill_needs_confirmation(monkeypatch, tmp_path):
    save_state({"node_id": "9"}, str(tmp_path))
    args = _args(monkeypatch, tmp_path, yes=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    monkeypatch.setattr(cli_mod, "load_config", lambda c=None: Config())
    assert cli_mod.cmd_kill(args) == 1
    assert load_state(str(tmp_path))["node_id"] == "9"


def test_cli_kill_yes_deletes(monkeypatch, tmp_path):
    save_state({"node_id": "9", "public_ip": "1.1.1.1"}, str(tmp_path))
    args = _args(monkeypatch, tmp_path, yes=True)
    client = FakeClient(["running"])
    monkeypatch.setattr(cli_mod, "load_config",
                        lambda c=None: _ready_cfg())
    monkeypatch.setattr(cli_mod, "_client", lambda cfg: client)
    assert cli_mod.cmd_kill(args) == 0
    assert client.deleted == ["9"]
    assert load_state(str(tmp_path)) == {}


def test_cli_run_parsing_strips_dashes():
    parser = cli_mod.build_parser()
    args = parser.parse_args(["run", "--src", "d", "--", "top.sv", "+X=1"])
    assert args.xezim_args == ["--", "top.sv", "+X=1"]
    # main() strips the leading `--` before dispatch.
    assert [a for a in args.xezim_args if a != "--"] == ["top.sv", "+X=1"]


def _exec_args(monkeypatch, tmp_path, **over):
    ns = {"config": None, "workdir": str(tmp_path), "node_id": None,
          "src": "", "results": "", "cmd": ["echo", "hi"],
          "keep": False, "kill": False, "yes": True,
          "ssh_timeout": 600, "pause_timeout": 300}
    ns.update(over)
    monkeypatch.setattr(cli_mod, "load_env_file", lambda path: None)
    return argparse.Namespace(**ns)


def test_cmd_exec_plain_command(monkeypatch, tmp_path):
    args = _exec_args(monkeypatch, tmp_path)
    client = FakeClient(["running"])
    ran = {}

    monkeypatch.setattr(cli_mod, "load_config",
                        lambda c=None: _ready_cfg())
    monkeypatch.setattr(cli_mod, "_client", lambda cfg: client)
    monkeypatch.setattr(cli_mod, "ensure_node",
                        lambda *a: ("42", "9.9.9.9"))
    monkeypatch.setattr(cli_mod, "wait_for_ssh", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "wait_for", lambda *a, **k: {})
    monkeypatch.setattr(
        cli_mod, "upload_sources",
        lambda *a: (_ for _ in ()).throw(AssertionError("no upload")))
    monkeypatch.setattr(
        cli_mod, "run_remote_cmd",
        lambda cfg, wd, ip, cwd, cmd: ran.update(cmd=cmd) or 0)
    assert cli_mod.cmd_exec(args) == 0
    assert ran["cmd"] == ["echo", "hi"]
    assert client.actions == [("power_off", "42")]
    assert load_state(str(tmp_path))["node_id"] == "42"


def test_cmd_exec_src_results_keep(monkeypatch, tmp_path):
    args = _exec_args(monkeypatch, tmp_path, src="design", results="out",
                      keep=True)
    client = FakeClient(["running"])
    calls = []
    monkeypatch.setattr(cli_mod, "load_config",
                        lambda c=None: _ready_cfg())
    monkeypatch.setattr(cli_mod, "_client", lambda cfg: client)
    monkeypatch.setattr(cli_mod, "ensure_node",
                        lambda *a: ("42", "9.9.9.9"))
    monkeypatch.setattr(cli_mod, "wait_for_ssh", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "upload_sources",
                        lambda *a: calls.append("up") or "/remote/work")
    monkeypatch.setattr(cli_mod, "run_remote_cmd",
                        lambda *a: calls.append("run") or 3)
    monkeypatch.setattr(cli_mod, "fetch_results",
                        lambda *a: calls.append("fetch") or tmp_path)
    assert cli_mod.cmd_exec(args) == 3  # remote exit code propagates
    assert calls == ["up", "run", "fetch"]
    assert client.actions == []  # --keep: no pause


def test_cmd_exec_empty_command(monkeypatch, tmp_path):
    args = _exec_args(monkeypatch, tmp_path, cmd=[])
    monkeypatch.setattr(cli_mod, "load_config",
                        lambda c=None: _ready_cfg())
    assert cli_mod.cmd_exec(args) == 1


def test_finish_node_kill_path(monkeypatch, tmp_path):
    save_state({"node_id": "9"}, str(tmp_path))
    args = _exec_args(monkeypatch, tmp_path, kill=True)
    client = FakeClient(["running"])
    monkeypatch.setattr(cli_mod, "load_config",
                        lambda c=None: _ready_cfg())
    monkeypatch.setattr(cli_mod, "_client", lambda cfg: client)
    assert cli_mod._finish_node(client, "9", 0, args) == 0
    assert client.deleted == ["9"]
    assert load_state(str(tmp_path)) == {}


def test_cmd_up_honors_node_id(monkeypatch, tmp_path):
    args = argparse.Namespace(config=None, workdir=str(tmp_path),
                              node_id="352624", build=False, xezim_bin="",
                              ssh_timeout=600, build_timeout=3600)
    seen = {}
    monkeypatch.setattr(cli_mod, "load_config",
                        lambda c=None: _ready_cfg())
    monkeypatch.setattr(cli_mod, "_client",
                        lambda cfg: FakeClient(["running"]))

    def fake_ensure(client, cfg, state):
        seen.update(state)
        return ("352624", "9.9.9.9")

    monkeypatch.setattr(cli_mod, "ensure_node", fake_ensure)
    monkeypatch.setattr(cli_mod, "wait_for_ssh", lambda *a, **k: None)
    assert cli_mod.cmd_up(args) == 0
    assert seen == {"node_id": "352624"}
    assert load_state(str(tmp_path))["node_id"] == "352624"


def test_exec_main_parsing(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli_mod, "load_env_file", lambda path: None)
    monkeypatch.setattr(cli_mod, "cmd_exec",
                        lambda args: seen.update(vars(args)) or 0)
    assert cli_mod.exec_main(["--config", "c.json", "--workdir",
                              str(tmp_path), "--", "echo", "hi"]) == 0
    assert seen["config"] == "c.json"
    assert seen["cmd"] == ["echo", "hi"]
    assert cli_mod.exec_main(["nproc"]) == 0
    assert seen["cmd"] == ["nproc"]
