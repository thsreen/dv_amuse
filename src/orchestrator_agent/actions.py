"""Plan-backed code and bounded local simulation for the four-command terminal."""
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from dv_agent.fsutil import atomic_write_text
from dv_agent.uvm import build_uvm, write_uvm

CODE_MANIFEST = "code_manifest.json"
SIM_TIMEOUT_S = 180


def documented_plan(plan: dict) -> tuple[dict, dict]:
    """Keep only statements directly backed by a cited specification source."""
    filtered = {"sections": [
        {key: copy.deepcopy(value) for key, value in section.items()
         if key in ("id", "generator", "entries", "configurations", "strategy")}
        for section in plan.get("sections", [])]}
    kept = 0
    skipped = 0
    def eligible(item):
        return (item.get("provenance") == "DOCUMENTED"
                and bool(item.get("cited_req_ids") or item.get("cited_chunk_ids")))
    for section in filtered.get("sections", []):
        for field in ("entries", "configurations"):
            if isinstance(section.get(field), list):
                original = section[field]
                section[field] = [item for item in original if eligible(item)]
                kept += len(section[field])
                skipped += len(original) - len(section[field])
        if section.get("id") == "strategy" and isinstance(section.get("strategy"), dict):
            strategy = section["strategy"]
            for field in ("agents", "scoreboards"):
                original = strategy.get(field, [])
                strategy[field] = [item for item in original if eligible(item)]
                kept += len(strategy[field])
                skipped += len(original) - len(strategy[field])
            for field in ("environment", "register_model", "virtual_sequences", "rtl_observation_actions"):
                strategy[field] = [] if isinstance(strategy.get(field), list) else None
        if section.get("generator") == "rtl_observations":
            section["entries"] = []
    filtered["code_policy"] = {"source": "documented specification entries only",
                               "kept": kept, "skipped": skipped,
                               "rtl_observations": "excluded from code"}
    return filtered, filtered["code_policy"]


def _clock_reset(definition: dict, rtl_files: list[Path]) -> tuple[str, str | None, str | None]:
    inputs = [p["name"] for p in definition["ports"] if p["direction"] == "input"
              and p.get("width", 1) == 1]
    clocks = [p for p in inputs if re.search(r"(^|_)(clk|clock)(_|$)", p.lower())]
    if len(clocks) != 1:
        raise ValueError("could not identify one scalar DUT clock from the interface")
    resets = [p for p in inputs if re.search(r"(^|_)(rst|reset)(_|$)", p.lower())]
    if len(resets) > 1:
        raise ValueError("multiple reset inputs; choose one before code generation")
    reset = resets[0] if resets else None
    active = None
    if reset:
        evidence = "\n".join(p.read_text(encoding="utf-8", errors="replace")[:256_000] for p in rtl_files[:32])
        high = bool(re.search(r"\bposedge\s+" + re.escape(reset) + r"\b", evidence))
        low = bool(re.search(r"\bnegedge\s+" + re.escape(reset) + r"\b", evidence))
        if high == low:
            raise ValueError(f"reset polarity for {reset} is not unambiguous in the RTL")
        active = "high" if high else "low"
    return clocks[0], reset, active


def _smoke_source(top: str, definition: dict, clock: str, reset: str | None, active: str | None) -> str:
    ports = definition["ports"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", top):
        raise ValueError("invalid RTL top module")
    lines = ["// Basic compile, clock and reset smoke test; no functional behavior claimed.",
             "module orchestrator_smoke_tb;"]
    for p in ports:
        name = p["name"]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
            raise ValueError(f"unsupported port identifier {name!r}")
        width = p.get("range") or (f"[{p['width']-1}:0]" if p.get("width", 1) > 1 else "")
        if width and not re.fullmatch(r"\[\d+\s*:\s*\d+\]", width):
            raise ValueError(f"unsupported port range for {name}: {width}")
        kind = "wire" if p["direction"] == "output" else "reg"
        value = "" if kind == "wire" else (" = 0" if name == clock else
                (" = 1" if active == "high" else " = 0") if name == reset else " = '0")
        lines.append(f"  {kind} {width} {name}{value};")
    lines += [f"  {top} dut (" + ", ".join(f".{p['name']}({p['name']})" for p in ports) + ");",
              f"  always #5 {clock} = ~{clock};", "  initial begin"]
    if reset:
        lines += [f"    repeat (3) @(posedge {clock});",
                  f"    {reset} = {'0' if active == 'high' else '1'};"]
    lines += [f"    repeat (10) @(posedge {clock});", '    $display("BASIC_SMOKE_PASS");',
              "    $finish;", "  end", "  initial begin #1000; $fatal(1, \"smoke timeout\"); end",
              "endmodule", ""]
    return "\n".join(lines)


def build_code(out: Path, variables: dict) -> dict:
    plan_path = out / "dv" / "testplan_doc.json"
    interface_path = out / "rtl" / "interface_definition.json"
    if not plan_path.is_file() or not interface_path.is_file():
        raise ValueError("/code needs a saved plan and JSON interface; run /plan first")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    definition = json.loads(interface_path.read_text(encoding="utf-8"))
    rtl_files = [Path(p).resolve() for p in variables.get("rtl_graph_files", [])]
    if not rtl_files or any(not p.is_file() for p in rtl_files):
        raise ValueError("the saved RTL source list is missing; name the repository again")
    clock, reset, active = _clock_reset(definition, rtl_files)
    filtered, policy = documented_plan(plan)
    digest = hashlib.sha256((json.dumps(filtered, sort_keys=True) + json.dumps(definition, sort_keys=True)
                             + "documented-code-v1").encode()).hexdigest()[:12]
    code_dir = out / "code" / digest
    manifest_path = out / CODE_MANIFEST
    if code_dir.exists():
        existing = code_dir / "tests.json"
        if not existing.is_file():
            raise ValueError(f"code output exists without a complete manifest: {code_dir}")
        manifest = json.loads(existing.read_text(encoding="utf-8"))
        atomic_write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
        return manifest | {"reused": True}
    prefix = re.sub(r"[^a-zA-Z0-9_]", "_", variables["rtl_top"]).lower()
    artifacts, uvm_manifest = build_uvm(definition, prefix=prefix, clock=clock,
                                        reset=reset, reset_active=active, plan=filtered)
    write_uvm(code_dir, artifacts, inputs=[plan_path, interface_path], force=False)
    atomic_write_text(code_dir / "documented_plan.json", json.dumps(filtered, indent=2) + "\n")
    atomic_write_text(code_dir / "orchestrator_smoke_tb.sv",
                      _smoke_source(variables["rtl_top"], definition, clock, reset, active))
    manifest = dict(status="BUILT_NEEDS_REVIEW", source_plan=str(plan_path), interface=str(interface_path),
                    code_dir=str(code_dir), top=variables["rtl_top"], clock=clock, reset=reset,
                    reset_active=active, rtl_files=[str(p) for p in rtl_files], policy=policy,
                    uvm_status=uvm_manifest["status"],
                    tests=[dict(name="basic_smoke", kind="rtl_smoke", top="orchestrator_smoke_tb",
                                source=str(code_dir / "orchestrator_smoke_tb.sv"),
                                scope="compile, clock and reset only; no functional checks")])
    atomic_write_text(code_dir / "tests.json", json.dumps(manifest, indent=2) + "\n")
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    return manifest | {"reused": False}


def run_tests(out: Path, *, regress: bool = False) -> dict:
    path = out / CODE_MANIFEST
    if not path.is_file():
        raise ValueError("no built tests; run /code first")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    tests = manifest.get("tests", [])
    if not tests:
        raise ValueError("code manifest has no built tests")
    binary = os.getenv("XEZIM_BIN") or shutil.which("xezim")
    if not binary or not Path(binary).is_file():
        raise ValueError("xezim executable not found; set XEZIM_BIN to a local xezim binary")
    selected = tests if regress else tests[:1]
    results = []
    for test in selected:
        if test.get("kind") != "rtl_smoke" or test.get("name") != "basic_smoke":
            results.append(dict(name=test.get("name"), status="BLOCKED", reason="unsupported test kind"))
            continue
        rtl = [Path(p) for p in manifest["rtl_files"]]
        if any(not p.is_file() for p in rtl):
            results.append(dict(name=test["name"], status="BLOCKED", reason="RTL source missing"))
            continue
        source = Path(test["source"])
        if not source.is_file():
            results.append(dict(name=test["name"], status="BLOCKED", reason="built test source missing"))
            continue
        includes = sorted({str(p.parent) for p in rtl})
        cmd = [str(binary), "--simulate", "-s", test["top"]]
        for directory in includes:
            cmd += ["-I", directory]
        cmd += [str(p) for p in rtl] + [str(source)]
        try:
            completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, timeout=SIM_TIMEOUT_S, check=False)
            output = completed.stdout
            status = "PASS" if completed.returncode == 0 and "BASIC_SMOKE_PASS" in output else "FAIL"
            reason = f"xezim exit {completed.returncode}"
        except subprocess.TimeoutExpired as exc:
            captured = exc.stdout or ""
            output, status, reason = (captured.decode(errors="replace") if isinstance(captured, bytes) else captured), "TIMEOUT", "simulation timed out"
        log = out / "simulation" / f"{test['name']}.log"
        atomic_write_text(log, output)
        results.append(dict(name=test["name"], status=status, reason=reason, log=str(log)))
    report = dict(status="PASS" if all(r["status"] == "PASS" for r in results) else "BLOCKED",
                  tests=results, mode="regress" if regress else "run")
    atomic_write_text(out / "simulation" / f"{report['mode']}.json", json.dumps(report, indent=2) + "\n")
    return report
