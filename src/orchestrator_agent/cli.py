"""orchestrate-agent CLI: run | validate | status."""
import argparse
import json
import os
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


LLM_MODES = ("auto", "on", "off")
EXIT_NEEDS_REVIEW = 3


class UsageError(Exception):
    pass


def _llm_mode(arg: str | None) -> str:
    mode = (arg or os.getenv("DV_AGENT_LLM_MODE", "") or "auto").strip().lower()
    if mode not in LLM_MODES:
        raise UsageError(f"LLM mode must be one of {LLM_MODES}, got {mode!r}")
    return mode


def _models_for(mode: str):
    from dv_agent.dense import MetaEmbedder
    from dv_agent.llm import MetaClient
    if mode == "off":
        return None, None
    key = os.getenv("MODEL_API_KEY", "").strip()
    if key == "":
        if mode == "on":
            raise UsageError("LLM mode is 'on' but MODEL_API_KEY is not set")
        return None, None
    llm = MetaClient()
    embedder = MetaEmbedder() if os.getenv("META_EMBED_MODEL", "").strip() else None
    return llm, embedder


def _parse_var(item: str) -> tuple[str, str]:
    name, sep, value = item.partition("=")
    if not sep or not name.strip():
        raise UsageError(f"--var needs NAME=VALUE, got {item!r}")
    return name.strip(), value


def _parse_approvals(items: list[str]) -> list[str]:
    approvals: list[str] = []
    for item in items:
        approvals.extend(a.strip() for a in item.split(",") if a.strip())
    return approvals


def _resume_hint(argv: list[str]) -> str:
    parts = ["orchestrate-agent"]
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if token == "--approve":
            skip_next = True
            continue
        if token.startswith("--approve="):
            continue
        parts.append(token)
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (UsageError, ValueError) as exc:
        message = exc.args[0] if exc.args else type(exc).__name__
        print(f"error: {message}", file=sys.stderr)
        return 2


def _main(argv: list[str] | None) -> int:
    load_env_file(PACKAGE_ROOT / ".env")
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="orchestrate-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="execute a flow file step by step")
    pr.add_argument("--flow", type=Path, required=True, help="flow JSON contract")
    pr.add_argument("--out", type=Path, required=True, help="orchestrator run directory")
    pr.add_argument("--repo", type=Path, help="spec repository (${repo})")
    pr.add_argument("--include", action="append", default=[], help="${include} entry (repeatable)")
    pr.add_argument("--rtl-files", action="append", default=[], help="${rtl_files} entry (repeatable)")
    pr.add_argument("--rtl-top", help="${rtl_top}")
    pr.add_argument("--scope", default="", help="${scope}")
    pr.add_argument("--template", type=Path, help="${template}")
    pr.add_argument("--clock", help="${clock}")
    pr.add_argument("--reset", help="${reset}")
    pr.add_argument("--reset-active", choices=("high", "low"), help="${reset_active}")
    pr.add_argument("--agent-args", type=Path, help="${agent_args}")
    pr.add_argument("--var", action="append", default=[], metavar="NAME=VALUE",
                    help="extra flow variable (repeatable)")
    pr.add_argument("--approve", action="append", default=[],
                    help="approved step id(s), comma-separated (repeatable)")
    pr.add_argument("--llm", choices=LLM_MODES, help="auto (default), on, or off")
    pr.add_argument("--dry-run", action="store_true", help="resolve and guard every step, run nothing")
    pr.add_argument("--force", action="store_true", help="rerun stages even if outputs exist")

    pv = sub.add_parser("validate", help="check a flow file without running it")
    pv.add_argument("--flow", type=Path, required=True)

    ps = sub.add_parser("status", help="show the result and pending review of a run")
    ps.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(args_list)
    if args.cmd == "validate":
        from .flow import load_flow
        from .guards import unknown_rules
        from .tools import REGISTRY
        flow = load_flow(args.flow)
        problems = [f"unknown tool {t!r}" for t in sorted({s["tool"] for s in flow["steps"]}
                                                          - set(REGISTRY))]
        problems += [f"unknown never-do rule {r!r}"
                     for r in unknown_rules([r["id"] for r in flow["forbidden"]])]
        if problems:
            raise UsageError("invalid flow: " + "; ".join(problems))
        print(json.dumps(dict(status="PASS", flow=str(args.flow), name=flow["name"],
                               steps=[dict(id=s["id"], tool=s["tool"], agent=s["agent"],
                                           optional=s["optional"],
                                           review_gate=s["review_gate"]) for s in flow["steps"]],
                               forbidden=[r["id"] for r in flow["forbidden"]],
                               policy=flow["policy"]), indent=2))
        return 0
    if args.cmd == "status":
        from .runner import RESULT_FILE, REVIEW_FILE
        result_path = args.out / RESULT_FILE
        if not result_path.is_file():
            raise UsageError(f"no orchestrator result in {args.out}")
        shown = dict(json.loads(result_path.read_text(encoding="utf-8")))
        review_path = args.out / REVIEW_FILE
        if review_path.is_file():
            shown["review"] = json.loads(review_path.read_text(encoding="utf-8"))
        print(json.dumps(shown, indent=2, default=str))
        return 0

    from .runner import run_flow
    if not args.flow.is_file():
        raise UsageError(f"flow file not found: {args.flow}")
    variables: dict = {"include": list(args.include),
                       "rtl_files": list(args.rtl_files), "scope": args.scope}
    if args.repo is not None:
        variables["repo"] = str(args.repo)
    if args.rtl_top:
        variables["rtl_top"] = args.rtl_top
    if args.template is not None:
        variables["template"] = str(args.template)
    if args.clock:
        variables["clock"] = args.clock
    if args.reset:
        variables["reset"] = args.reset
    if args.reset_active:
        variables["reset_active"] = args.reset_active
    if args.agent_args is not None:
        variables["agent_args"] = str(args.agent_args)
    for item in args.var:
        name, value = _parse_var(item)
        variables[name] = value
    llm, embedder = _models_for(_llm_mode(args.llm))
    result = run_flow(args.flow, out_dir=args.out, variables=variables, llm=llm,
                      embedder=embedder, approvals=_parse_approvals(args.approve),
                      dry_run=args.dry_run, force=args.force,
                      resume_hint=_resume_hint(args_list))
    print(json.dumps(result, indent=2, default=str))
    if result["status"] == "PASS":
        return 0
    if result["status"] == "NEEDS_REVIEW":
        print(f"owner review required: {result['reason']}", file=sys.stderr)
        return EXIT_NEEDS_REVIEW
    print(f"blocked: {result['reason']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
