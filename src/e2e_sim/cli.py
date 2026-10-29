"""e2e-sim CLI: discover | up | run | pause | resume | kill | status | ssh."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .client import Client, E2EError, extract_public_ip
from .config import (DEFAULTS, clear_state, load_config, load_env_file,
                     load_state, save_state)
from .runner import (BOOT_TIMEOUT_S, ensure_node, ensure_xezim,
                     fetch_results, is_paused, is_running, node_status,
                     run_remote_cmd, run_remote_sim, run_ssh,
                     upload_sources, wait_for, wait_for_ssh)

EXIT_OK = 0
EXIT_ERROR = 1

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _client(cfg) -> Client:
    return Client(auth_token=cfg.auth_token, project_id=cfg.project_id,
                  location=cfg.location, api_key=cfg.api_key)


def _load_state(args) -> dict:
    state = load_state(args.workdir)
    if getattr(args, "node_id", None) and not state.get("node_id"):
        state = {"node_id": str(args.node_id)}
    return state


def cmd_discover(args) -> int:
    cfg = load_config(args.config)
    if not cfg.auth_token:
        print("need E2E_AUTH_TOKEN to query the catalog",
              file=sys.stderr)
        return EXIT_ERROR
    client = _client(cfg)
    try:
        plans = client.list_os_plans(os=cfg.os, osversion=cfg.os_version)
    except E2EError as exc:
        print(f"catalog query failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    rows = plans.get("data", []) if isinstance(plans, dict) else []
    want = (args.family or cfg.plan_family).lower()
    matches = [r for r in rows if isinstance(r, dict) and (
        want in str(r.get("name", "")).lower()
        or want in str(r.get("plan", "")).lower())]
    if not matches:
        print(f"no plans matching {want!r} for {cfg.os} {cfg.os_version} "
              f"in {cfg.location}. Full rows:", file=sys.stderr)
        for row in rows:
            if isinstance(row, dict):
                print(f"  name={row.get('name')} plan={row.get('plan')} "
                      f"image={row.get('image')}")
        return EXIT_ERROR
    print(f"location={cfg.location} family={want}")
    for row in matches:
        print(f"  name={row.get('name')} plan={row.get('plan')}\n"
              f"  image={row.get('image')}")
    if args.write_config and len(matches) >= 1:
        pick = matches[0]
        out = {"location": cfg.location, "plan": pick.get("plan"),
               "image": pick.get("image")}
        Path(args.write_config).write_text(json.dumps(out, indent=2) + "\n",
                                           encoding="utf-8")
        print(f"wrote {args.write_config}; pass it with --config")
    else:
        print("Set E2E_PLAN/E2E_IMAGE or a --config JSON with these values.")
    return EXIT_OK


def cmd_up(args) -> int:
    cfg = load_config(args.config)
    state = _load_state(args)
    client = _client(cfg)
    try:
        node_id, ip = ensure_node(client, cfg, state)
        wait_for_ssh(cfg, args.workdir or os.getcwd(), ip,
                     timeout_s=args.ssh_timeout)
        if args.build:
            ensure_xezim(cfg, args.workdir or os.getcwd(), ip,
                         local_bin=args.xezim_bin,
                         timeout_s=args.build_timeout)
    except E2EError as exc:
        print(f"up failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    save_state({"node_id": node_id, "public_ip": ip,
                "plan": cfg.plan, "location": cfg.location},
               args.workdir)
    print(f"node {node_id} running at {ip} (state saved)")
    return EXIT_OK


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    if not args.xezim_args:
        print("no xezim arguments given after --", file=sys.stderr)
        return EXIT_ERROR
    workdir = args.workdir or os.getcwd()
    state = _load_state(args)
    client = _client(cfg)
    try:
        node_id, ip = ensure_node(client, cfg, state)
        save_state({"node_id": node_id, "public_ip": ip,
                    "plan": cfg.plan, "location": cfg.location},
                   args.workdir)
        wait_for_ssh(cfg, workdir, ip, timeout_s=args.ssh_timeout)
        ensure_xezim(cfg, workdir, ip, local_bin=args.xezim_bin,
                     timeout_s=args.build_timeout)
        remote_work = upload_sources(cfg, workdir, ip, args.src)
        code = run_remote_sim(cfg, workdir, ip, remote_work,
                              args.xezim_args)
        dest = fetch_results(cfg, workdir, ip, remote_work, args.results)
        print(f"results in {dest} (sim exit code {code})")
    except E2EError as exc:
        print(f"run failed: {exc}", file=sys.stderr)
        print("node left as-is; use `e2e-sim pause` or `e2e-sim kill`",
              file=sys.stderr)
        return EXIT_ERROR
    return _finish_node(client, node_id, code, args)


def cmd_exec(args) -> int:
    cfg = load_config(args.config)
    if not args.cmd:
        print("no command given after --", file=sys.stderr)
        return EXIT_ERROR
    workdir = args.workdir or os.getcwd()
    state = _load_state(args)
    client = _client(cfg)
    try:
        node_id, ip = ensure_node(client, cfg, state)
        save_state({"node_id": node_id, "public_ip": ip,
                    "plan": cfg.plan, "location": cfg.location},
                   args.workdir)
        wait_for_ssh(cfg, workdir, ip, timeout_s=args.ssh_timeout)
        remote_cwd = cfg.remote_dir
        if args.src:
            remote_cwd = upload_sources(cfg, workdir, ip, args.src)
        code = run_remote_cmd(cfg, workdir, ip, remote_cwd, args.cmd)
        if args.results:
            dest = fetch_results(cfg, workdir, ip, remote_cwd,
                                 args.results)
            print(f"results in {dest} (exit code {code})")
    except E2EError as exc:
        print(f"exec failed: {exc}", file=sys.stderr)
        print("node left as-is; use `e2e-sim pause` or `e2e-sim kill`",
              file=sys.stderr)
        return EXIT_ERROR
    return _finish_node(client, node_id, code, args)


def _finish_node(client, node_id: str, code: int, args) -> int:
    if args.keep:
        print(f"node {node_id} left running (billing continues!)")
        return EXIT_OK if code == 0 else code
    if args.kill:
        kill_code = cmd_kill(args)
        return kill_code if kill_code != EXIT_OK else (
            EXIT_OK if code == 0 else code)
    try:
        client.power_off(node_id)
        wait_for(client, node_id, "paused", args.pause_timeout)
    except E2EError as exc:
        print(f"pause failed (check billing!): {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"node {node_id} paused: compute billing stopped, data kept")
    return EXIT_OK if code == 0 else code


def _state_node_id(args) -> str | None:
    node_id = args.node_id or load_state(args.workdir).get("node_id")
    if not node_id:
        print("no node id: pass it or run from the state directory",
              file=sys.stderr)
    return str(node_id) if node_id else None


def cmd_pause(args) -> int:
    cfg = load_config(args.config)
    node_id = _state_node_id(args)
    if not node_id:
        return EXIT_ERROR
    try:
        _client(cfg).power_off(node_id)
        wait_for(_client(cfg), node_id, "paused", args.pause_timeout)
    except E2EError as exc:
        print(f"pause failed (check billing!): {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"node {node_id} paused: compute billing stopped, data kept")
    return EXIT_OK


def cmd_resume(args) -> int:
    cfg = load_config(args.config)
    node_id = _state_node_id(args)
    if not node_id:
        return EXIT_ERROR
    client = _client(cfg)
    try:
        status, _ = node_status(client, node_id)
        if not is_paused(status) and not is_running(status):
            print(f"node {node_id} status is {status!r}, cannot resume",
                  file=sys.stderr)
            return EXIT_ERROR
        if is_paused(status):
            client.power_on(node_id)
            payload = wait_for(client, node_id, "running", BOOT_TIMEOUT_S)
            ip = extract_public_ip(payload)
            state = load_state(args.workdir)
            state.update({"node_id": node_id, "public_ip": ip})
            save_state(state, args.workdir)
            print(f"node {node_id} running at {ip}")
        else:
            print(f"node {node_id} already running")
    except E2EError as exc:
        print(f"resume failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def cmd_kill(args) -> int:
    cfg = load_config(args.config)
    node_id = _state_node_id(args)
    if not node_id:
        return EXIT_ERROR
    if not args.yes and sys.stdin.isatty():
        answer = input(f"delete node {node_id} irreversibly? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("aborted")
            return EXIT_ERROR
    try:
        try:
            status, _ = node_status(_client(cfg), node_id)
            print(f"node {node_id} status before delete: {status or '?'}")
        except E2EError as exc:  # noqa: BLE001 - confirm step, keep going
            print(f"warning: could not confirm node first: {exc}")
        _client(cfg).delete_node(node_id)
    except E2EError as exc:
        print(f"delete failed (check billing!): {exc}", file=sys.stderr)
        return EXIT_ERROR
    clear_state(args.workdir)
    print(f"node {node_id} deleted; state cleared")
    print("note: this tool never creates reserved IPs or volumes, so there "
          "is nothing else to release")
    return EXIT_OK


def cmd_status(args) -> int:
    cfg = load_config(args.config)
    node_id = _state_node_id(args)
    if not node_id:
        return EXIT_ERROR
    client = _client(cfg)
    try:
        status, payload = node_status(client, node_id)
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        ip = extract_public_ip(payload)
        print(f"node={node_id} status={status or '?'} ip={ip or '?'} "
              f"plan={data.get('plan', '?') if isinstance(data, dict) else '?'}")
        if args.billing:
            log = client.billing_log(node_id)
            print(json.dumps(log.get("data", log), indent=2)[:2000])
    except E2EError as exc:
        print(f"status failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def cmd_ssh(args) -> int:
    cfg = load_config(args.config)
    state = load_state(args.workdir)
    node_id = args.node_id or state.get("node_id")
    ip = state.get("public_ip", "")
    if not node_id or not ip:
        print("no node in state; pass --node-id and check status first",
              file=sys.stderr)
        return EXIT_ERROR
    if not args.remote_cmd:
        # Interactive shell.
        import subprocess

        target = f"{cfg.ssh_user}@{ip}"
        workdir = args.workdir or os.getcwd()
        from .runner import ssh_base

        return subprocess.run(
            ssh_base(cfg, workdir) + [target]).returncode
    proc = run_ssh(cfg, args.workdir or os.getcwd(), str(ip),
                   " ".join(args.remote_cmd), stream=True)
    return proc.returncode


def add_global_options(p) -> None:
    p.add_argument("--config",
                   help="JSON config file (non-secret defaults)")
    p.add_argument("--workdir",
                   help="directory holding .e2e-sim-state.json "
                        "(default: cwd)")
    p.add_argument("--node-id", help="override the node id from state")


def add_finish_options(p) -> None:
    p.add_argument("--keep", action="store_true",
                   help="leave the node running afterwards (bills!)")
    p.add_argument("--kill", action="store_true",
                   help="delete the node afterwards instead of pausing")
    p.add_argument("--yes", action="store_true",
                   help="skip the delete confirmation with --kill")
    p.add_argument("--ssh-timeout", type=int, default=600)
    p.add_argument("--pause-timeout", type=int, default=300)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="e2e-sim",
                                description="Ephemeral E2E xezim sim nodes: "
                                            "launch, run, pause or kill.")
    p.add_argument("--version", action="version", version=__version__)
    add_global_options(p)
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="list exact plan/image SKUs")
    d.add_argument("--family", default="",
                   help=f"plan family substring (default: "
                        f"{DEFAULTS['plan_family']})")
    d.add_argument("--write-config", default="",
                   help="write first match to this JSON config file")
    d.set_defaults(func=cmd_discover)

    u = sub.add_parser("up", help="create or resume the node")
    u.add_argument("--build", action="store_true",
                   help="also ensure xezim is ready (upload or build)")
    u.add_argument("--xezim-bin", default="",
                   help="local xezim binary to upload (skip node build)")
    u.add_argument("--ssh-timeout", type=int, default=600)
    u.add_argument("--build-timeout", type=int, default=3600)
    u.set_defaults(func=cmd_up)

    r = sub.add_parser("run", help="run a simulation, fetch results, pause")
    r.add_argument("--src", required=True, help="local design/tb directory")
    r.add_argument("--results", default="sim-results",
                   help="local results directory (default: sim-results)")
    r.add_argument("--xezim-bin", default="",
                   help="local xezim binary to upload (skip node build)")
    r.add_argument("--build-timeout", type=int, default=3600)
    add_finish_options(r)
    r.add_argument("xezim_args", nargs=argparse.REMAINDER,
                   help="xezim arguments after --")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("exec", help="run any command, then pause by default")
    e.add_argument("--src", default="",
                   help="local directory to upload before running")
    e.add_argument("--results", default="",
                   help="fetch the remote dir back here afterwards")
    add_finish_options(e)
    e.add_argument("cmd", nargs=argparse.REMAINDER,
                   help="command after --")
    e.set_defaults(func=cmd_exec)

    pa = sub.add_parser("pause", help="power off: stop compute billing")
    pa.add_argument("--pause-timeout", type=int, default=300)
    pa.set_defaults(func=cmd_pause)

    re = sub.add_parser("resume", help="power a paused node back on")
    re.set_defaults(func=cmd_resume)

    k = sub.add_parser("kill", help="delete the node irreversibly")
    k.add_argument("--yes", action="store_true",
                   help="skip the confirmation prompt")
    k.set_defaults(func=cmd_kill)

    s = sub.add_parser("status", help="show node status")
    s.add_argument("--billing", action="store_true",
                   help="also show the node billing log")
    s.set_defaults(func=cmd_status)

    sh = sub.add_parser("ssh", help="open a shell or run a remote command")
    sh.add_argument("remote_cmd", nargs=argparse.REMAINDER)
    sh.set_defaults(func=cmd_ssh)
    return p


def _strip_dashes(args) -> None:
    for attr in ("xezim_args", "remote_cmd", "cmd"):
        values = getattr(args, attr, None)
        if values and values[:1] == ["--"]:
            setattr(args, attr, values[1:])


def main(argv: list[str] | None = None) -> int:
    load_env_file(PACKAGE_ROOT / ".env")
    args = build_parser().parse_args(argv)
    _strip_dashes(args)
    try:
        return args.func(args)
    except E2EError as exc:
        print(f"e2e-sim: {exc}", file=sys.stderr)
        return EXIT_ERROR


def build_exec_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="e2e-exec",
        description="Run any command on the ephemeral E2E node "
                    "(resume if paused, pause afterwards by default).")
    p.add_argument("--version", action="version", version=__version__)
    add_global_options(p)
    p.add_argument("--src", default="",
                   help="local directory to upload before running")
    p.add_argument("--results", default="",
                   help="fetch the remote dir back here afterwards")
    add_finish_options(p)
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="command after --")
    return p


def exec_main(argv: list[str] | None = None) -> int:
    """`e2e-exec <normal command>` entry point."""
    load_env_file(PACKAGE_ROOT / ".env")
    args = build_exec_parser().parse_args(argv)
    _strip_dashes(args)
    try:
        return cmd_exec(args)
    except E2EError as exc:
        print(f"e2e-exec: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
