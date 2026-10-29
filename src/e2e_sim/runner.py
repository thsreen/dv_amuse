"""Node lifecycle and simulation orchestration for e2e-sim."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .client import Client, E2EError, extract_node_id, extract_public_ip
from .config import Config

REMOTE_XEZIM = "/opt/xezim-sim/xezim-bin"
REMOTE_BUILD_DONE = "/opt/xezim-sim/build.done"
REMOTE_BUILD_LOG = "/opt/xezim-sim/build.log"

BOOT_TIMEOUT_S = 600
SSH_TIMEOUT_S = 600
BUILD_TIMEOUT_S = 3600
PAUSE_TIMEOUT_S = 300


def build_create_body(cfg: Config) -> dict:
    """Cheapest possible create body: hourly on-demand, zero extras.

    No backup, encryption, BitNinja, reserved IP, IPv6, snapshot, or volume
    fields are ever set. ``default_public_ip`` uses the free auto-allocated
    IP (needed for SSH); it is released on delete.
    """
    body: dict = {
        "label": cfg.label,
        "name": cfg.node_name,
        "region": cfg.region,
        "plan": cfg.plan,
        "image": cfg.image,
        "ssh_keys": [cfg.ssh_pubkey],
        "number_of_instances": 1,
        "disable_password": True,
        "backups": False,
        "isEncryptionEnabled": False,
        "is_encryption_required": False,
        "enable_bitninja": False,
        "is_ipv6_availed": False,
        "is_private": False,
        "default_public_ip": True,
        "start_scripts": [BOOTSTRAP_TEMPLATE],
    }
    if cfg.disk_gb:
        body["disk"] = cfg.disk_gb
    if cfg.security_group_id:
        body["security_group_id"] = cfg.security_group_id
    return body


BOOTSTRAP_TEMPLATE = """#!/bin/bash
# e2e-sim first-boot provision: build xezim once, then never again.
# Runs as root via cloud-init. Resume-from-pause keeps the disk, so this
# cost is paid exactly once per node. Markers live in /opt/xezim-sim/.
set -u
M=/opt/xezim-sim
mkdir -p "$M"
REPO="${E2E_SIM_XEZIM_REPO:-__XEZIM_REPO__}"
REF="${E2E_SIM_XEZIM_REF:-__XEZIM_REF__}"
(
  export DEBIAN_FRONTEND=noninteractive
  apt-get update >>"$M/apt.log" 2>&1
  apt-get install -y git curl build-essential pkg-config >>"$M/apt.log" 2>&1
  if ! command -v cargo >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup.sh
    sh /tmp/rustup.sh -y --profile minimal --default-toolchain stable >>"$M/rust.log" 2>&1
  fi
  export PATH="$HOME/.cargo/bin:/root/.cargo/bin:$PATH"
  if [ ! -d "$M/src" ]; then
    git clone --depth 1 --branch "$REF" "$REPO" "$M/src" >>"$M/build.log" 2>&1
  fi
  cd "$M/src" && cargo build --release >>"$M/build.log" 2>&1
  echo "exit=$?" >"$M/build.done"
  if [ -x "$M/src/target/release/xezim" ]; then
    ln -sf "$M/src/target/release/xezim" /opt/xezim-sim/xezim-bin
  fi
) >>"$M/build.log" 2>&1 &
"""


def render_bootstrap(cfg: Config) -> str:
    return (BOOTSTRAP_TEMPLATE
            .replace("__XEZIM_REPO__", cfg.xezim_repo)
            .replace("__XEZIM_REF__", cfg.xezim_ref))


def ssh_base(cfg: Config, workdir: str) -> list[str]:
    known_hosts = str(Path(workdir) / ".e2e-sim-known-hosts")
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           "-o", "StrictHostKeyChecking=accept-new",
           "-o", f"UserKnownHostsFile={known_hosts}"]
    if cfg.ssh_key:
        cmd += ["-i", cfg.ssh_key]
    return cmd


def scp_base(cfg: Config, workdir: str) -> list[str]:
    known_hosts = str(Path(workdir) / ".e2e-sim-known-hosts")
    cmd = ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           "-o", "StrictHostKeyChecking=accept-new",
           "-o", f"UserKnownHostsFile={known_hosts}"]
    if cfg.ssh_key:
        cmd += ["-i", cfg.ssh_key]
    return cmd


def node_status(client: Client, node_id: str) -> tuple[str, dict]:
    payload = client.get_node(node_id)
    data = payload.get("data", {})
    status = str(data.get("status", "")).strip().lower() if isinstance(
        data, dict) else ""
    return status, payload


def is_running(status: str) -> bool:
    return status == "running"


def is_paused(status: str) -> bool:
    return status in ("stopped", "powered off", "poweroff", "off",
                      "suspended", "paused")


def wait_for(client: Client, node_id: str, want: str,
             timeout_s: int, poll_s: int = 10) -> dict:
    """Wait until the node status matches ``want`` ('running'/'paused')."""
    deadline = time.time() + timeout_s
    last = ""
    payload: dict = {}
    while time.time() < deadline:
        last, payload = node_status(client, node_id)
        if want == "running" and is_running(last):
            return payload
        if want == "paused" and is_paused(last):
            return payload
        time.sleep(poll_s)
    raise E2EError(f"node {node_id} did not become {want} within "
                   f"{timeout_s}s (last status: {last!r})")


def wait_for_ssh(cfg: Config, workdir: str, ip: str,
                 timeout_s: int = SSH_TIMEOUT_S) -> None:
    deadline = time.time() + timeout_s
    target = f"{cfg.ssh_user}@{ip}"
    while time.time() < deadline:
        proc = subprocess.run(
            ssh_base(cfg, workdir) + [target, "true"],
            capture_output=True, timeout=30)
        if proc.returncode == 0:
            return
        time.sleep(10)
    raise E2EError(f"SSH to {target} not ready within {timeout_s}s")


def run_ssh(cfg: Config, workdir: str, ip: str, remote_cmd: str,
            stream: bool = False) -> subprocess.CompletedProcess:
    target = f"{cfg.ssh_user}@{ip}"
    if stream:
        return subprocess.run(ssh_base(cfg, workdir) + [target, remote_cmd])
    return subprocess.run(ssh_base(cfg, workdir) + [target, remote_cmd],
                          capture_output=True, text=True, timeout=600)


BUILD_TRIGGER = ("test -f %s && grep -q exit=0 %s || "
                 "(mkdir -p /opt/xezim-sim && "
                 "setsid nohup bash /tmp/e2e-sim-bootstrap.sh "
                 ">/tmp/e2e-sim-bootstrap.out 2>&1 < /dev/null &)")


def ensure_xezim(cfg: Config, workdir: str, ip: str,
                 local_bin: str | None = None,
                 timeout_s: int = BUILD_TIMEOUT_S) -> str:
    """Return the remote xezim path, uploading or waiting for a build.

    When no local binary is given and the first-boot script did not finish
    (some images lack cloud-init), the build is (re)started over SSH.
    """
    if local_bin:
        dest = f"{cfg.ssh_user}@{ip}:/tmp/xezim-bin"
        proc = subprocess.run(
            scp_base(cfg, workdir) + [local_bin, dest],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise E2EError(f"upload of {local_bin} failed: {proc.stderr}")
        inst = run_ssh(cfg, workdir, ip,
                       "sudo mkdir -p /opt/xezim-sim "
                       "&& sudo mv /tmp/xezim-bin "
                       f"{REMOTE_XEZIM} && sudo chmod +x {REMOTE_XEZIM} "
                       f"&& {REMOTE_XEZIM} --version")
        if inst.returncode != 0:
            raise E2EError("uploaded xezim binary does not run on the "
                           f"node: {(inst.stderr or '')[:300]} "
                           "(omit --xezim-bin to build on the node)")
        return REMOTE_XEZIM
    deadline = time.time() + timeout_s
    probe = "test -f %s && cat %s" % (REMOTE_BUILD_DONE, REMOTE_BUILD_DONE)
    triggered = False
    while time.time() < deadline:
        proc = run_ssh(cfg, workdir, ip, probe)
        if proc.returncode == 0 and "exit=" in (proc.stdout or ""):
            if "exit=0" not in (proc.stdout or ""):
                raise E2EError(
                    "xezim build failed on the node; see "
                    f"{REMOTE_BUILD_LOG} via `e2e-sim ssh -- tail`")
            return REMOTE_XEZIM
        if not triggered:
            triggered = True
            _trigger_build_over_ssh(cfg, workdir, ip)
        time.sleep(20)
    raise E2EError(f"xezim build not done within {timeout_s}s "
                   f"(log: {REMOTE_BUILD_LOG})")


def _trigger_build_over_ssh(cfg: Config, workdir: str, ip: str) -> None:
    script = Path(workdir) / ".e2e-sim-bootstrap.sh"
    script.write_text(render_bootstrap(cfg), encoding="utf-8")
    dest = f"{cfg.ssh_user}@{ip}:/tmp/e2e-sim-bootstrap.sh"
    proc = subprocess.run(scp_base(cfg, workdir) + [str(script), dest],
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise E2EError(f"bootstrap upload failed: {proc.stderr}")
    proc = run_ssh(cfg, workdir, ip,
                   BUILD_TRIGGER % (REMOTE_BUILD_DONE, REMOTE_BUILD_DONE))
    if proc.returncode != 0:
        raise E2EError("could not start the xezim build over SSH: "
                       f"{(proc.stderr or '')[:200]}")


def upload_sources(cfg: Config, workdir: str, ip: str,
                   src_dir: str) -> str:
    """Tar local sources, upload, and extract into the remote work dir."""
    src = Path(src_dir).resolve()
    if not src.is_dir():
        raise E2EError(f"source dir not found: {src_dir}")
    tarball = Path(workdir) / ".e2e-sim-src.tar.gz"
    proc = subprocess.run(["tar", "czf", str(tarball), "-C", str(src), "."],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise E2EError(f"cannot tar {src_dir}: {proc.stderr}")
    dest = f"{cfg.ssh_user}@{ip}:/tmp/e2e-sim-src.tar.gz"
    proc = subprocess.run(scp_base(cfg, workdir) + [str(tarball), dest],
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise E2EError(f"source upload failed: {proc.stderr}")
    remote_work = f"{cfg.remote_dir}/work"
    proc = run_ssh(cfg, workdir, ip,
                   f"mkdir -p {remote_work} && tar xzf /tmp/e2e-sim-src.tar.gz"
                   f" -C {remote_work}")
    if proc.returncode != 0:
        raise E2EError(f"remote extract failed: {(proc.stderr or '')[:300]}")
    return remote_work


def run_remote_cmd(cfg: Config, workdir: str, ip: str, remote_cwd: str,
                   argv: list[str], log_name: str = "exec.log") -> int:
    """Run an arbitrary command on the node, streaming output.

    Returns the remote exit code.
    """
    import shlex

    quoted = " ".join(shlex.quote(a) for a in argv)
    remote_cmd = (f"mkdir -p {remote_cwd} && cd {remote_cwd} && "
                  f"set -o pipefail && {quoted} 2>&1 | tee {log_name}")
    proc = run_ssh(cfg, workdir, ip, remote_cmd, stream=True)
    return proc.returncode


def run_remote_sim(cfg: Config, workdir: str, ip: str, remote_work: str,
                   xezim_args: list[str]) -> int:
    """Run xezim on the node, streaming output. Returns exit code."""
    return run_remote_cmd(cfg, workdir, ip, remote_work,
                          [REMOTE_XEZIM] + list(xezim_args),
                          log_name="sim.log")


def fetch_results(cfg: Config, workdir: str, ip: str, remote_work: str,
                  dest_dir: str) -> Path:
    """Download the remote work dir (logs, coverage, waves) as a tarball."""
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    proc = run_ssh(cfg, workdir, ip,
                   f"tar czf /tmp/e2e-sim-out.tar.gz -C {remote_work} .")
    if proc.returncode != 0:
        raise E2EError(f"remote pack failed: {(proc.stderr or '')[:300]}")
    src = f"{cfg.ssh_user}@{ip}:/tmp/e2e-sim-out.tar.gz"
    tarball = dest / "sim-results.tar.gz"
    proc = subprocess.run(scp_base(cfg, workdir) + [src, str(tarball)],
                          capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise E2EError(f"result download failed: {proc.stderr}")
    proc = subprocess.run(["tar", "xzf", str(tarball), "-C", str(dest)],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise E2EError(f"cannot unpack results: {proc.stderr}")
    return dest


def ensure_node(client: Client, cfg: Config, state: dict) -> tuple[str, str]:
    """Create the node, or reuse/resume the one recorded in state.

    Returns (node_id, public_ip). The bootstrap script is rendered with the
    configured repo/ref before create.
    """
    node_id = str(state.get("node_id", "") or "")
    if node_id:
        status, payload = node_status(client, node_id)
        if is_running(status):
            ip = extract_public_ip(payload) or str(
                state.get("public_ip", ""))
            if not ip:
                raise E2EError(f"node {node_id} is running but has no "
                               f"public IP yet; retry shortly")
            return node_id, ip
        if is_paused(status):
            client.power_on(node_id)
            payload = wait_for(client, node_id, "running", BOOT_TIMEOUT_S)
            ip = extract_public_ip(payload)
            if not ip:
                raise E2EError(f"node {node_id} resumed but has no "
                               f"public IP yet; retry shortly")
            return node_id, ip
        raise E2EError(f"node {node_id} is in unexpected status {status!r}; "
                       f"inspect with `e2e-sim status`")
    missing = cfg.check_create_ready()
    if missing:
        raise E2EError("cannot create node, missing: " + ", ".join(missing))
    body = build_create_body(cfg)
    body["start_scripts"] = [render_bootstrap(cfg)]
    payload = client.create_node(body)
    node_id = extract_node_id(payload)
    payload = wait_for(client, node_id, "running", BOOT_TIMEOUT_S)
    ip = extract_public_ip(payload)
    if not ip:
        raise E2EError(f"node {node_id} is running but has no public IP "
                       f"yet; retry shortly")
    return node_id, ip
