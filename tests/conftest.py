from pathlib import Path

import pytest

from dv_agent.core.llm import FakeLLM

PAGES = [
    """ACME TMR32 datasheet
TMR32 Timer IP Core
Specification
Contents
Introduction ........ 1
Registers ........ 2
Interrupts ........ 3
Confidential - page 1 of 3""",
    """ACME TMR32 datasheet
1
Introduction
The TMR32 is a 32-bit down-counting timer with a programmable reload value.

2 Registers
2.1 Control Register (CTRL)
Bit # Access Description
0 RW Enable. When '1' the counter decrements on every clock cycle.
1 RW Interrupt enable. When '1' the IRQ output is asserted when the counter reaches zero.
Reset Value: 00h
Confidential - page 2 of 3""",
    """ACME TMR32 datasheet
2.2 Reload Register (RELOAD)
The counter loads the RELOAD value when it reaches zero and the Enable bit is set.
3 Interrupts
The IRQ output stays asserted until software writes 1 to STATUS bit 0.

4 Interface Signals
Port Width Direction Description
CLK 1 Input Clock input
RST_N 1 Input Active-low asynchronous reset
BUS_ADDR 4 Input Register address
BUS_WDATA 32 Input Write data
BUS_RDATA 32 Output Read data
BUS_WE 1 Input Write enable
IRQ 1 Output Interrupt request to the interrupt controller
TICK_O 1 Output Optional tick pulse, present when TMR_HAS_TICK is defined
Confidential - page 3 of 3""",
]


@pytest.fixture
def spec_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "tmr32"
    (repo / "doc" / "old").mkdir(parents=True)
    (repo / "rtl").mkdir()
    (repo / "doc" / "tmr32_spec.txt").write_text("\f".join(PAGES), encoding="utf-8")
    (repo / "doc" / "old" / "tmr32_spec.doc").write_bytes(b"\xd0\xcf\x11\xe0legacy")
    (repo / "doc" / "CHANGES.txt").write_text("1.1 fixed things\n")
    (repo / "rtl" / "notes.txt").write_text("design source, not a specification\n")
    (repo / "README.md").write_text("# tmr32\n")
    return repo


def _req(statement, quote, kind, entities):
    return {"statement": statement, "quote": quote, "kind": kind, "entities": entities}


def extraction_handler(payload: dict) -> dict:
    text = payload["text"]
    if "Control Register" in text:
        return {"summary": "CTRL register enable and interrupt enable bits.",
                "entities": [{"name": "Control Register (CTRL)", "kind": "register", "aliases": []},
                             {"name": "IRQ", "kind": "signal", "aliases": []}],
                "requirements": [
                    # Curly quotes: must still match the straight quotes in the source.
                    _req("When CTRL.Enable is 1 the counter decrements every clock cycle.",
                         "When ‘1’ the counter decrements on every clock cycle", "register",
                         ["Control Register (CTRL)"]),
                    _req("CTRL resets to 00h.", "Reset Value: 00h", "reset", ["CTRL"]),
                    _req("Invented requirement.", "This text is not in the chunk", "other", [])]}
    if "Reload Register" in text:
        return {"summary": "RELOAD register and IRQ clearing.",
                "entities": [{"name": "Reload Register (RELOAD)", "kind": "register", "aliases": []}],
                "requirements": [
                    _req("On reaching zero with Enable set, the counter loads RELOAD.",
                         "The counter loads the RELOAD value when it reaches zero and the Enable bit is set",
                         "functional", ["RELOAD", "CTRL"])]}
    if "STATUS bit 0" in text:
        return {"summary": "IRQ clearing.", "entities": [],
                "requirements": [
                    _req("IRQ stays asserted until software writes 1 to STATUS bit 0.",
                         "The IRQ output stays asserted until software writes 1 to STATUS bit 0",
                         "functional", ["IRQ"])]}
    return {"summary": "", "entities": [], "requirements": []}


def dependency_handler(payload: dict) -> dict:
    by_text = {r["statement"]: r["req_id"] for r in payload["requirements"]}
    reload_id = next((v for k, v in by_text.items() if k.startswith("On reaching zero")), None)
    enable_id = next((v for k, v in by_text.items() if k.startswith("When CTRL.Enable")), None)
    if not (reload_id and enable_id):
        return {"edges": []}
    return {"edges": [
        {"src": reload_id, "dst": enable_id, "type": "DEPENDS_ON",
         "rationale": "Reload happens only when the counter is enabled.",
         "evidence_quote": "the Enable bit is set"},
        {"src": enable_id, "dst": reload_id, "type": "REFINES",
         "rationale": "unsupported", "evidence_quote": "text that appears nowhere"}]}


def rerank_handler(payload: dict) -> dict:
    question = payload["question"].lower()
    judgements, sufficient, missing = [], True, ""
    for c in payload["chunks"]:
        text = c["text"].lower()
        rel = 3 if ("reload" in text and "reload" in question) else 0
        if "counter" in question and "counter" in text:
            rel = max(rel, 2)
        judgements.append({"chunk_id": c["chunk_id"], "relevance": rel})
    if "enable" not in payload["focus"].lower():
        sufficient, missing = False, "Enable bit semantics"
    return {"judgements": judgements, "sufficient": sufficient, "missing": missing}


def plan_handler(payload: dict) -> dict:
    req = payload["requirement"]["req_id"]
    chunks = [c["chunk_id"] for c in payload["chunks"]]
    item = {"objective": f"Verify {payload['requirement']['kind']} behaviour of the counter reload",
            "checks": ["Enable the counter, run to zero, observe the reload value"],
            "cited_req_ids": [req], "cited_chunk_ids": chunks,
            "assumptions": [], "open_questions": [], "needs_review": False}
    bogus = dict(item, objective="Bogus citation", cited_req_ids=["REQ-bogus"])
    return {"items": [item, bogus]}


def interfaces_handler(payload: dict) -> dict:
    cid = next(c["chunk_id"] for c in payload["chunks"] if "Interface Signals" in c["text"])

    def sig(name, width, direction, desc, availability="", level="not_applicable"):
        row = next(line for line in payload["chunks"][[c["chunk_id"] for c in payload["chunks"]].index(cid)]["text"].splitlines()
                   if line.startswith(name + " "))
        return {"name": name, "width": width, "direction": direction, "active_level": level,
                "availability": availability, "description": desc, "quote": row, "chunk_id": cid}
    return {"signals": [
        sig("CLK", "1", "input", "Clock input", level="rising_edge"),
        sig("RST_N", "1", "input", "Active-low asynchronous reset", level="low"),
        sig("BUS_ADDR", "4", "input", "Register address"),
        sig("BUS_WDATA", "32", "input", "Write data"),
        sig("BUS_RDATA", "32", "output", "Read data"),
        sig("BUS_WE", "1", "input", "Write enable"),
        sig("IRQ", "1", "output", "Interrupt request", level="high"),
        sig("TICK_O", "1", "output", "Optional tick pulse", "TMR_HAS_TICK defined"),
        {"name": "GHOST_SIG", "width": "1", "direction": "input", "active_level": "unknown", "availability": "", "description": "invented",
         "quote": "GHOST_SIG 1 Input", "chunk_id": cid}],
        "groups": [
            {"name": "Register bus", "function": "Register read/write", "category": "bus", "protocol": "",
             "connected_to": "system bus master", "peer_type": "processor_or_bus_master", "dut_role": "responder", "is_sideband": False,
             "signals": ["BUS_ADDR", "BUS_WDATA", "BUS_RDATA", "BUS_WE", "GHOST_SIG"], "rationale": "bus signals"},
            {"name": "Clock", "function": "Clock", "category": "clock", "protocol": "", "connected_to": "clock generator", "peer_type": "clock_generator",
             "dut_role": "sink", "is_sideband": False, "signals": ["CLK"], "rationale": ""},
            {"name": "Reset", "function": "Reset", "category": "reset", "protocol": "", "connected_to": "reset controller", "peer_type": "reset_controller",
             "dut_role": "sink", "is_sideband": False, "signals": ["RST_N", "CLK"], "rationale": ""},
            {"name": "Interrupt", "function": "Interrupt request", "category": "interrupt", "protocol": "",
             "connected_to": "interrupt controller", "peer_type": "interrupt_controller", "dut_role": "source", "is_sideband": True,
             "signals": ["IRQ"], "rationale": "single-wire sideband"}]}


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM({"spec_requirements": extraction_handler,
                    "requirement_dependencies": dependency_handler,
                    "rerank_chunks": rerank_handler,
                    "test_plan_items": plan_handler})


@pytest.fixture(autouse=True)
def no_langfuse(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    # Ordinary CLI tests must not reload real credentials from the developer's .env.
    monkeypatch.setattr("dv_agent.cli.load_env_file", lambda path: None)


@pytest.fixture(autouse=True)
def _clear_progress_sinks():
    yield
    from dv_agent.core.progress import set_global_sink, set_sink
    set_sink(None)
    set_global_sink(None)
