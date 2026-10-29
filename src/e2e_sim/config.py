"""Configuration and local state for e2e-sim.

Secrets come from the environment (or ``dv_agent/.env``, git-ignored).
Non-secret defaults live in an optional JSON config file. Node state
(node id, IP) lives in a git-ignored state file in the working directory.

There are deliberately no options for backups, encryption, BitNinja,
reserved IPs, snapshots, or extra volumes: the cheapest shape is the only
shape this tool can build.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

STATE_FILENAME = ".e2e-sim-state.json"

DEFAULTS = {
    "location": "Chennai",
    "region": "chennai",
    "plan_family": "C3.32GB",
    "os": "Ubuntu",
    "os_version": "24.04",
    "node_name": "xezim-sim",
    "label": "xezim-sim",
    # E2E Ubuntu images inject SSH keys for root (verified live 2026-10-29).
    "ssh_user": "root",
    "xezim_repo": "https://github.com/aionhw/xezim.git",
    "xezim_ref": "0.11.3",
    "remote_dir": "/root/xezim-sim",
}


@dataclass
class Config:
    auth_token: str = ""
    api_key: str = ""
    project_id: str = ""
    location: str = DEFAULTS["location"]
    region: str = DEFAULTS["region"]
    plan: str = ""          # exact SKU; resolved by `discover` when empty
    image: str = ""         # exact image; resolved by `discover` when empty
    plan_family: str = DEFAULTS["plan_family"]
    os: str = DEFAULTS["os"]
    os_version: str = DEFAULTS["os_version"]
    node_name: str = DEFAULTS["node_name"]
    label: str = DEFAULTS["label"]
    ssh_user: str = DEFAULTS["ssh_user"]
    ssh_key: str = ""       # path to the private key for ssh/scp
    ssh_pubkey: str = ""    # public key string injected at create time
    xezim_repo: str = DEFAULTS["xezim_repo"]
    xezim_ref: str = DEFAULTS["xezim_ref"]
    remote_dir: str = DEFAULTS["remote_dir"]
    disk_gb: int = 0        # only for E1/E1WC plans, which need --disk
    security_group_id: int = 0  # 0 means the project default
    errors: list[str] = field(default_factory=list)

    def check_create_ready(self) -> list[str]:
        """Missing items that block node creation (no secrets leaked)."""
        missing = []
        if not self.auth_token:
            missing.append("E2E_AUTH_TOKEN")
        if not self.plan or not self.image:
            missing.append("plan/image (run `e2e-sim discover` first)")
        if not self.ssh_pubkey and not self.ssh_key:
            missing.append("SSH public key (--ssh-key or E2E_SIM_SSH_KEY)")
        return missing


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(),
                              value.strip().strip('"').strip("'"))


def _read_pubkey_for(private_path: str) -> str:
    for candidate in (private_path + ".pub", private_path):
        try:
            text = Path(candidate).expanduser().read_text(
                encoding="utf-8").strip()
        except OSError:
            continue
        for token in text.split():
            if token.startswith(("ssh-", "ecdsa-")):
                # Return the full "type key [comment]" line.
                for line in text.splitlines():
                    if token in line:
                        return line.strip()
                return text.strip()
    return ""


def load_config(config_path: str | None = None) -> Config:
    cfg = Config()
    if config_path:
        try:
            raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            cfg.errors.append(f"cannot read config {config_path}: {exc}")
            return cfg
        if isinstance(raw, dict):
            for key in ("location", "region", "plan", "image",
                        "plan_family", "os", "os_version", "node_name",
                        "label", "ssh_user", "ssh_key", "xezim_repo",
                        "xezim_ref", "remote_dir", "project_id"):
                if raw.get(key) not in (None, ""):
                    setattr(cfg, key, raw[key])
            for key in ("disk_gb", "security_group_id"):
                if raw.get(key) not in (None, ""):
                    setattr(cfg, key, int(raw[key]))
    env_map = {
        "E2E_AUTH_TOKEN": "auth_token",
        "E2E_API_KEY": "api_key",
        "E2E_PROJECT_ID": "project_id",
        "E2E_LOCATION": "location",
        "E2E_REGION": "region",
        "E2E_PLAN": "plan",
        "E2E_IMAGE": "image",
        "E2E_NODE_NAME": "node_name",
        "E2E_SIM_SSH_KEY": "ssh_key",
        "E2E_SIM_SSH_PUBKEY": "ssh_pubkey",
        "E2E_SIM_SSH_USER": "ssh_user",
    }
    for env_key, attr in env_map.items():
        value = os.getenv(env_key, "").strip()
        if value:
            setattr(cfg, attr, value)
    if not cfg.ssh_pubkey and cfg.ssh_key:
        cfg.ssh_pubkey = _read_pubkey_for(cfg.ssh_key)
        if not cfg.ssh_pubkey:
            cfg.errors.append(f"no public key found for {cfg.ssh_key} "
                              f"(expected a .pub file or key material)")
    return cfg


def state_path(directory: str | None = None) -> Path:
    return Path(directory or os.getcwd()) / STATE_FILENAME


def load_state(directory: str | None = None) -> dict:
    try:
        raw = json.loads(state_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_state(state: dict, directory: str | None = None) -> Path:
    path = state_path(directory)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return path


def clear_state(directory: str | None = None) -> None:
    try:
        state_path(directory).unlink()
    except OSError:
        pass
